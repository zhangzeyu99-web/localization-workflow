"""UI short-text length budget checks."""
from __future__ import annotations

import re
from dataclasses import dataclass

from utils.text_normalize import strip_tags_and_vars

_SENTENCE_PUNCTUATION = re.compile(r"[。！？!?]|\.{2,}")


@dataclass
class UILengthCheckResult:
    row_id: int
    check_type: str
    severity: str
    message: str
    source_length: int
    target_length: int
    budget: int
    confidence: float = 0.9
    auto_fix: str = ""


def visible_text_length(text: str) -> int:
    normalized = strip_tags_and_vars(str(text))
    normalized = re.sub(r"\s+", "", normalized)
    return len(normalized)


def is_short_ui_candidate(original: str, translation: str, is_ui: bool) -> bool:
    if not is_ui:
        return False

    source = strip_tags_and_vars(str(original))
    target = strip_tags_and_vars(str(translation))
    if not source or not target:
        return False
    if "\\n" in str(original) or "\\n" in str(translation) or "\n" in str(original) or "\n" in str(translation):
        return False
    if _SENTENCE_PUNCTUATION.search(source):
        return False
    return 1 <= visible_text_length(source) <= 8


def compute_ui_length_budget(source_length: int, lang: str = "en") -> int:
    if lang == "idn":
        return min(22, max(7, source_length * 2 + 5))
    return min(20, max(6, source_length * 2 + 4))


def check_ui_length(
    row_id: int,
    original: str,
    translation: str,
    is_ui: bool,
    lang: str = "en",
) -> list[UILengthCheckResult]:
    if not is_short_ui_candidate(original, translation, is_ui):
        return []

    source_length = visible_text_length(original)
    target_length = visible_text_length(translation)
    budget = compute_ui_length_budget(source_length, lang=lang)
    if target_length <= budget:
        return []

    return [
        UILengthCheckResult(
            row_id=row_id,
            check_type="ui_length_overflow",
            severity="error",
            message=(
                "UI text is too long for compact display: "
                f"source={source_length}, target={target_length}, budget<={budget}"
            ),
            source_length=source_length,
            target_length=target_length,
            budget=budget,
        )
    ]
