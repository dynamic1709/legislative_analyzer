import re
from typing import Any, Dict, List

from .token_utils import estimate_tokens


class InformationDensityEvaluator:
    def __init__(self):
        self.stakeholder_keywords = (
            "citizen",
            "citizens",
            "consumer",
            "company",
            "business",
            "government",
            "authority",
            "employer",
            "person",
        )
        self.legal_signal_keywords = (
            "shall",
            "must",
            "liable",
            "penalty",
            "appeal",
            "offence",
            "compliance",
            "within",
            "section",
            "clause",
            "article",
        )

    def evaluate(
        self,
        explanation: str,
        token_metrics: Dict[str, Any],
        detected_references: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        explanation_text = explanation or ""
        prompt_tokens = int(token_metrics.get("total_prompt_tokens_estimate", 0) or 0)
        response_tokens = int(token_metrics.get("response_tokens_estimate", 0) or estimate_tokens(explanation_text))
        total_tokens = max(prompt_tokens + response_tokens, 1)

        summary_present = 1 if re.search(r"simple\s+summary", explanation_text, re.IGNORECASE) else 0
        breakdown_bullets = self._count_bullets(explanation_text)
        stakeholder_mentions = self._count_keyword_hits(explanation_text, self.stakeholder_keywords)
        legal_signal_hits = self._count_keyword_hits(explanation_text, self.legal_signal_keywords)
        reference_count = len(detected_references or [])
        citation_count = len(citations or [])

        weighted_value_units = (
            (2.5 * summary_present)
            + (1.35 * breakdown_bullets)
            + (1.15 * min(stakeholder_mentions, 8))
            + (1.45 * reference_count)
            + (1.6 * citation_count)
            + (0.55 * min(legal_signal_hits, 12))
        )

        value_per_token = round(weighted_value_units / total_tokens, 6)
        density_per_1k_tokens = round(value_per_token * 1000, 2)

        return {
            "value_units": round(weighted_value_units, 3),
            "prompt_plus_response_tokens": total_tokens,
            "value_per_token": value_per_token,
            "density_per_1k_tokens": density_per_1k_tokens,
            "signals": {
                "summary_present": bool(summary_present),
                "breakdown_bullets": breakdown_bullets,
                "stakeholder_mentions": stakeholder_mentions,
                "legal_signal_hits": legal_signal_hits,
                "reference_count": reference_count,
                "citation_count": citation_count,
            },
        }

    def _count_bullets(self, text: str) -> int:
        explicit_bullets = len(re.findall(r"(?m)^\s*[-*•]\s+", text))
        numbered_points = len(re.findall(r"(?m)^\s*\d+[\.)]\s+", text))
        return explicit_bullets + numbered_points

    def _count_keyword_hits(self, text: str, keywords: tuple[str, ...]) -> int:
        normalized = text.lower()
        return sum(normalized.count(keyword) for keyword in keywords)