import re
from typing import List


TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\?\!;:])\s+(?=[A-Z0-9\"'])")


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def estimate_tokens(text: str) -> int:
    normalized = normalize_whitespace(text)
    if not normalized:
        return 0
    return len(TOKEN_RE.findall(normalized))


def split_sentences(text: str) -> List[str]:
    cleaned = (text or "").replace("\r", "\n")
    sentences: List[str] = []

    for block in re.split(r"\n{2,}", cleaned):
        normalized_block = normalize_whitespace(block)
        if not normalized_block:
            continue

        fragments = SENTENCE_SPLIT_RE.split(normalized_block)
        for fragment in fragments:
            normalized_fragment = normalize_whitespace(fragment)
            if normalized_fragment:
                sentences.append(normalized_fragment)

    return sentences


def trim_to_token_budget(text: str, max_tokens: int) -> str:
    normalized = normalize_whitespace(text)
    if not normalized or max_tokens <= 0:
        return ""

    current_tokens = estimate_tokens(normalized)
    if current_tokens <= max_tokens:
        return normalized

    words = normalized.split()
    if not words:
        return ""

    approx_word_budget = max(1, int(len(words) * (max_tokens / current_tokens)))
    trimmed = " ".join(words[:approx_word_budget])
    return normalize_whitespace(trimmed)