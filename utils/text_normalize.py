"""Shared text normalization for all QA modules.

All modules must use these functions instead of ad-hoc regex,
ensuring consistent handling of backslash escapes, tags, and variables.
"""
import re

_BACKSLASH_ESCAPE = re.compile(r'\\([_!#=\[\]{}()\\*+\-.<>|~])')

VAR_PATTERN = re.compile(r'\{[^}]+\}')
BBCODE_OPEN = re.compile(r'\[color\s*=[^\]]*\]', re.IGNORECASE)
BBCODE_CLOSE = re.compile(r'\[/color\]', re.IGNORECASE)
BBCODE_ANY = re.compile(r'\[/?color[^\]]*\]', re.IGNORECASE)
NEWLINE_TAG = re.compile(r'\\n')
STRIP_TAGS = re.compile(r'\[/?color[^\]]*\]|\{[^}]+\}')


def normalize_escapes(text: str) -> str:
    """Remove backslash escapes (e.g. \\_ -> _, \\! -> !) for consistent comparison."""
    return _BACKSLASH_ESCAPE.sub(r'\1', str(text))


def strip_tags_and_vars(text: str) -> str:
    """Remove BBCode tags and {var} placeholders."""
    t = STRIP_TAGS.sub('', normalize_escapes(str(text)))
    return re.sub(r'\s+', ' ', t).strip()


def extract_vars(text: str) -> list[str]:
    """Extract all {var} placeholders after normalizing escapes."""
    return VAR_PATTERN.findall(normalize_escapes(str(text)))


def extract_bbcode_opens(text: str) -> list[str]:
    """Extract all [color=xxx] open tags after normalizing escapes."""
    return BBCODE_OPEN.findall(normalize_escapes(str(text)))


def extract_bbcode_closes(text: str) -> list[str]:
    """Extract all [/color] close tags after normalizing escapes."""
    return BBCODE_CLOSE.findall(normalize_escapes(str(text)))


def count_newlines(text: str) -> int:
    """Count \\n occurrences after normalizing escapes."""
    return len(NEWLINE_TAG.findall(normalize_escapes(str(text))))
