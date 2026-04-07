"""Term hit detection and grammar validation.

Layer 1: Check if standard terms are used in translations.
Layer 2: Check grammar correctness (capitalization, plurals, articles).
"""
import re
from dataclasses import dataclass

from utils.text_normalize import strip_tags_and_vars, normalize_escapes

TERM_ALIASES = {
    'atk': ['attack', 'attacks', 'attacked', 'attacking'],
    'dmg': ['damage', 'damages'],
    'def': ['defense', 'defence'],
    'hp': ['health', 'hit points'],
    'role': ['character', 'characters'],
    'heroes': ['hero'],
    'hero': ['heroes'],
    'events': ['event', 'activity', 'activities'],
    'event': ['events', 'activity', 'activities'],
    'upgrade': ['level up', 'level-up', 'leveled up', 'leveling up', 'levelled up', 'levelling up'],
    'upgrading': ['leveling up', 'levelling up', 'leveled up', 'levelled up', 'level-up'],
    'use': ['using', 'used', 'uses'],
    'usage': ['use', 'using'],
    'train': ['training', 'trained'],
    'share': ['shared', 'sharing'],
    'sharing': ['share', 'shared'],
    'battle': ['combat', 'fight', 'fighting'],
    'build': ['building', 'built', 'construct', 'constructed', 'constructing'],
    'construction': ['building', 'built', 'construct', 'constructed', 'constructing'],
    'add': ['increase', 'increased', 'increasing', 'improve', 'improved', 'improving', 'boost', 'boosted', 'boosting', 'raise', 'raised', 'raising', 'added'],
    'increasement': ['increase', 'increased', 'increasing', 'improve', 'improved', 'improving', 'boost', 'boosted', 'boosting', 'raise', 'raised', 'raising', 'added'],
    'buy': ['purchase', 'purchased', 'buying', 'purchasing'],
    'purchase': ['buy', 'purchased', 'buying', 'purchasing'],
    'claim': ['claimed', 'collect', 'collected', 'receive', 'received', 'redeem', 'redeemed'],
    'march': ['deploy', 'deployed', 'deploying', 'marching', 'expedition', 'expeditions', 'proceed'],
    'faq': ['help', 'helps', 'helping', 'assist', 'assists', 'assistance'],
    'speedup': ['accelerate', 'accelerated', 'accelerating', 'boost', 'boosts', 'boosted', 'boosting'],
    'recover': ['recovered', 'recovery', 'restore', 'restored', 'restoring', 'regenerate', 'regenerated', 'regenerating'],
    'get': ['acquire', 'acquired', 'acquiring', 'obtain', 'obtained', 'obtaining', 'earn', 'earned', 'retrieve', 'retrieved'],
    'acquisition': ['acquire', 'acquired', 'obtained', 'obtain', 'earn', 'earned', 'retrieve', 'retrieved'],
    'klaim': ['diklaim', 'mengklaim', 'ambil', 'diambil'],
    'beli': ['membeli', 'dibeli', 'pembelian'],
    'pembelian': ['beli', 'membeli', 'dibeli'],
    'pengaturan': ['atur', 'diatur', 'mengatur', 'tetapkan', 'ditetapkan'],
    'pasukan': ['berbaris', 'tim', 'antre', 'formasi'],
    'event': ['acara'],
    'pahlawan': ['hero'],
    'faq': ['help', 'bantuan', 'membantu', 'dibantu', 'tolong'],
    'tingkatkan': ['ditingkatkan', 'peningkatan', 'naik level'],
    'meningkatkan': ['ditingkatkan', 'peningkatan', 'naik level'],
    'dmg': ['damage', 'damages', 'kerusakan'],
    'atk': ['attack', 'attacks', 'attacked', 'attacking', 'serangan', 'menyerang'],
}


@dataclass
class TermCheckResult:
    """Result from a term check."""
    row_id: int
    check_type: str
    severity: str  # 'error', 'warning', 'info'
    message: str
    source_term: str = ''
    expected_target: str = ''
    actual_fragment: str = ''
    auto_fix: str = ''
    confidence: float = 1.0


def _normalize_for_search(text: str) -> str:
    """Normalize text for case-insensitive term searching."""
    return strip_tags_and_vars(text)


def _compile_term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term)
    escaped = escaped.replace(r'\ ', r'[\s\-]+')
    if re.fullmatch(r"[A-Za-z0-9'\-\s]+", term):
        return re.compile(rf'\b{escaped}\b', re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def _find_term_in_text(term: str, text: str) -> tuple[bool, str]:
    """Search for a term in text, case-insensitive.

    Returns (found, actual_match).
    """
    clean_text = _normalize_for_search(text)
    pattern = _compile_term_pattern(term)
    match = pattern.search(clean_text)
    if match:
        return True, match.group()
    return False, ''


def _pluralize_word(word: str) -> str:
    if word.endswith('y') and len(word) > 1 and word[-2].lower() not in 'aeiou':
        return word[:-1] + 'ies'
    if word.endswith(('s', 'x', 'z', 'ch', 'sh')):
        return word + 'es'
    return word + 's'


def _singularize_word(word: str) -> str:
    lowered = word.lower()
    if lowered.endswith('ies') and len(word) > 3:
        return word[:-3] + 'y'
    if lowered.endswith('es') and lowered[:-2].endswith(('s', 'x', 'z', 'ch', 'sh')):
        return word[:-2]
    if lowered.endswith('s') and not lowered.endswith('ss'):
        return word[:-1]
    return word


def _inflect_term(term: str) -> set[str]:
    if not term or ' ' not in term and not term.isalpha():
        return {term}

    tokens = term.split()
    if not tokens:
        return {term}

    variants = {term}
    last = tokens[-1]
    singular = _singularize_word(last)
    plural = _pluralize_word(last)

    if singular != last:
        variants.add(' '.join(tokens[:-1] + [singular]))
    if plural != last:
        variants.add(' '.join(tokens[:-1] + [plural]))

    if len(tokens) == 1:
        variants.add(singular)
        variants.add(plural)

    return {variant for variant in variants if variant}


def _expand_search_terms(accepted_terms: list[str]) -> list[str]:
    expanded: list[str] = []
    seen = set()

    def _add(term: str):
        normalized = term.strip()
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        expanded.append(normalized)

    for term in accepted_terms:
        for variant in _inflect_term(term):
            _add(variant)

        alias_terms = TERM_ALIASES.get(term.lower(), [])
        for alias in alias_terms:
            for variant in _inflect_term(alias):
                _add(variant)

    return expanded


def _normalize_term_entry(term_value) -> tuple[str, list[str], bool]:
    """Normalize term entry to (primary, accepted_terms, enforce_case)."""
    if isinstance(term_value, str):
        t = term_value.strip()
        return t, [t] if t else [], False

    if isinstance(term_value, list):
        terms = [str(x).strip() for x in term_value if str(x).strip()]
        if not terms:
            return '', [], False
        return terms[0], terms, False

    if isinstance(term_value, dict):
        primary = str(term_value.get('primary', '')).strip()
        variants = term_value.get('variants', [])
        if isinstance(variants, str):
            variants = [variants]
        variants = [str(x).strip() for x in variants if str(x).strip()]
        enforce_case = bool(term_value.get('enforce_case', False))

        accepted = []
        seen = set()
        for t in [primary] + variants:
            if not t:
                continue
            k = t.lower()
            if k in seen:
                continue
            seen.add(k)
            accepted.append(t)

        if not primary and accepted:
            primary = accepted[0]
        return primary, accepted, enforce_case

    return '', [], False


def _check_capitalization(
    term: str,
    translation: str,
    row_id: int,
    source_term: str,
) -> list[TermCheckResult]:
    """Check if term capitalization is correct in context."""
    results = []
    clean_trans = _normalize_for_search(translation)

    pattern = re.compile(re.escape(term), re.IGNORECASE)
    for match in pattern.finditer(clean_trans):
        actual = match.group()
        start = match.start()

        if actual == term:
            continue

        # Sentence start: first letter should be capitalized
        is_sentence_start = start == 0 or clean_trans[start - 2:start] in ('. ', '! ', '? ')

        if is_sentence_start:
            expected = term[0].upper() + term[1:]
            if actual != expected:
                results.append(TermCheckResult(
                    row_id=row_id,
                    check_type='term_capitalization',
                    severity='warning',
                    message=f"Term '{actual}' at sentence start should be '{expected}'",
                    source_term=source_term,
                    expected_target=expected,
                    actual_fragment=actual,
                    auto_fix=translation.replace(actual, expected, 1),
                    confidence=0.9,
                ))
        else:
            # Mid-sentence: proper nouns stay capitalized, common nouns lowercase
            # Heuristic: if the standard term has capitals, it's a proper noun → keep as-is
            if term[0].isupper():
                # Proper noun — should match exactly
                if actual != term:
                    results.append(TermCheckResult(
                        row_id=row_id,
                        check_type='term_capitalization',
                        severity='warning',
                        message=f"Proper noun '{actual}' should be '{term}'",
                        source_term=source_term,
                        expected_target=term,
                        actual_fragment=actual,
                        auto_fix=translation.replace(actual, term, 1),
                        confidence=0.85,
                    ))
            else:
                # Common noun mid-sentence: should be lowercase
                if actual[0].isupper() and not is_sentence_start:
                    expected_lower = actual[0].lower() + actual[1:]
                    results.append(TermCheckResult(
                        row_id=row_id,
                        check_type='term_capitalization',
                        severity='warning',
                        message=f"Common term '{actual}' mid-sentence should be '{expected_lower}'",
                        source_term=source_term,
                        expected_target=expected_lower,
                        actual_fragment=actual,
                        auto_fix=translation.replace(actual, expected_lower, 1),
                        confidence=0.75,
                    ))

    return results


def check_term_hit(
    row_id: int,
    original: str,
    translation: str,
    term_lookup: dict,
) -> list[TermCheckResult]:
    """Check if standard terms appear in the translation.

    Args:
        row_id: Row identifier
        original: Chinese source text
        translation: English translation
        term_lookup: Dict of {chinese_term: english_term}
    """
    results = []

    for cn_term, term_entry in term_lookup.items():
        if cn_term not in original:
            continue

        primary_term, accepted_terms, enforce_case = _normalize_term_entry(term_entry)
        if not accepted_terms:
            continue
        search_terms = _expand_search_terms(accepted_terms)

        # Layer 1: term hit detection
        found = False
        matched_expected = ''
        for expected in search_terms:
            hit, _ = _find_term_in_text(expected, translation)
            if hit:
                found = True
                matched_expected = expected
                break

        if not found:
            # Check for partial matches or common variants
            en_words = primary_term.split()
            if len(en_words) > 1:
                # Multi-word term: check if any words appear
                hits = sum(1 for w in en_words if w.lower() in translation.lower())
                if hits > 0 and hits < len(en_words):
                    results.append(TermCheckResult(
                        row_id=row_id,
                        check_type='term_partial_hit',
                        severity='warning',
                        message=f"Partial term match: expected one of {accepted_terms} for '{cn_term}', "
                                f"found {hits}/{len(en_words)} words",
                        source_term=cn_term,
                        expected_target=primary_term,
                        confidence=0.6,
                    ))
                else:
                    results.append(TermCheckResult(
                        row_id=row_id,
                        check_type='term_missing',
                        severity='error',
                        message=f"Term not found: expected one of {accepted_terms} for '{cn_term}'",
                        source_term=cn_term,
                        expected_target=primary_term,
                        confidence=0.8,
                    ))
            else:
                results.append(TermCheckResult(
                    row_id=row_id,
                    check_type='term_missing',
                    severity='error',
                    message=f"Term not found: expected one of {accepted_terms} for '{cn_term}'",
                    source_term=cn_term,
                    expected_target=primary_term,
                    confidence=0.8,
                ))
        else:
            # Optional Layer 2: capitalization checks (default disabled)
            if enforce_case and matched_expected:
                cap_results = _check_capitalization(matched_expected, translation, row_id, cn_term)
                results.extend(cap_results)

    return results


def check_chinese_residue(
    row_id: int,
    translation: str,
) -> list[TermCheckResult]:
    """Check for residual Chinese characters in translation."""
    results = []
    translation = str(translation)
    cn_chars = re.findall(r'[\u4e00-\u9fa5]+', translation)
    if cn_chars:
        results.append(TermCheckResult(
            row_id=row_id,
            check_type='chinese_residue',
            severity='error',
            message=f"Chinese characters found in translation: {'、'.join(cn_chars)}",
            actual_fragment='、'.join(cn_chars),
            confidence=1.0,
        ))
    return results
