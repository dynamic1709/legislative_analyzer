import os
import tempfile
import unittest

from services.query_benchmark_registry import QueryBenchmarkRegistry


class QueryBenchmarkRegistryTests(unittest.TestCase):
    def test_registry_aggregates_density_benchmarks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "query_metrics.json")
            registry = QueryBenchmarkRegistry(storage_path=file_path, max_records=20)

            for index in range(3):
                registry.append_record(
                    {
                        "document_id": "doc-1",
                        "query": f"Question {index}",
                        "confidence": 0.8,
                        "information_density": {
                            "density_per_1k_tokens": 12.0 + index,
                            "value_per_token": 0.012 + (index * 0.001),
                            "prompt_plus_response_tokens": 300 + (index * 10),
                        },
                    }
                )

            summary = registry.build_benchmark(document_id="doc-1", window=10)
            recent = registry.list_recent(limit=2, document_id="doc-1")

            self.assertEqual(summary["query_count"], 3)
            self.assertGreater(summary["avg_density_per_1k_tokens"], 0)
            self.assertIn("efficiency_grade", summary)
            self.assertEqual(len(recent), 2)


if __name__ == "__main__":
    unittest.main()
