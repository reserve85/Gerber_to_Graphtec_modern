"""Minimal translation layer: English source strings, German catalogue."""

from __future__ import annotations

_language = "en"
_catalog: dict[str, str] = {}


def set_language(lang: str) -> None:
    global _language, _catalog
    _language = lang
    if lang == "de":
        from .lang_de import DE

        _catalog = DE
    else:
        _catalog = {}


def language() -> str:
    return _language


def tr(text: str) -> str:
    return _catalog.get(text, text)
