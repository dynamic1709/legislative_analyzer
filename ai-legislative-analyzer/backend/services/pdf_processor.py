import pdfplumber
import re
import io
import logging
from pathlib import Path
from typing import Any, Dict, List

from .token_utils import estimate_tokens, normalize_whitespace, split_sentences, trim_to_token_budget


LOGGER = logging.getLogger(__name__)

class LegislativeProcessor:
    def __init__(self):
        self.chapter_re = re.compile(r'CHAPTER\s+([IVXLCDM\d]+)', re.IGNORECASE)
        self.section_re = re.compile(r'^(\d+)\.\s+', re.MULTILINE)
        self.reference_re = re.compile(
            r'\b(?:Section|Sections|Clause|Clauses|Article|Articles|Rule|Rules)\s+[\dA-Za-z\.\-\(\)]+(?:\s*(?:,|and)\s*[\dA-Za-z\.\-\(\)]+)*',
            re.IGNORECASE,
        )
        self.legal_keywords = {
            "shall",
            "must",
            "means",
            "includes",
            "penalty",
            "liable",
            "offence",
            "duty",
            "obligation",
            "prohibited",
            "exemption",
            "authority",
            "board",
            "government",
            "citizen",
            "person",
            "company",
            "compliance",
            "within",
            "days",
            "months",
            "appeal",
            "license",
            "registration",
        }
        self.priority_phrases = (
            "shall",
            "must",
            "means",
            "includes",
            "penalty",
            "liable",
            "offence",
            "within",
            "subject to",
            "provided that",
            "notwithstanding",
        )
        self.retrieval_boilerplate_patterns = tuple(
            re.compile(pattern, re.IGNORECASE)
            for pattern in (
                r"\bit\s+is\s+hereby\s+declared\s+that\b",
                r"\bfor\s+the\s+removal\s+of\s+doubts\b",
                r"\bas\s+the\s+case\s+may\s+be\b",
                r"\bunless\s+the\s+context\s+otherwise\s+requires\b",
                r"\bfor\s+the\s+purposes\s+of\s+this\s+(?:act|section|chapter|rule)\b",
                r"\bsave\s+as\s+otherwise\s+provided\s+in\s+this\s+act\b",
                r"\bwithout\s+prejudice\s+to\s+the\s+generality\s+of\s+the\s+foregoing\b",
            )
        )
        self.stakeholder_map = {
            "Citizens and Consumers": ["citizen", "person", "consumer", "resident", "individual", "data principal"],
            "Businesses and Employers": ["company", "employer", "business", "entity", "intermediary", "data fiduciary"],
            "Government and Regulators": ["government", "board", "authority", "commission", "tribunal", "state"],
            "Courts and Enforcement": ["court", "judge", "appeal", "police", "investigation", "enforcement"],
        }

    def extract_text(self, file_content: bytes) -> str:
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            return self._extract_text_from_pdf(pdf)

    def extract_text_from_path(self, file_path: str) -> str:
        with pdfplumber.open(file_path) as pdf:
            return self._extract_text_from_pdf(pdf)

    def _extract_text_from_pdf(self, pdf) -> str:
        text = ""
        for page in pdf.pages:
            text += page.extract_text() or ""
            text += "\n"
        return text

    def chunk_by_structure(self, text: str) -> List[Dict]:
        chunks = []
        current_chapter = "General/Intro"
        current_text = ""
        
        lines = text.split('\n')
        for line in lines:
            # Detect Chapter start
            chapter_match = self.chapter_re.search(line)
            if chapter_match:
                if current_text:
                    chunks.append({"chapter": current_chapter, "content": current_text.strip()})
                    current_text = ""
                current_chapter = line.strip()
                continue
            
            # Detect Section/Clause start (e.g., "5. Definitions.")
            section_match = self.section_re.search(line)
            if section_match:
                if current_text:
                    chunks.append({"chapter": current_chapter, "content": current_text.strip()})
                    current_text = ""

            current_text += line + "\n"

        if current_text:
            chunks.append({"chapter": current_chapter, "content": current_text.strip()})

        return self._split_large_chunks(chunks)

    def compress_context(
        self,
        chunks: List[Dict[str, Any]],
        max_tokens_per_chunk: int = 180,
        target_ratio: float = 10.0,
        filename: str = "Document",
    ) -> Dict[str, Any]:
        compressed_chunks = []
        total_original_tokens = 0
        total_compressed_tokens = 0
        safe_ratio = max(target_ratio, 1.0)

        for chunk in chunks:
            original_content = normalize_whitespace(chunk['content'])
            if not original_content:
                continue

            original_token_count = estimate_tokens(original_content)
            compressed_content = self._compress_chunk(original_content, max_tokens_per_chunk)
            compressed_token_count = estimate_tokens(compressed_content)

            total_original_tokens += original_token_count
            total_compressed_tokens += compressed_token_count

            compressed_chunks.append({
                "chapter": chunk['chapter'],
                "full_text": original_content,
                "content": compressed_content,
                "original_token_count": original_token_count,
                "compressed_token_count": compressed_token_count,
                "compression_ratio": round(
                    compressed_token_count / original_token_count, 4
                ) if original_token_count else 1.0,
                "references": self._extract_references(compressed_content),
            })

        if compressed_chunks and total_original_tokens:
            target_total_tokens = max(1, int(total_original_tokens / safe_ratio))
            if total_compressed_tokens > target_total_tokens:
                compressed_chunks, total_compressed_tokens = self._rebalance_ingestion_chunks_to_budget(
                    compressed_chunks,
                    target_total_tokens,
                    max_tokens_per_chunk,
                )

        achieved_ratio = round(
            total_original_tokens / max(total_compressed_tokens, 1),
            4,
        ) if total_original_tokens else 1.0

        if achieved_ratio < safe_ratio:
            LOGGER.warning(
                "Ingestion compression ratio %.4f below target %.2f (tokens %s -> %s).",
                achieved_ratio,
                safe_ratio,
                total_original_tokens,
                total_compressed_tokens,
            )

        metrics = {
            "original_tokens": total_original_tokens,
            "compressed_tokens": total_compressed_tokens,
            "tokens_saved": max(total_original_tokens - total_compressed_tokens, 0),
            "compression_percentage": round(
                (1 - (total_compressed_tokens / total_original_tokens)) * 100, 2
            ) if total_original_tokens else 0.0,
            "chunk_count": len(compressed_chunks),
            "average_chunk_tokens": round(
                total_compressed_tokens / len(compressed_chunks), 2
            ) if compressed_chunks else 0.0,
            "max_chunk_tokens": max(
                (chunk['compressed_token_count'] for chunk in compressed_chunks),
                default=0,
            ),
            "target_ratio": safe_ratio,
            "achieved_ratio": achieved_ratio,
            "compression_method": "extractive_sentence_ranking",
            "compression_postprocess": "global_budget_rebalancing",
        }

        summary_card = self.build_document_summary(filename, compressed_chunks, metrics)
        return {
            "chunks": compressed_chunks,
            "metrics": metrics,
            "summary_card": summary_card,
        }

    def _rebalance_ingestion_chunks_to_budget(
        self,
        chunks: List[Dict[str, Any]],
        target_total_tokens: int,
        max_tokens_per_chunk: int,
    ) -> tuple[List[Dict[str, Any]], int]:
        sentence_candidates: List[Dict[str, Any]] = []

        for chunk_index, chunk in enumerate(chunks):
            source_text = normalize_whitespace(chunk.get("full_text") or chunk.get("content", ""))
            if not source_text:
                continue

            sentences = split_sentences(source_text)
            for sentence_index, sentence in enumerate(sentences):
                cleaned_sentence = self._strip_legal_boilerplate(sentence)
                if not cleaned_sentence or not self._is_useful_sentence(cleaned_sentence):
                    continue

                token_count = estimate_tokens(cleaned_sentence)
                if token_count <= 0:
                    continue

                density_score = self._score_information_density_sentence(
                    cleaned_sentence,
                    sentence_index,
                    len(sentences),
                )

                sentence_candidates.append(
                    {
                        "chunk_index": chunk_index,
                        "sentence_index": sentence_index,
                        "sentence": cleaned_sentence,
                        "token_count": token_count,
                        "density_score": density_score,
                    }
                )

        if not sentence_candidates:
            return self._trim_ingestion_chunks_to_budget(
                chunks,
                target_total_tokens,
                max_tokens_per_chunk,
            )

        ranked_candidates = sorted(
            sentence_candidates,
            key=lambda item: (item["density_score"], -item["token_count"]),
            reverse=True,
        )

        selected_candidates: List[Dict[str, Any]] = []
        selected_tokens = 0

        for candidate in ranked_candidates:
            if selected_tokens >= target_total_tokens:
                break

            remaining_tokens = target_total_tokens - selected_tokens
            candidate_tokens = candidate["token_count"]

            if candidate_tokens <= remaining_tokens:
                selected_candidates.append(candidate)
                selected_tokens += candidate_tokens
                continue

            if remaining_tokens >= 8:
                trimmed_sentence = trim_to_token_budget(candidate["sentence"], remaining_tokens)
                trimmed_tokens = estimate_tokens(trimmed_sentence)
                if trimmed_tokens >= 5:
                    trimmed_candidate = dict(candidate)
                    trimmed_candidate["sentence"] = trimmed_sentence
                    trimmed_candidate["token_count"] = trimmed_tokens
                    selected_candidates.append(trimmed_candidate)
                    selected_tokens += trimmed_tokens
                break

        if not selected_candidates and ranked_candidates:
            fallback = dict(ranked_candidates[0])
            fallback_sentence = trim_to_token_budget(
                fallback["sentence"],
                min(target_total_tokens, max_tokens_per_chunk),
            )
            fallback_tokens = estimate_tokens(fallback_sentence)
            if fallback_tokens > 0:
                fallback["sentence"] = fallback_sentence
                fallback["token_count"] = fallback_tokens
                selected_candidates = [fallback]

        selected_by_chunk: Dict[int, List[Dict[str, Any]]] = {}
        for candidate in selected_candidates:
            selected_by_chunk.setdefault(candidate["chunk_index"], []).append(candidate)

        rebased_chunks: List[Dict[str, Any]] = []
        for chunk_index, chunk in enumerate(chunks):
            chunk_candidates = selected_by_chunk.get(chunk_index)
            if not chunk_candidates:
                continue

            ordered_candidates = sorted(chunk_candidates, key=lambda item: item["sentence_index"])
            rebased_content = normalize_whitespace(
                " ".join(item["sentence"] for item in ordered_candidates)
            )
            rebased_content = trim_to_token_budget(rebased_content, max_tokens_per_chunk)
            rebased_tokens = estimate_tokens(rebased_content)
            if rebased_tokens <= 0:
                continue

            original_token_count = int(chunk.get("original_token_count") or 0)
            if original_token_count <= 0:
                original_token_count = estimate_tokens(chunk.get("full_text", ""))

            rebased_chunk = dict(chunk)
            rebased_chunk["content"] = rebased_content
            rebased_chunk["compressed_token_count"] = rebased_tokens
            rebased_chunk["compression_ratio"] = round(
                rebased_tokens / max(original_token_count, 1),
                4,
            ) if original_token_count else 1.0
            rebased_chunk["references"] = self._extract_references(rebased_content)
            rebased_chunks.append(rebased_chunk)

        return self._trim_ingestion_chunks_to_budget(
            rebased_chunks,
            target_total_tokens,
            max_tokens_per_chunk,
        )

    def _trim_ingestion_chunks_to_budget(
        self,
        chunks: List[Dict[str, Any]],
        target_total_tokens: int,
        max_tokens_per_chunk: int,
    ) -> tuple[List[Dict[str, Any]], int]:
        if not chunks:
            return [], 0

        budget_remaining = target_total_tokens
        trimmed_chunks: List[Dict[str, Any]] = []

        for chunk in chunks:
            if budget_remaining <= 0:
                break

            raw_content = normalize_whitespace(chunk.get("content", ""))
            if not raw_content:
                continue

            chunk_budget = min(max_tokens_per_chunk, budget_remaining)
            trimmed_content = trim_to_token_budget(raw_content, chunk_budget)
            trimmed_tokens = estimate_tokens(trimmed_content)
            if trimmed_tokens <= 0:
                continue

            original_token_count = int(chunk.get("original_token_count") or 0)
            if original_token_count <= 0:
                original_token_count = estimate_tokens(chunk.get("full_text", ""))

            trimmed_chunk = dict(chunk)
            trimmed_chunk["content"] = trimmed_content
            trimmed_chunk["compressed_token_count"] = trimmed_tokens
            trimmed_chunk["compression_ratio"] = round(
                trimmed_tokens / max(original_token_count, 1),
                4,
            ) if original_token_count else 1.0
            trimmed_chunk["references"] = self._extract_references(trimmed_content)

            trimmed_chunks.append(trimmed_chunk)
            budget_remaining -= trimmed_tokens

        if not trimmed_chunks:
            emergency_content = trim_to_token_budget(
                normalize_whitespace(chunks[0].get("content", "")),
                min(target_total_tokens, max_tokens_per_chunk),
            )
            emergency_tokens = estimate_tokens(emergency_content)
            if emergency_tokens > 0:
                emergency_chunk = dict(chunks[0])
                emergency_chunk["content"] = emergency_content
                emergency_chunk["compressed_token_count"] = emergency_tokens

                original_token_count = int(emergency_chunk.get("original_token_count") or 0)
                if original_token_count <= 0:
                    original_token_count = estimate_tokens(emergency_chunk.get("full_text", ""))

                emergency_chunk["compression_ratio"] = round(
                    emergency_tokens / max(original_token_count, 1),
                    4,
                ) if original_token_count else 1.0
                emergency_chunk["references"] = self._extract_references(emergency_content)
                trimmed_chunks = [emergency_chunk]

        total_tokens = sum(
            estimate_tokens(chunk.get("content", ""))
            for chunk in trimmed_chunks
        )
        return trimmed_chunks, total_tokens

    def compress_retrieved_chunks_for_prompt(
        self,
        retrieved_chunks: List[Dict[str, Any]],
        target_ratio: float = 10.0,
    ) -> Dict[str, Any]:
        safe_ratio = max(target_ratio, 1.0)
        if not retrieved_chunks:
            return {
                "chunks": [],
                "metrics": {
                    "compression_stage": "retrieval_second_pass",
                    "target_ratio": safe_ratio,
                    "achieved_ratio": 1.0,
                    "original_tokens": 0,
                    "compressed_tokens": 0,
                    "sentences_considered": 0,
                    "sentences_selected": 0,
                },
            }

        sentence_candidates: List[Dict[str, Any]] = []
        total_original_tokens = 0

        for chunk_index, chunk in enumerate(retrieved_chunks):
            original_content = normalize_whitespace(chunk.get("content", ""))
            if not original_content:
                continue

            total_original_tokens += estimate_tokens(original_content)
            sentences = split_sentences(original_content)

            for sentence_index, sentence in enumerate(sentences):
                cleaned_sentence = self._strip_legal_boilerplate(sentence)
                if not cleaned_sentence or not self._is_useful_sentence(cleaned_sentence):
                    continue

                token_count = estimate_tokens(cleaned_sentence)
                if token_count <= 0:
                    continue

                density_score = self._score_information_density_sentence(
                    cleaned_sentence,
                    sentence_index,
                    len(sentences),
                )

                sentence_candidates.append(
                    {
                        "chunk_index": chunk_index,
                        "sentence_index": sentence_index,
                        "sentence": cleaned_sentence,
                        "token_count": token_count,
                        "density_score": density_score,
                    }
                )

        target_token_budget = max(1, int(total_original_tokens / safe_ratio))

        if not sentence_candidates:
            fallback_chunks: List[Dict[str, Any]] = []
            budget_remaining = target_token_budget

            for chunk in retrieved_chunks:
                if budget_remaining <= 0:
                    break

                fallback_content = normalize_whitespace(chunk.get("content", ""))
                if not fallback_content:
                    continue

                trimmed_content = trim_to_token_budget(fallback_content, budget_remaining)
                trimmed_tokens = estimate_tokens(trimmed_content)
                if trimmed_tokens <= 0:
                    continue

                fallback_chunk = dict(chunk)
                fallback_chunk["content"] = trimmed_content
                metadata = dict(fallback_chunk.get("metadata", {}))
                metadata["second_pass_compression"] = "budget_trim_fallback"
                fallback_chunk["metadata"] = metadata

                fallback_chunks.append(fallback_chunk)
                budget_remaining -= trimmed_tokens

            if not fallback_chunks and retrieved_chunks:
                emergency_content = trim_to_token_budget(
                    normalize_whitespace(retrieved_chunks[0].get("content", "")),
                    target_token_budget,
                )
                if emergency_content:
                    emergency_chunk = dict(retrieved_chunks[0])
                    emergency_chunk["content"] = emergency_content
                    metadata = dict(emergency_chunk.get("metadata", {}))
                    metadata["second_pass_compression"] = "budget_trim_emergency"
                    emergency_chunk["metadata"] = metadata
                    fallback_chunks = [emergency_chunk]

            compressed_tokens = sum(
                estimate_tokens(chunk.get("content", ""))
                for chunk in fallback_chunks
            )
            achieved_ratio = round(
                total_original_tokens / max(compressed_tokens, 1),
                4,
            ) if total_original_tokens else 1.0

            if achieved_ratio < safe_ratio:
                LOGGER.warning(
                    "Retrieved chunk compression ratio %.4f below target %.2f (tokens %s -> %s).",
                    achieved_ratio,
                    safe_ratio,
                    total_original_tokens,
                    compressed_tokens,
                )

            return {
                "chunks": fallback_chunks,
                "metrics": {
                    "compression_stage": "retrieval_second_pass",
                    "target_ratio": safe_ratio,
                    "achieved_ratio": achieved_ratio,
                    "original_tokens": total_original_tokens,
                    "compressed_tokens": compressed_tokens,
                    "sentences_considered": 0,
                    "sentences_selected": sum(
                        len(split_sentences(chunk.get("content", "")))
                        for chunk in fallback_chunks
                    ),
                },
            }
        ranked_candidates = sorted(
            sentence_candidates,
            key=lambda item: (item["density_score"], -item["token_count"]),
            reverse=True,
        )

        selected_candidates: List[Dict[str, Any]] = []
        selected_tokens = 0
        selected_keys = set()

        for candidate in ranked_candidates:
            if selected_tokens >= target_token_budget:
                break

            candidate_key = (candidate["chunk_index"], candidate["sentence_index"])
            if candidate_key in selected_keys:
                continue

            remaining_tokens = target_token_budget - selected_tokens
            candidate_tokens = candidate["token_count"]

            if candidate_tokens <= remaining_tokens:
                selected_candidates.append(candidate)
                selected_tokens += candidate_tokens
                selected_keys.add(candidate_key)
                continue

            # Allow one trimmed sentence to fit the remaining budget.
            if remaining_tokens >= 8:
                trimmed_sentence = trim_to_token_budget(candidate["sentence"], remaining_tokens)
                trimmed_tokens = estimate_tokens(trimmed_sentence)
                if trimmed_tokens >= 5:
                    trimmed_candidate = dict(candidate)
                    trimmed_candidate["sentence"] = trimmed_sentence
                    trimmed_candidate["token_count"] = trimmed_tokens
                    selected_candidates.append(trimmed_candidate)
                    selected_tokens += trimmed_tokens
                    selected_keys.add(candidate_key)
                break

        if not selected_candidates:
            fallback = dict(ranked_candidates[0])
            fallback_budget = max(1, target_token_budget)
            fallback_sentence = trim_to_token_budget(fallback["sentence"], fallback_budget)
            fallback_tokens = estimate_tokens(fallback_sentence)
            if fallback_tokens > 0:
                fallback["sentence"] = fallback_sentence
                fallback["token_count"] = fallback_tokens
                selected_candidates = [fallback]

        selected_by_chunk: Dict[int, List[Dict[str, Any]]] = {}
        for candidate in selected_candidates:
            selected_by_chunk.setdefault(candidate["chunk_index"], []).append(candidate)

        def build_compressed_chunks(
            grouped_candidates: Dict[int, List[Dict[str, Any]]],
        ) -> tuple[List[Dict[str, Any]], int, float]:
            built_chunks: List[Dict[str, Any]] = []

            for chunk_index, chunk in enumerate(retrieved_chunks):
                chunk_candidates = grouped_candidates.get(chunk_index)
                if not chunk_candidates:
                    continue

                ordered_candidates = sorted(chunk_candidates, key=lambda item: item["sentence_index"])
                compressed_content = normalize_whitespace(
                    " ".join(item["sentence"] for item in ordered_candidates)
                )
                if not compressed_content:
                    continue

                compressed_chunk = dict(chunk)
                compressed_chunk["content"] = compressed_content

                metadata = dict(compressed_chunk.get("metadata", {}))
                metadata["second_pass_compression"] = "information_density_top_sentences"
                compressed_chunk["metadata"] = metadata

                built_chunks.append(compressed_chunk)

            built_tokens = sum(
                estimate_tokens(chunk.get("content", ""))
                for chunk in built_chunks
            )
            built_ratio = round(
                total_original_tokens / max(built_tokens, 1),
                4,
            ) if total_original_tokens else 1.0
            return built_chunks, built_tokens, built_ratio

        compressed_chunks, compressed_tokens, achieved_ratio = build_compressed_chunks(selected_by_chunk)

        # Iterative second pass: prune lowest-scoring sentences until target ratio is met
        # or each selected chunk is down to one sentence.
        while achieved_ratio < safe_ratio:
            removable_candidates = [
                candidate
                for chunk_candidates in selected_by_chunk.values()
                if len(chunk_candidates) > 1
                for candidate in chunk_candidates
            ]
            if not removable_candidates:
                break

            candidate_to_remove = min(
                removable_candidates,
                key=lambda item: (item["density_score"], -item["token_count"], item["sentence_index"]),
            )

            chunk_candidates = selected_by_chunk.get(candidate_to_remove["chunk_index"], [])
            selected_by_chunk[candidate_to_remove["chunk_index"]] = [
                candidate
                for candidate in chunk_candidates
                if candidate["sentence_index"] != candidate_to_remove["sentence_index"]
            ]

            compressed_chunks, compressed_tokens, achieved_ratio = build_compressed_chunks(selected_by_chunk)

        # Hard token-cap enforcement so prompt input never exceeds budget.
        if compressed_tokens > target_token_budget:
            budget_remaining = target_token_budget
            budgeted_chunks: List[Dict[str, Any]] = []

            for chunk in compressed_chunks:
                if budget_remaining <= 0:
                    break

                trimmed_content = trim_to_token_budget(chunk.get("content", ""), budget_remaining)
                trimmed_tokens = estimate_tokens(trimmed_content)
                if trimmed_tokens <= 0:
                    continue

                budgeted_chunk = dict(chunk)
                budgeted_chunk["content"] = trimmed_content
                metadata = dict(budgeted_chunk.get("metadata", {}))
                metadata["second_pass_compression"] = "information_density_top_sentences_budget_cap"
                budgeted_chunk["metadata"] = metadata

                budgeted_chunks.append(budgeted_chunk)
                budget_remaining -= trimmed_tokens

            if not budgeted_chunks and compressed_chunks:
                emergency_content = trim_to_token_budget(
                    compressed_chunks[0].get("content", ""),
                    target_token_budget,
                )
                if emergency_content:
                    emergency_chunk = dict(compressed_chunks[0])
                    emergency_chunk["content"] = emergency_content
                    metadata = dict(emergency_chunk.get("metadata", {}))
                    metadata["second_pass_compression"] = "information_density_top_sentences_budget_cap_emergency"
                    emergency_chunk["metadata"] = metadata
                    budgeted_chunks = [emergency_chunk]

            compressed_chunks = budgeted_chunks
            compressed_tokens = sum(
                estimate_tokens(chunk.get("content", ""))
                for chunk in compressed_chunks
            )
            achieved_ratio = round(
                total_original_tokens / max(compressed_tokens, 1),
                4,
            ) if total_original_tokens else 1.0

        if not compressed_chunks and retrieved_chunks:
            emergency_content = trim_to_token_budget(
                normalize_whitespace(retrieved_chunks[0].get("content", "")),
                target_token_budget,
            )
            if emergency_content:
                emergency_chunk = dict(retrieved_chunks[0])
                emergency_chunk["content"] = emergency_content
                metadata = dict(emergency_chunk.get("metadata", {}))
                metadata["second_pass_compression"] = "information_density_top_sentences_last_resort"
                emergency_chunk["metadata"] = metadata
                compressed_chunks = [emergency_chunk]
                compressed_tokens = estimate_tokens(emergency_content)
                achieved_ratio = round(
                    total_original_tokens / max(compressed_tokens, 1),
                    4,
                ) if total_original_tokens else 1.0

        if achieved_ratio < safe_ratio:
            LOGGER.warning(
                "Retrieved chunk compression ratio %.4f below target %.2f (tokens %s -> %s).",
                achieved_ratio,
                safe_ratio,
                total_original_tokens,
                compressed_tokens,
            )

        sentences_selected = sum(
            len(split_sentences(chunk.get("content", "")))
            for chunk in compressed_chunks
        )

        return {
            "chunks": compressed_chunks,
            "metrics": {
                "compression_stage": "retrieval_second_pass",
                "target_ratio": safe_ratio,
                "achieved_ratio": achieved_ratio,
                "original_tokens": total_original_tokens,
                "compressed_tokens": compressed_tokens,
                "sentences_considered": len(sentence_candidates),
                "sentences_selected": sentences_selected,
            },
        }

    def build_document_summary(
        self,
        filename: str,
        compressed_chunks: List[Dict[str, Any]],
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        ranked_chunks = sorted(
            compressed_chunks,
            key=self._score_chunk_for_summary,
            reverse=True,
        )

        selected_chunks = ranked_chunks[:4]
        summary_sentences: List[str] = []
        key_points: List[str] = []
        top_sections: List[str] = []

        for chunk in selected_chunks:
            summary_sentence = self._pick_high_value_sentence(chunk['content'])
            if summary_sentence and len(summary_sentences) < 2:
                summary_sentences.append(summary_sentence)

            point_sentence = self._pick_high_value_sentence(chunk['content'])
            if point_sentence and len(key_points) < 4:
                key_points.append(f"{chunk['chapter']}: {point_sentence}")

            if chunk['chapter'] not in top_sections and len(top_sections) < 4:
                top_sections.append(chunk['chapter'])

        summary_text = trim_to_token_budget(" ".join(summary_sentences), 90)
        all_content = " ".join(chunk['content'] for chunk in compressed_chunks)
        affected_stakeholders = self._derive_stakeholders(all_content)
        references = self._extract_references(all_content)[:6]

        return {
            "title": self._derive_title(filename),
            "summary": summary_text or "Upload a legislative document to generate a compressed overview.",
            "key_points": key_points[:4],
            "affected_stakeholders": affected_stakeholders,
            "top_sections": top_sections,
            "top_references": references,
            "compression_badge": (
                f"{float(metrics.get('achieved_ratio', 1.0)):.2f}:1 compression "
                f"({metrics.get('compression_percentage', 0)}% smaller prompt footprint)"
            ),
        }

    def _split_large_chunks(self, chunks: List[Dict[str, str]], max_tokens: int = 900) -> List[Dict[str, str]]:
        normalized_chunks: List[Dict[str, str]] = []

        for chunk in chunks:
            normalized_content = normalize_whitespace(chunk['content'])
            if not normalized_content:
                continue

            if estimate_tokens(normalized_content) <= max_tokens:
                normalized_chunks.append({
                    "chapter": chunk['chapter'],
                    "content": normalized_content,
                })
                continue

            fragments = [
                normalize_whitespace(fragment)
                for fragment in re.split(r'\n{2,}|(?=\b\d+\.\s+)|(?=\bSection\s+\d+)', chunk['content'])
                if normalize_whitespace(fragment)
            ]

            if not fragments:
                fragments = [normalized_content]

            buffer: List[str] = []
            buffer_tokens = 0
            part_index = 1

            for fragment in fragments:
                fragment_tokens = estimate_tokens(fragment)
                if buffer and buffer_tokens + fragment_tokens > max_tokens:
                    normalized_chunks.append({
                        "chapter": self._build_part_label(chunk['chapter'], part_index),
                        "content": normalize_whitespace(" ".join(buffer)),
                    })
                    part_index += 1
                    buffer = [fragment]
                    buffer_tokens = fragment_tokens
                else:
                    buffer.append(fragment)
                    buffer_tokens += fragment_tokens

            if buffer:
                normalized_chunks.append({
                    "chapter": self._build_part_label(chunk['chapter'], part_index),
                    "content": normalize_whitespace(" ".join(buffer)),
                })

        return normalized_chunks

    def _build_part_label(self, chapter: str, part_index: int) -> str:
        if part_index == 1:
            return chapter
        return f"{chapter} - Part {part_index}"

    def _compress_chunk(self, content: str, max_tokens: int) -> str:
        normalized_content = normalize_whitespace(content)
        if estimate_tokens(normalized_content) <= max_tokens:
            return normalized_content

        sentences = split_sentences(content)
        if not sentences:
            return trim_to_token_budget(normalized_content, max_tokens)

        sentence_map = {
            index: normalize_whitespace(sentence)
            for index, sentence in enumerate(sentences)
            if normalize_whitespace(sentence) and self._is_useful_sentence(sentence)
        }

        if not sentence_map:
            sentence_map = {
                index: normalize_whitespace(sentence)
                for index, sentence in enumerate(sentences)
                if normalize_whitespace(sentence)
            }

        candidate_order: List[int] = []
        candidate_scores = sorted(
            (
                (self._score_sentence(sentence, index, len(sentence_map)), index)
                for index, sentence in sentence_map.items()
            ),
            reverse=True,
        )

        for index, sentence in sentence_map.items():
            sentence_lower = sentence.lower()
            if index == 0 or any(phrase in sentence_lower for phrase in self.priority_phrases) or any(char.isdigit() for char in sentence):
                candidate_order.append(index)

        for _, index in candidate_scores:
            if index not in candidate_order:
                candidate_order.append(index)

        selected_indices: List[int] = []
        selected_tokens = 0

        for index in candidate_order:
            sentence = sentence_map[index]
            sentence_tokens = estimate_tokens(sentence)

            if selected_indices and selected_tokens + sentence_tokens > max_tokens:
                continue

            if not selected_indices and sentence_tokens >= max_tokens:
                return trim_to_token_budget(sentence, max_tokens)

            selected_indices.append(index)
            selected_tokens += sentence_tokens

            if selected_tokens >= int(max_tokens * 0.8) and len(selected_indices) >= 2:
                break

        if not selected_indices:
            return trim_to_token_budget(normalized_content, max_tokens)

        compressed_text = " ".join(sentence_map[index] for index in sorted(selected_indices))
        return trim_to_token_budget(compressed_text, max_tokens)

    def _score_sentence(self, sentence: str, index: int, total_sentences: int) -> float:
        sentence_lower = sentence.lower()
        score = 1.0

        if index == 0:
            score += 3.0
        if index == total_sentences - 1:
            score += 0.5

        keyword_hits = sum(1 for keyword in self.legal_keywords if keyword in sentence_lower)
        score += keyword_hits * 1.25

        if any(char.isdigit() for char in sentence):
            score += 1.4

        if any(phrase in sentence_lower for phrase in self.priority_phrases):
            score += 2.2

        word_count = len(sentence.split())
        if word_count < 5:
            score -= 0.75
        elif word_count > 60:
            score -= 0.5

        return score

    def _score_information_density_sentence(
        self,
        sentence: str,
        index: int,
        total_sentences: int,
    ) -> float:
        sentence_lower = sentence.lower()
        token_count = max(estimate_tokens(sentence), 1)

        legal_keyword_hits = sum(1 for keyword in self.legal_keywords if keyword in sentence_lower)
        priority_phrase_hits = sum(sentence_lower.count(phrase) for phrase in self.priority_phrases)
        reference_hits = len(self.reference_re.findall(sentence))
        numeric_hits = len(re.findall(r"\b\d+(?:\.\d+)?\b", sentence))
        obligation_hits = sum(sentence_lower.count(modal) for modal in ("shall", "must", "liable", "penalty"))
        stakeholder_hits = sum(
            sentence_lower.count(term)
            for term in ("authority", "government", "board", "person", "company", "citizen")
        )

        sentence_length = len(sentence.split())
        brevity_bonus = 0.25 if 8 <= sentence_length <= 40 else -0.15
        position_bonus = 0.35 if index == 0 else 0.15 if index == total_sentences - 1 else 0.0

        value_units = (
            (1.45 * legal_keyword_hits)
            + (1.9 * priority_phrase_hits)
            + (2.2 * reference_hits)
            + (1.2 * min(numeric_hits, 4))
            + (1.1 * min(obligation_hits, 3))
            + (0.9 * min(stakeholder_hits, 4))
            + brevity_bonus
            + position_bonus
        )

        return round(value_units / token_count, 6)

    def _strip_legal_boilerplate(self, sentence: str) -> str:
        cleaned_sentence = sentence or ""
        for pattern in self.retrieval_boilerplate_patterns:
            cleaned_sentence = pattern.sub(" ", cleaned_sentence)

        cleaned_sentence = re.sub(r"\s+([,.;:])", r"\1", cleaned_sentence)
        return normalize_whitespace(cleaned_sentence)

    def _pick_high_value_sentence(self, content: str) -> str:
        sentences = split_sentences(content)
        if not sentences:
            return trim_to_token_budget(content, 35)

        ranked_sentences = sorted(
            [
                (self._score_sentence(sentence, index, len(sentences)), sentence)
                for index, sentence in enumerate(sentences)
                if self._is_useful_sentence(sentence)
            ],
            reverse=True,
        )

        if not ranked_sentences:
            return trim_to_token_budget(content, 35)

        return trim_to_token_budget(ranked_sentences[0][1], 35)

    def _is_useful_sentence(self, sentence: str) -> bool:
        normalized_sentence = normalize_whitespace(sentence)
        if re.fullmatch(r'\d+[\.)]?', normalized_sentence):
            return False
        return len(normalized_sentence.split()) >= 4

    def _derive_title(self, filename: str) -> str:
        title = Path(filename).stem.replace("_", " ").replace("-", " ")
        title = normalize_whitespace(title)
        return title.title() if title else "Legislative Document"

    def _derive_stakeholders(self, text: str) -> List[str]:
        text_lower = text.lower()
        scored_stakeholders = []

        for stakeholder, keywords in self.stakeholder_map.items():
            hits = sum(text_lower.count(keyword) for keyword in keywords)
            if hits:
                scored_stakeholders.append((hits, stakeholder))

        if not scored_stakeholders:
            return [
                "Citizens and Consumers",
                "Businesses and Employers",
                "Government and Regulators",
            ]

        return [
            stakeholder
            for _, stakeholder in sorted(scored_stakeholders, reverse=True)[:3]
        ]

    def _extract_references(self, text: str) -> List[str]:
        references: List[str] = []

        for match in self.reference_re.finditer(text or ""):
            reference = normalize_whitespace(match.group(0).rstrip(",.;:"))
            if reference and reference not in references:
                references.append(reference)

        return references

    def _score_chunk_for_summary(self, chunk: Dict[str, Any]) -> float:
        chapter_bonus = 1.5 if chunk['chapter'] != "General/Intro" else 0.0
        reference_bonus = len(chunk.get('references', [])) * 0.4
        return chunk.get('compressed_token_count', 0) + chapter_bonus + reference_bonus
