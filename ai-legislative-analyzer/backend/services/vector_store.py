import os
import re
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

class VectorService:
    def __init__(self, collection_name="legislative_docs"):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        db_path = os.path.join(base_dir, "chroma_db")
        if not os.path.exists(db_path):
            os.makedirs(db_path)
            
        self.client = chromadb.PersistentClient(path=db_path)
        
        self.openai_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        
        self.collection = self.client.get_or_create_collection(
            name=collection_name, 
            embedding_function=self.openai_ef
        )

        self._bm25_index: Optional[BM25Okapi] = None
        self._bm25_entries: List[Dict[str, Any]] = []
        self._build_bm25_index_from_chroma()

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[A-Za-z0-9_]+", (text or "").lower())

    def _build_bm25_index_from_chroma(self) -> None:
        payload = self.collection.get(include=["documents", "metadatas"])

        ids = payload.get("ids") or []
        documents = payload.get("documents") or []
        metadatas = payload.get("metadatas") or []

        entries: List[Dict[str, Any]] = []
        tokenized_corpus: List[List[str]] = []

        for index, chunk_id in enumerate(ids):
            content = documents[index] if index < len(documents) else ""
            metadata = metadatas[index] if index < len(metadatas) else {}
            tokens = self._tokenize(content)

            # BM25 requires at least one token per record.
            tokenized_corpus.append(tokens if tokens else ["__empty__"])
            entries.append(
                {
                    "id": chunk_id,
                    "content": content,
                    "metadata": metadata or {},
                }
            )

        self._bm25_entries = entries
        self._bm25_index = BM25Okapi(tokenized_corpus) if tokenized_corpus else None

    def _vector_query(
        self,
        query: str,
        n_results: int,
        document_id: str = None,
    ) -> List[Dict[str, Any]]:
        query_kwargs: Dict[str, Any] = {
            "query_texts": [query],
            "n_results": n_results,
        }
        if document_id:
            query_kwargs["where"] = {"document_id": document_id}

        results = self.collection.query(**query_kwargs)

        formatted_results: List[Dict[str, Any]] = []
        documents_row = (results.get("documents") or [[]])[0]
        metadatas_row = (results.get("metadatas") or [[]])[0]
        ids_row = (results.get("ids") or [[]])[0]
        distances_row = (results.get("distances") or [[]])[0]

        for i in range(len(documents_row)):
            formatted_results.append(
                {
                    "id": ids_row[i] if i < len(ids_row) else f"vector_{i}",
                    "content": documents_row[i],
                    "metadata": metadatas_row[i] if i < len(metadatas_row) else {},
                    "distance": distances_row[i] if i < len(distances_row) else 1.0,
                }
            )

        return formatted_results

    def _bm25_query(
        self,
        query: str,
        n_results: int,
        document_id: str = None,
    ) -> List[Dict[str, Any]]:
        if self._bm25_index is None:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = self._bm25_index.get_scores(query_tokens)
        ranked_indices = sorted(
            range(len(scores)),
            key=lambda idx: float(scores[idx]),
            reverse=True,
        )

        matches: List[Dict[str, Any]] = []
        for index in ranked_indices:
            entry = self._bm25_entries[index]
            metadata = entry.get("metadata") or {}

            if document_id and metadata.get("document_id") != document_id:
                continue

            matches.append(
                {
                    "id": entry.get("id"),
                    "content": entry.get("content", ""),
                    "metadata": metadata,
                    "bm25_score": float(scores[index]),
                }
            )

            if len(matches) >= n_results:
                break

        return matches

    def _fuse_with_rrf(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        n_results: int,
        rrf_k: int,
    ) -> List[Dict[str, Any]]:
        fused: Dict[str, Dict[str, Any]] = {}

        for rank, item in enumerate(vector_results, start=1):
            chunk_id = item.get("id")
            if not chunk_id:
                continue

            bucket = fused.setdefault(
                chunk_id,
                {
                    "id": chunk_id,
                    "content": item.get("content", ""),
                    "metadata": item.get("metadata", {}),
                    "distance": item.get("distance", 1.0),
                    "bm25_score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": None,
                    "rrf_score": 0.0,
                },
            )
            bucket["vector_rank"] = rank
            bucket["rrf_score"] += 1.0 / (rrf_k + rank)

        for rank, item in enumerate(bm25_results, start=1):
            chunk_id = item.get("id")
            if not chunk_id:
                continue

            bucket = fused.setdefault(
                chunk_id,
                {
                    "id": chunk_id,
                    "content": item.get("content", ""),
                    "metadata": item.get("metadata", {}),
                    "distance": 1.0,
                    "bm25_score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": None,
                    "rrf_score": 0.0,
                },
            )
            bucket["bm25_rank"] = rank
            bucket["bm25_score"] = item.get("bm25_score", 0.0)
            bucket["rrf_score"] += 1.0 / (rrf_k + rank)

        ranked = sorted(
            fused.values(),
            key=lambda value: value["rrf_score"],
            reverse=True,
        )[:n_results]

        return [
            {
                "content": item["content"],
                "metadata": item["metadata"],
                "distance": item["distance"],
                "bm25_score": round(item["bm25_score"], 6),
                "vector_rank": item["vector_rank"],
                "bm25_rank": item["bm25_rank"],
                "fusion_score": round(item["rrf_score"], 6),
            }
            for item in ranked
        ]

    def add_to_store(self, chunks: List[Dict], document_id: str, document_name: str):
        ids = []
        documents = []
        metadatas = []
        
        for idx, chunk in enumerate(chunks):
            ids.append(f"{document_id}_{idx}")
            documents.append(chunk['content'])
            metadatas.append({
                "document_id": document_id,
                "document_name": document_name,
                "chapter": chunk['chapter'],
                "chunk_index": idx,
                "full_text": chunk.get('full_text', chunk['content']),
                "original_token_count": chunk.get('original_token_count', 0),
                "compressed_token_count": chunk.get('compressed_token_count', 0),
            })
            
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

        # Keep BM25 index in sync after upserts.
        self._build_bm25_index_from_chroma()

    def hybrid_query(
        self,
        query: str,
        n_results: int = 3,
        document_id: str = None,
        vector_k: int = 12,
        bm25_k: int = 12,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        vector_results = self._vector_query(
            query=query,
            n_results=max(n_results, vector_k),
            document_id=document_id,
        )
        bm25_results = self._bm25_query(
            query=query,
            n_results=max(n_results, bm25_k),
            document_id=document_id,
        )

        return self._fuse_with_rrf(
            vector_results=vector_results,
            bm25_results=bm25_results,
            n_results=n_results,
            rrf_k=rrf_k,
        )

    def query_docs(self, query: str, n_results: int = 3, document_id: str = None) -> List[Dict[str, Any]]:
        # Backward-compatible alias for existing call sites.
        return self.hybrid_query(query=query, n_results=n_results, document_id=document_id)

    def clear_collection(self):
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.create_collection(
            self.collection.name,
            embedding_function=self.openai_ef,
        )
        self._build_bm25_index_from_chroma()
