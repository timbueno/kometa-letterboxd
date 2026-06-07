"""Collection naming helpers."""

from __future__ import annotations


def prepend_namespace_emoji(name: str, namespace_emoji: str | None) -> str:
    emoji = " ".join((namespace_emoji or "").split())
    clean_name = name.strip()
    if not emoji:
        return clean_name
    if clean_name == emoji or clean_name.startswith(f"{emoji} "):
        return clean_name
    return f"{emoji} {clean_name}"
