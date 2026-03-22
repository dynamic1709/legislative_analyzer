import json
import os
from copy import deepcopy
from typing import Any, Dict, List, Optional


class DocumentRegistry:
    def __init__(self, storage_path: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        self.storage_path = storage_path or os.path.join(data_dir, "documents.json")
        self._documents = self._load_documents()

    def _load_documents(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.storage_path):
            return []

        try:
            with open(self.storage_path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except (OSError, json.JSONDecodeError):
            return []

        return payload if isinstance(payload, list) else []

    def _save_documents(self) -> None:
        with open(self.storage_path, "w", encoding="utf-8") as file_handle:
            json.dump(self._documents, file_handle, indent=2, ensure_ascii=True)

    def _refresh_documents(self) -> None:
        self._documents = self._load_documents()

    def upsert_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        self._refresh_documents()
        replaced = False
        for index, existing_document in enumerate(self._documents):
            if existing_document.get("document_id") == document.get("document_id"):
                self._documents[index] = deepcopy(document)
                replaced = True
                break

        if not replaced:
            self._documents.append(deepcopy(document))

        self._documents.sort(key=lambda item: item.get("uploaded_at", ""), reverse=True)
        self._save_documents()
        return deepcopy(document)

    def list_documents(self, limit: int = 10) -> List[Dict[str, Any]]:
        self._refresh_documents()
        return deepcopy(self._documents[:limit])

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        self._refresh_documents()
        for document in self._documents:
            if document.get("document_id") == document_id:
                return deepcopy(document)
        return None

    def find_by_external_id(self, external_id: str) -> Optional[Dict[str, Any]]:
        self._refresh_documents()
        for document in self._documents:
            source = document.get("source", {})
            if source.get("external_id") == external_id:
                return deepcopy(document)
        return None

    def get_latest_document(self) -> Optional[Dict[str, Any]]:
        self._refresh_documents()
        if not self._documents:
            return None
        return deepcopy(self._documents[0])

    def build_stats(self) -> Dict[str, Any]:
        self._refresh_documents()
        documents = self.list_documents(limit=len(self._documents))
        total_original_tokens = sum(
            doc.get("metrics", {}).get("original_tokens", 0) for doc in documents
        )
        total_compressed_tokens = sum(
            doc.get("metrics", {}).get("compressed_tokens", 0) for doc in documents
        )
        total_tokens_saved = sum(
            doc.get("metrics", {}).get("tokens_saved", 0) for doc in documents
        )
        average_compression = 0.0

        if documents:
            average_compression = round(
                sum(doc.get("metrics", {}).get("compression_percentage", 0.0) for doc in documents)
                / len(documents),
                2,
            )

        return {
            "document_count": len(documents),
            "total_original_tokens": total_original_tokens,
            "total_compressed_tokens": total_compressed_tokens,
            "total_tokens_saved": total_tokens_saved,
            "average_compression_percentage": average_compression,
            "auto_ingested_count": sum(
                1 for doc in documents if doc.get("ingestion_type") == "auto-feed"
            ),
        }