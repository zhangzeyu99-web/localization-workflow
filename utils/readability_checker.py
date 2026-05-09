"""Readability checks for over-compressed localization output.

This module blocks two common failure modes in game localization:
- opaque internal-code style abbreviations, for example "PERR", "DTT", "IDNE"
- clipped words produced by aggressive UI shortening, for example "rewa", "obta"
"""
from __future__ import annotations

import re

from utils.variable_checker import CheckResult

_RUNTIME_PLACEHOLDER = re.compile(
    r'<[^>]+>|\{[^}]+\}|\[[A-Za-z]+\d+\]|%[dfs]|##\d+',
    re.IGNORECASE,
)
_ALL_CAPS_TOKEN = re.compile(r'^[A-Z]{2,8}$')
_OPAQUE_CODE_WITH_PLACEHOLDER = re.compile(
    r'^(?:##\d+)*[A-Z]{2,8}(?:##\d+|[A-Z0-9])*$'
)

ALLOWED_GAME_ABBREVIATIONS = {
    "AI",
    "AOE",
    "API",
    "ATK",
    "BP",
    "CD",
    "CN",
    "CP",
    "DEF",
    "DMG",
    "DPS",
    "EN",
    "EXP",
    "FPS",
    "GM",
    "HP",
    "ID",
    "NPC",
    "OK",
    "PVE",
    "PVP",
    "RNG",
    "SFX",
    "SR",
    "SSR",
    "SS",
    "UI",
    "URL",
    "VIP",
}

_CLIPPED_WORD_PATTERN = re.compile(
    r'\b(?:'
    r'acct|acti|adde|afte|alre|anon|arri|batt|blac|bloc|char|coll|comm|coun|cur|'
    r'del|dist|effe|foll|frie|imme|init|memb|mgmt|obta|opti|perm|perms|phon|'
    r'poti|prog|purc|rada|rand|rece|reco|refr|rema|repa|req|resi|reso|rewa|rwd|'
    r'sele|sett|supp|tmrw|toke|tran|trea|upgr'
    r')\b',
    re.IGNORECASE,
)


def _visible_text(text: str) -> str:
    visible = _RUNTIME_PLACEHOLDER.sub('', str(text or ''))
    return re.sub(r'\s+', ' ', visible).strip()


def _has_opaque_code(text: str) -> bool:
    raw = str(text or '').strip()
    visible = _visible_text(raw)
    if not visible:
        return False
    if _ALL_CAPS_TOKEN.match(visible):
        return visible.upper() not in ALLOWED_GAME_ABBREVIATIONS
    if _OPAQUE_CODE_WITH_PLACEHOLDER.match(raw):
        stripped = re.sub(r'##\d+', '', raw)
        return bool(stripped) and stripped.upper() not in ALLOWED_GAME_ABBREVIATIONS
    return False


def check_readability(row_id: int, original: str, translation: str, lang: str = 'en') -> list[CheckResult]:
    """Return hard readability issues caused by over-compression.

    The check is conservative: it allows established game abbreviations such as
    HP, ATK, DEF, DMG, PVP, and VIP, but flags opaque internal codes and clipped
    English fragments that are not user-facing text.
    """
    if lang not in {'en', 'idn', 'fr', 'de', 'tr', 'es', 'pt', 'ru'}:
        return []

    results: list[CheckResult] = []
    text = str(translation or '')

    if _has_opaque_code(text):
        results.append(CheckResult(
            row_id=row_id,
            check_type='opaque_abbreviation',
            severity='error',
            message='Opaque or internal-code abbreviation found in translation',
            original=original,
            translation=translation,
            confidence=0.95,
        ))

    clipped = _CLIPPED_WORD_PATTERN.search(_visible_text(text))
    if clipped:
        results.append(CheckResult(
            row_id=row_id,
            check_type='clipped_word',
            severity='error',
            message=f"Clipped word found in translation: {clipped.group(0)}",
            original=original,
            translation=translation,
            confidence=0.9,
        ))

    return results
