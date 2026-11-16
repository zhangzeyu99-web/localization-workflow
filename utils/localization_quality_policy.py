"""Language guidance learned from reviewed copy; project names stay in private glossaries."""

QUALITY_POLICY_VERSION = "native-baseline-v2-name-relations"
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
    "case, numbering, multiplicity, and markup separately from prose capitalization. "
    "Translate the intended meaning, not a sequence of source words. For names and epithets, "
    "identify the head noun and what each modifier describes; do not invent a place, faction, "
    "or other entity by attaching a modifier to the wrong noun. Read the target on its own for "
    "natural game usage. Keep established proper names and justified concise wording; never "
    "ban a grammatical construction such as 'of' or restore omitted decorative words mechanically. "
    "Use supplied project explanations to resolve meaning. Glossary presence proves consistency, "
    "not semantic correctness: report a concrete source/glossary conflict in unresolved_issues "
    "for scoped glossary correction, rather than silently retaining the error or renaming it.\n"
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


def requires_name_semantic_check(row: dict) -> bool:
    """Use explicit types or an exact glossary name, never source length/word shapes."""
    import json
    from utils.name_policy import classify_name_type

    name_types = {
        'name', 'character', 'character name', 'hero', 'hero name',
        'person', 'person name', 'epithet', 'title', 'character title',
        'ui_skill_name', 'ui_location_name', 'ui_building_name',
        '人名', '人物名', '角色', '角色名', '英雄名', '称号', '角色称号', '头衔',
    }
    def is_name(value):
        text = str(value or '').strip().casefold()
        return text in name_types or bool(classify_name_type(text))

    flags = row.get('risk_flags') or []
    if isinstance(flags, str):
        flags = [flags]
    if set(flags) & {'name_semantics', 'literal_translation', 'modifier_attachment'}:
        return True
    context = row.get('context') or {}
    if isinstance(context, str):
        try:
            context = json.loads(context)
        except (ValueError, TypeError):
            context = {}
    if isinstance(context, dict) and any(is_name(context.get(key)) for key in ('type', 'text_type')):
        return True
    if is_name(row.get('text_type')):
        return True
    source = str(row.get('cn') or '').strip()
    return any(
        isinstance(hit, dict) and source == str(hit.get('source') or hit.get('CN') or '').strip()
        and is_name(hit.get('category')) for hit in row.get('term_hits') or []
    )
