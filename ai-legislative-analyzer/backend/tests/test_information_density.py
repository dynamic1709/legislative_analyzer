import unittest

from services.information_density import InformationDensityEvaluator


class InformationDensityTests(unittest.TestCase):
    def test_density_metric_returns_value_per_token(self):
        evaluator = InformationDensityEvaluator()
        explanation = (
            "Simple Summary: Companies face a penalty if they delay disclosures.\n"
            "Detailed Breakdown:\n"
            "- Companies must publish notices within 30 days.\n"
            "- Non-compliance can trigger monetary penalties.\n"
            "Affected Stakeholders: Citizens, businesses, and regulators.\n"
            "References: Section 7, Clause 2."
        )

        token_metrics = {
            "total_prompt_tokens_estimate": 240,
            "response_tokens_estimate": 120,
        }
        detected_references = [
            {"type": "Section", "number": "7", "full_match": "Section 7"},
            {"type": "Clause", "number": "2", "full_match": "Clause 2"},
        ]
        citations = [
            {"chapter": "CHAPTER I", "chunk_index": 0},
            {"chapter": "CHAPTER II", "chunk_index": 1},
        ]

        result = evaluator.evaluate(explanation, token_metrics, detected_references, citations)

        self.assertGreater(result["value_units"], 0)
        self.assertGreater(result["value_per_token"], 0)
        self.assertGreater(result["density_per_1k_tokens"], 0)
        self.assertIn("signals", result)
        self.assertTrue(result["signals"]["summary_present"])


if __name__ == "__main__":
    unittest.main()
