import re
from typing import Any, Dict, List

from sentence_transformers import CrossEncoder


class HallucinationVerifier:
    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-base",
        entailment_threshold: float = 0.4,
    ):
        self.model_name = model_name
        self.entailment_threshold = entailment_threshold
        self._model: CrossEncoder | None = None
        self._entailment_index: int = 1

    def _lazy_load(self) -> None:
        if self._model is not None:
            return

        self._model = CrossEncoder(self.model_name)
        self._entailment_index = self._resolve_entailment_index()

    def _resolve_entailment_index(self) -> int:
        if self._model is None:
            return 1

        config = getattr(self._model.model, "config", None)
        id2label = getattr(config, "id2label", None)
        if not isinstance(id2label, dict):
            return 1

        for idx, label in id2label.items():
            label_text = str(label).lower()
            if "entail" in label_text:
                try:
                    return int(idx)
                except (TypeError, ValueError):
                    continue

        return 1

    def split_sentences(self, text: str) -> List[str]:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        if not normalized:
            return []

        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)
        sentences = [part.strip() for part in parts if part.strip()]
        return sentences or [normalized]

    def _extract_evidence_texts(self, retrieved_chunks: List[Dict[str, Any]]) -> List[str]:
        evidence_texts: List[str] = []
        for chunk in retrieved_chunks or []:
            metadata = chunk.get("metadata", {}) or {}
            full_text = (metadata.get("full_text") or "").strip()
            compressed_text = (chunk.get("content") or "").strip()
            evidence = full_text or compressed_text
            if evidence:
                evidence_texts.append(evidence)

        return evidence_texts

    def _score_sentence_against_evidence(
        self,
        sentence: str,
        evidence_texts: List[str],
    ) -> tuple[float, int]:
        if self._model is None or not evidence_texts:
            return 0.0, -1

        sentence_pairs = [(sentence, evidence) for evidence in evidence_texts]
        probabilities = self._model.predict(sentence_pairs, apply_softmax=True)

        best_score = 0.0
        best_index = -1
        for idx, row in enumerate(probabilities):
            row_values = row.tolist() if hasattr(row, "tolist") else row
            if isinstance(row_values, (list, tuple)):
                if 0 <= self._entailment_index < len(row_values):
                    entailment_score = float(row_values[self._entailment_index])
                else:
                    entailment_score = float(max(row_values)) if row_values else 0.0
            else:
                entailment_score = float(row_values)

            if entailment_score > best_score:
                best_score = entailment_score
                best_index = idx

        return best_score, best_index

    def verify(
        self,
        generated_answer: str,
        retrieved_chunks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        sentences = self.split_sentences(generated_answer)
        if not sentences:
            return {
                "trust_score": 0.0,
                "flagged_sentences": [],
            }

        evidence_texts = self._extract_evidence_texts(retrieved_chunks)
        if not evidence_texts:
            return {
                "trust_score": 0.0,
                "flagged_sentences": [
                    {
                        "sentence_index": idx,
                        "sentence": sentence,
                        "entailment_score": 0.0,
                        "best_chunk_index": -1,
                    }
                    for idx, sentence in enumerate(sentences)
                ],
            }

        try:
            self._lazy_load()
        except Exception:
            return {
                "trust_score": 0.0,
                "flagged_sentences": [
                    {
                        "sentence_index": idx,
                        "sentence": sentence,
                        "entailment_score": 0.0,
                        "best_chunk_index": -1,
                    }
                    for idx, sentence in enumerate(sentences)
                ],
            }

        flagged_sentences: List[Dict[str, Any]] = []
        sentence_scores: List[float] = []

        for idx, sentence in enumerate(sentences):
            entailment_score, best_chunk_index = self._score_sentence_against_evidence(
                sentence,
                evidence_texts,
            )
            sentence_scores.append(entailment_score)

            if entailment_score < self.entailment_threshold:
                flagged_sentences.append(
                    {
                        "sentence_index": idx,
                        "sentence": sentence,
                        "entailment_score": round(entailment_score, 4),
                        "best_chunk_index": best_chunk_index,
                    }
                )

        trust_score = round(sum(sentence_scores) / len(sentence_scores), 4) if sentence_scores else 0.0

        return {
            "trust_score": trust_score,
            "flagged_sentences": flagged_sentences,
        }
