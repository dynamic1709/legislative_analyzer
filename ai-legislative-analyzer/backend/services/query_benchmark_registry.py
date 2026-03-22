import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class QueryBenchmarkRegistry:
    def __init__(self, storage_path: Optional[str] = None, max_records: int = 1000):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        self.storage_path = storage_path or os.path.join(data_dir, "query_metrics.json")
        self.max_records = max_records
        self._records = self._load_records()

    def _load_records(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.storage_path):
            return []

        try:
            with open(self.storage_path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except (OSError, json.JSONDecodeError):
            return []

        return payload if isinstance(payload, list) else []

    def _save_records(self) -> None:
        with open(self.storage_path, "w", encoding="utf-8") as file_handle:
            json.dump(self._records, file_handle, indent=2, ensure_ascii=True)

    def _refresh(self) -> None:
        self._records = self._load_records()

    def append_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._refresh()
        complete_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **record,
        }
        self._records.append(deepcopy(complete_record))
        self._records = self._records[-self.max_records:]
        self._save_records()
        return deepcopy(complete_record)

    def list_recent(self, limit: int = 20, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
        self._refresh()
        records = self._filter_by_document(self._records, document_id)
        return deepcopy(records[-limit:][::-1])

    def build_benchmark(self, document_id: Optional[str] = None, window: int = 100) -> Dict[str, Any]:
        self._refresh()
        filtered_records = self._filter_by_document(self._records, document_id)
        scoped_records = filtered_records[-window:]

        if not scoped_records:
            return {
                "query_count": 0,
                "window": window,
                "avg_density_per_1k_tokens": 0.0,
                "best_density_per_1k_tokens": 0.0,
                "avg_value_per_token": 0.0,
                "avg_total_tokens": 0.0,
                "avg_confidence": 0.0,
                "efficiency_grade": "N/A",
            }

        avg_density = round(
            sum((record.get("information_density", {}) or {}).get("density_per_1k_tokens", 0.0) for record in scoped_records)
            / len(scoped_records),
            3,
        )
        best_density = round(
            max((record.get("information_density", {}) or {}).get("density_per_1k_tokens", 0.0) for record in scoped_records),
            3,
        )
        avg_value_per_token = round(
            sum((record.get("information_density", {}) or {}).get("value_per_token", 0.0) for record in scoped_records)
            / len(scoped_records),
            6,
        )
        avg_total_tokens = round(
            sum((record.get("information_density", {}) or {}).get("prompt_plus_response_tokens", 0.0) for record in scoped_records)
            / len(scoped_records),
            2,
        )
        avg_confidence = round(
            sum(record.get("confidence", 0.0) for record in scoped_records)
            / len(scoped_records),
            4,
        )

        return {
            "query_count": len(scoped_records),
            "window": window,
            "avg_density_per_1k_tokens": avg_density,
            "best_density_per_1k_tokens": best_density,
            "avg_value_per_token": avg_value_per_token,
            "avg_total_tokens": avg_total_tokens,
            "avg_confidence": avg_confidence,
            "efficiency_grade": self._grade_density(avg_density),
        }

    def _filter_by_document(
        self,
        records: List[Dict[str, Any]],
        document_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not document_id:
            return records
        return [record for record in records if record.get("document_id") == document_id]

    def _grade_density(self, avg_density: float) -> str:
        if avg_density >= 25:
            return "A+"
        if avg_density >= 18:
            return "A"
        if avg_density >= 12:
            return "B"
        if avg_density >= 8:
            return "C"
        return "D"