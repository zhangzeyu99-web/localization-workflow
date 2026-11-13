"""Language guidance learned from reviewed copy; project names stay in private glossaries."""

QUALITY_POLICY_VERSION = "native-baseline-v1"
TRANSLATION_ERROR_VALUES = frozenset({
    "#N/A", "#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!", "#SPILL!", "#CALC!",
})

SOURCE_REVIEW_POLICY = (
    "Cross-check the supplied Chinese and reference at the level of gameplay facts: "
    "trigger thresholds, ranking criteria, fallback win conditions, actor/target ownership, "
    "negation, quantities, and duration. A fluent reference can still omit a rule. "
    "Keep an approved concise baseline, but restore gameplay-critical missing facts. "
    "Human-reviewed wording is a language baseline, not permission to copy spreadsheet error "
    "values, misspellings, foreign-language residue, or damaged tokens. Protect token spelling, "
    "case, numbering, multiplicity, and markup separately from prose capitalization.\n"
)

VIETNAMESE_REVIEW_POLICY = (
    "Vietnamese: use the project's approved Vietnamese glossary and reviewed complete sentences. "
    "Prefer natural mobile-game usage and concise condition-action-effect descriptions. "
    "Use only approved, recognizable game abbreviations; do not invent new ones or abbreviate "
    "a proper name as if it were an attribute. Respect diacritics and Vietnamese word order. "
    "Apply approved Title Case to UI/feature/proper names, and natural sentence case to ordinary "
    "verbs and prose; never Title Case program tokens. Distinguish self/our side from allies, "
    "skill activation from owning a skill, rerolling from refining, and vouchers from discount "
    "coupons using the supplied mechanics. Keep narrative voice natural without changing the "
    "speaker, intent, or implied action. Review compound words as words, not by global substring "
    "replacement; for example, discovering is 'phát hiện', not 'gửi hiện'.\n"
)


def localization_quality_policy(languages) -> str:
    if isinstance(languages, str):
        languages = [languages]
    normalized = {str(lang).strip().lower().replace('_', '-').split('-')[0] for lang in languages}
    return SOURCE_REVIEW_POLICY + (VIETNAMESE_REVIEW_POLICY if normalized & {'vi', 'vn', 'vie', 'vietnamese'} else '')
