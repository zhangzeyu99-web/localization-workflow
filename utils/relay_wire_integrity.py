"""Keep the transport's private reference syntax out of delivered text."""

import re


FRAGMENT_TOKEN = re.compile(r"\[f[0-9]+\]")
_WIRE_MARKER = re.compile(r"\[f[0-9]+\]|\$context_ref|\bshared_context(?:s|_fragments)\b")


def has_literal_fragment(value: object) -> bool:
    if isinstance(value, str):
        return FRAGMENT_TOKEN.search(value) is not None
    if isinstance(value, dict):
        return any(has_literal_fragment(key) or has_literal_fragment(item) for key, item in value.items())
    if isinstance(value, list):
        return any(map(has_literal_fragment, value))
    return False


def wire_markers_changed(source: str, target: str) -> bool:
    return _WIRE_MARKER.findall(source) != _WIRE_MARKER.findall(target)
