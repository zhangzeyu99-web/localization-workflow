"""Readability checks for over-compressed localization output.

This module blocks two common failure modes in game localization:
- opaque internal-code style abbreviations, for example "PERR", "DTT", "IDNE"
- clipped words produced by aggressive UI shortening, for example "rewa", "obta"
- title-case overuse in error/status messages, for example "Too Many Roles"
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
    r'poti|prog|purc|rada|rand|rece|reco|refr|rema|repa|req|resi|reso|rewa|rwd|logi|'
    r'sele|sett|supp|tmrw|toke|tran|trea|upgr'
    r')\b',
    re.IGNORECASE,
)
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z']*")
_STATUS_OR_ERROR_SOURCE = re.compile(
    r'失败|错误|异常|超时|过多|不足|无法|不能|不可|尚未|暂无|'
    r'未达到|未找到|未开启|未购买|未完成|未解锁|未拥有|未加入|未激活|'
    r'已结束|已过期|已被|已经|已达|已领取|已发送|已加入|已拒绝|已完成|已满|已售罄|'
    r'校验|验证|重连|成功|参数|警告|提示|网络|条件|上限|封禁|被封'
)
_PRESERVE_CASE_WORDS = {
    "Android",
    "App",
    "Discord",
    "Facebook",
    "Google",
    "ID",
    "iOS",
    "PvE",
    "PvP",
    "Twitter",
    "UI",
    "VIP",
    "YouTube",
}


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


def _is_title_word(word: str) -> bool:
    if word.upper() in ALLOWED_GAME_ABBREVIATIONS:
        return False
    if word in _PRESERVE_CASE_WORDS:
        return False
    return len(word) > 1 and word[0].isupper() and word[1:].islower()


def _is_title_case_overuse(original: str, translation: str) -> bool:
    if not _STATUS_OR_ERROR_SOURCE.search(str(original or '')):
        return False

    text = _visible_text(translation)
    words = _WORD_PATTERN.findall(text)
    if len(words) < 2:
        return False

    title_words = [w for w in words if _is_title_word(w)]
    lower_words = [
        w for w in words
        if w.islower() and w.lower() not in {'a', 'an', 'and', 'as', 'at', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to'}
    ]
    return len(title_words) >= 2 and not lower_words


def _sentence_case(text: str) -> str:
    words = _WORD_PATTERN.findall(text)
    if not words:
        return text

    first_word_seen = False

    def replace(match: re.Match) -> str:
        nonlocal first_word_seen
        word = match.group(0)
        if word.upper() in ALLOWED_GAME_ABBREVIATIONS or word in _PRESERVE_CASE_WORDS:
            return word
        lowered = word.lower()
        if not first_word_seen:
            first_word_seen = True
            return lowered[:1].upper() + lowered[1:]
        return lowered

    return _WORD_PATTERN.sub(replace, text)


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

    if lang == 'en' and _is_title_case_overuse(original, text):
        results.append(CheckResult(
            row_id=row_id,
            check_type='title_case_overuse',
            severity='warning',
            message='Title Case overused in status/error style translation',
            original=original,
            translation=translation,
            auto_fix=_sentence_case(text),
            confidence=0.8,
        ))

    return results
