import json
import os

_here = os.path.dirname(__file__)

_cache: dict[str, dict[str, str]] = {}


def _load(lang: str) -> dict[str, str]:
    path = os.path.join(_here, f"{lang}.json")
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return {}


def t(key: str, lang: str | None = None, **kwargs) -> str:
    import streamlit as st

    if lang is None:
        lang = st.session_state.get("settings", {}).get("language_code", "en") or "en"
    if lang not in _cache:
        _cache[lang] = _load(lang)
    # fallback: requested lang -> en -> key itself
    text = _cache[lang].get(key) or _cache.get("en", {}).get(key) or key
    if kwargs:
        text = text.format(**kwargs)
    return text
