import re
from typing import List, Dict

class CrossReferenceDetector:
    def __init__(self):
        self.ref_pattern = re.compile(
            r'(Section|Clause|Article)\s+((?:\d+[A-Za-z]?|[IVXLCDM]+)(?:[\.\-\(\)][A-Za-z0-9]+)*)(\s+of\s+([A-Za-z\s]+(Act|Bill|Sanhita)))?', 
            re.IGNORECASE
        )

    def detect_references(self, text: str) -> List[Dict]:
        matches = self.ref_pattern.finditer(text)
        references = []
        seen = set()
        for match in matches:
            full_match = match.group(0)
            if full_match in seen:
                continue
            seen.add(full_match)

            references.append({
                "type": match.group(1),
                "number": match.group(2),
                "source": match.group(4).strip() if match.group(4) else "Current Document",
                "full_match": full_match
            })
        return references

    def enrich_explanation_with_links(self, explanation: str, detected_refs: List[Dict]) -> str:
        """
        In a real app, this would wrap the detected references with <a> tags
        linking to the specific clause in the DB or external legal archive.
        """
        enriched = explanation
        # Deduplicate refs by full_match
        seen = set()
        for ref in detected_refs:
            if ref['full_match'] not in seen:
                # Placeholder replacement - in UI we'd handle this better
                # enriched = enriched.replace(ref['full_match'], f"[{ref['full_match']}](link)")
                seen.add(ref['full_match'])
        return enriched
