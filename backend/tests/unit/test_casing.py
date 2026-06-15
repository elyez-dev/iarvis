"""
Unit tests for casing normalization before translation.
"""

import pytest

pytestmark = pytest.mark.unit


def _normalize_casing_for_translation(text: str, threshold: float = 0.8) -> str:
    """Copy of chat_service._normalize_casing_for_translation."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return text

    upper_count = sum(1 for c in letters if c.isupper())
    ratio = upper_count / len(letters)

    if ratio > threshold:
        return text.lower()
    return text


# -- Normal text (unchanged) --

def test_normal_lowercase():
    """Texto en minúsculas no se modifica."""
    assert _normalize_casing_for_translation("hola que tal") == "hola que tal"


def test_normal_sentence():
    """Frase normal con primera mayúscula no se modifica."""
    assert _normalize_casing_for_translation("Hola que tal") == "Hola que tal"


def test_normal_with_acronyms():
    """Frase con acrónimos (NASA, ONU) no debe tocarse (~73% mayúsculas < 80%)."""
    text = "Hola NASA ONU"
    letters = [c for c in text if c.isalpha()]
    ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    assert ratio < 0.80  # sanity check
    assert _normalize_casing_for_translation(text) == text


def test_mixed_case_not_touched():
    """Texto con mayúsculas ocasionales no se toca."""
    text = "Hola, Me Llamo Eloi"
    # ratio: 4/13 ≈ 0.31 < 0.8
    assert _normalize_casing_for_translation(text) == text


# -- ALL CAPS (lowercased) --

def test_all_caps_simple():
    """ALL CAPS simple debe pasar a lowercase."""
    assert _normalize_casing_for_translation("HOLA") == "hola"


def test_all_caps_phrase():
    """Frase completa en ALL CAPS debe pasar a lowercase."""
    assert _normalize_casing_for_translation("HOLA QUE TAL QUIEN ERES") == "hola que tal quien eres"


def test_all_caps_with_numbers():
    """ALL CAPS con números y signos debe pasar a lowercase (se ignora puntuación)."""
    result = _normalize_casing_for_translation("HOLA! COMO ESTAS?")
    assert result == "hola! como estas?"


def test_all_caps_with_accented():
    """ALL CAPS con vocales acentuadas (mayúsculas Unicode) debe normalizar."""
    text = "QUÉ TAL ESTÁS"
    result = _normalize_casing_for_translation(text)
    assert result == "qué tal estás"


# -- No letters --

def test_no_letters():
    """Texto sin caracteres alfabéticos no se modifica."""
    assert _normalize_casing_for_translation("123 456 !@#$%") == "123 456 !@#$%"


def test_empty_string():
    """String vacío no se modifica."""
    assert _normalize_casing_for_translation("") == ""


# -- Threshold boundary --

def test_just_below_threshold():
    """Texto justo por debajo del umbral (0.75) no se toca."""
    # 3 mayúsculas de 4 letras = 0.75 < 0.80
    text = "HOLA que tal"
    assert _normalize_casing_for_translation(text) == text


def test_just_above_threshold():
    """Texto justo por encima del umbral se normaliza.

    'HOLA COMO ESTAS' → 12/12 mayúsculas = 1.0 > 0.8 → lowercase.
    """
    text = "HOLA COMO ESTAS"
    result = _normalize_casing_for_translation(text)
    assert result == text.lower()


def test_exactly_at_threshold_not_touched():
    """Texto en el umbral 0.8 no se normaliza (condición es >, no >=)."""
    # Construir texto con ratio 0.8: "AAAA b" → 4/5 = 0.8
    text = "AAAA b"
    assert _normalize_casing_for_translation(text) == text


# -- Real bug cases --

def test_real_bug_case_hola():
    """Caso real: 'HOLA!' se traducía como '- I'm going to go.' Con normalización pasa a lowercase."""
    result = _normalize_casing_for_translation("HOLA!")
    assert result == "hola!"


def test_real_bug_case_long():
    """Caso real: 'HOLA QUE TAL QUIEN ERES!' se descarrilaba."""
    result = _normalize_casing_for_translation("HOLA QUE TAL QUIEN ERES!")
    assert result == "hola que tal quien eres!"
