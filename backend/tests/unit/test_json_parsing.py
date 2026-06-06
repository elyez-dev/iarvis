"""
Tests unitarios de parseo de JSON flexible del backend.

Verifica que los parsers replican fielmente a _parse_json_payload_from_message
y _loads_flexible_json de memory_service.py (pipeline real de produccion):

  1. Regex block extraction: markdown fences + raw JSON block detection
  2. json.loads con comillas curvas Unicode
  3. Trailing comma stripping via regex
  4. ast.literal_eval fallback

Tambien prueba _normalize_triplets, _normalize_patterns y _normalize_entity_types
con los formatos legacy que acepta el backend.
"""

import ast
import json
import re
import pytest

pytestmark = pytest.mark.unit


# =============================================================================
# Replica exacta de _parse_json_payload_from_message + _loads_flexible_json
# de services/memory_service.py (snapshot 2026-06-02)
# =============================================================================

def _loads_flexible_json(raw_text: str):
    """Replica exacta de MemoryService._loads_flexible_json."""
    # Intento 1: json.loads directo
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Intento 2: limpiar comillas curvas + trailing commas
    cleaned = raw_text.strip().replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Intento 3: ast.literal_eval (soporta comillas simples, trailing commas, etc.)
    try:
        return ast.literal_eval(cleaned)
    except (ValueError, SyntaxError) as exc:
        raise ValueError("Invalid JSON object in AI message") from exc


def _parse_json_payload_from_message(message: str, label: str = "test") -> dict:
    """Replica exacta de MemoryService._parse_json_payload_from_message."""
    if not message or not message.strip():
        raise ValueError(f"{label.capitalize()} message is empty")

    raw_text = message.strip()

    # Buscar bloque JSON dentro de markdown fences
    fenced_match = re.search(
        r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw_text, flags=re.IGNORECASE
    )
    if fenced_match:
        json_candidate = fenced_match.group(1)
    else:
        # Buscar primer bloque { ... }
        block_match = re.search(r"(\{[\s\S]*\})", raw_text)
        json_candidate = block_match.group(1) if block_match else raw_text

    parsed = _loads_flexible_json(json_candidate)
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid {label} JSON message format")
    return parsed


# =============================================================================
# Replicas de _normalize_* de memory_service.py
# =============================================================================

from typing import Any, Dict, List


def _normalize_triplets(triplets_input) -> list:
    """Replica de MemoryService._normalize_triplets."""
    from schemas.memory import GraphTriplet

    if not isinstance(triplets_input, list):
        triplets_input = [triplets_input]

    result = []
    for item in triplets_input:
        if isinstance(item, str):
            parts = [part.strip() for part in re.split(r"->|,|\|", item) if part.strip()]
            if len(parts) >= 3:
                result.append(GraphTriplet(subject=parts[0], predicate=parts[1], object=parts[2]))
            continue
        if isinstance(item, dict):
            subject = item.get("subject") or item.get("s")
            predicate = item.get("predicate") or item.get("relation") or item.get("p")
            obj = item.get("object") or item.get("o")
            if subject and predicate and obj:
                result.append(GraphTriplet(subject=str(subject), predicate=str(predicate), object=str(obj)))
        elif isinstance(item, GraphTriplet):
            result.append(item)
    return result


def _normalize_patterns(patterns_input) -> list:
    """Replica de MemoryService._normalize_patterns."""
    if not isinstance(patterns_input, list):
        patterns_input = [patterns_input]

    result = []
    for item in patterns_input:
        if isinstance(item, str):
            parts = [p.strip() for p in re.split(r"\||->", item)]
            if len(parts) == 3:
                s, p, o = parts
                result.append({
                    "subject": s or None,
                    "predicate": p or None,
                    "object": o or None,
                })
            continue
        if isinstance(item, dict):
            s = item.get("subject") or item.get("s")
            p = item.get("predicate") or item.get("relation") or item.get("p")
            o = item.get("object") or item.get("o")
            result.append({
                "subject": (str(s).strip() or None) if s is not None else None,
                "predicate": (str(p).strip() or None) if p is not None else None,
                "object": (str(o).strip() or None) if o is not None else None,
            })
    return result


ALLOWED_TYPES = {"Person", "Animal", "Place", "Object", "Food",
                 "Event", "Activity", "Concept", "Feeling", "Other"}


def _normalize_entity_types(types: dict) -> dict:
    """Replica de MemoryService._normalize_entity_types."""
    if not isinstance(types, dict):
        return {}
    result = {}
    for k, v in types.items():
        name = str(k).strip()
        if not name:
            continue
        t = str(v).strip()
        if t not in ALLOWED_TYPES:
            t = "Other"
        result[name] = t
    return result


# =============================================================================
# Tests: _parse_json_payload_from_message (librarian)
# =============================================================================

LIBRARIAN_MINIMAL = """{"rag_query":"the user's favorite food","graph_patterns":[],"time_context":""}"""


def test_librarian_json_normal():
    """JSON librarian normal y limpio."""
    result = _parse_json_payload_from_message(LIBRARIAN_MINIMAL)
    assert result["rag_query"] == "the user's favorite food"
    assert result["graph_patterns"] == []
    assert result["time_context"] == ""


def test_librarian_json_with_linebreaks():
    """JSON con saltos de linea extra."""
    msg = """{
        "rag_query": "the user's favorite food",
        "graph_patterns": [],
        "time_context": ""
    }"""
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "the user's favorite food"


def test_librarian_json_curly_quotes():
    """Comillas curvas Unicode (\u201c \u201d \u2019) se limpian antes de parsear."""
    msg = '{\u201crag_query\u201d: \u201cthe user\u2019s favorite food\u201d, \u201cgraph_patterns\u201d: [], \u201ctime_context\u201d: \u201c\u201d}'
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "the user's favorite food"


def test_librarian_json_markdown_fence():
    """Bloque ```json ... ``` se extrae y parsea correctamente."""
    msg = """```json
{"rag_query": "test", "graph_patterns": [], "time_context": ""}
```"""
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "test"


def test_librarian_json_extra_fields():
    """Campos extra se ignoran (el parser devuelve todo el dict, Pydantic filtra luego)."""
    msg = '{"rag_query":"test","graph_patterns":[],"time_context":"","extra_field":"ignored"}'
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "test"
    assert "extra_field" in result


def test_librarian_json_trailing_comma():
    """Trailing comma se limpia con regex antes de json.loads (comportamiento real)."""
    msg = '{"rag_query":"test","graph_patterns":[],"time_context":"",}'
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "test"
    assert result["graph_patterns"] == []


def test_librarian_json_single_quotes_fallback():
    """Comillas simples se parsean via ast.literal_eval (fallback del pipeline real)."""
    msg = """{'rag_query': 'test', 'graph_patterns': [], 'time_context': ''}"""
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "test"


def test_librarian_json_markdown_with_lang_tag():
    """```json (con etiqueta) se limpia correctamente."""
    msg = """```json
{"rag_query": "where is Juan?", "graph_patterns": [], "time_context": ""}
```"""
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "where is Juan?"


def test_librarian_json_markdown_no_lang_tag():
    """``` (sin etiqueta de lenguaje) tambien se limpia."""
    msg = """```
{"rag_query": "test", "graph_patterns": [], "time_context": ""}
```"""
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "test"


def test_librarian_json_embedded_in_text():
    """JSON embebido en texto circundante: el regex extrae el bloque {}."""
    msg = 'Sure, here is the JSON:\n\n{"rag_query":"test","graph_patterns":[],"time_context":""}\n\nHope that helps!'
    result = _parse_json_payload_from_message(msg)
    assert result["rag_query"] == "test"


# =============================================================================
# Tests: _parse_json_payload_from_message (archivist)
# =============================================================================

ARCHIVIST_MINIMAL = (
    '{"rag_document":"The user likes cheese.",'
    '"graph_triplets":[{"subject":"User","predicate":"likes","object":"cheese"}],'
    '"entity_types":{"User":"Person","cheese":"Food"},"time_context":""}'
)


def test_archivist_json_normal():
    """JSON archivist normal se parsea correctamente."""
    result = _parse_json_payload_from_message(ARCHIVIST_MINIMAL)
    assert result["rag_document"] == "The user likes cheese."
    assert len(result["graph_triplets"]) == 1
    assert result["graph_triplets"][0]["subject"] == "User"
    assert result["entity_types"]["User"] == "Person"


def test_archivist_json_trailing_comma():
    """Trailing commas en arrays y objetos se limpian (comportamiento real)."""
    msg = (
        '{"rag_document":"test",'
        '"graph_triplets":[{"subject":"User","predicate":"likes","object":"test"},],'
        '"entity_types":{},"time_context":"",}'
    )
    result = _parse_json_payload_from_message(msg)
    assert result["rag_document"] == "test"
    assert len(result["graph_triplets"]) == 1


def test_archivist_json_markdown_fence():
    """Archivist JSON dentro de ```json se extrae."""
    msg = """```json
{"rag_document":"test","graph_triplets":[],"entity_types":{},"time_context":""}
```"""
    result = _parse_json_payload_from_message(msg)
    assert result["rag_document"] == "test"


# =============================================================================
# Tests: _normalize_triplets
# =============================================================================

def test_normalize_triplets_dict_list():
    """Lista de dicts se normaliza a GraphTriplet objects."""
    result = _normalize_triplets([
        {"subject": "User", "predicate": "likes", "object": "cheese"},
        {"subject": "User", "predicate": "likes", "object": "coffee"},
    ])
    assert len(result) == 2
    assert result[0].subject == "User"
    assert result[0].predicate == "likes"


def test_normalize_triplets_legacy_string():
    """String legacy 'S->P->O' se normaliza correctamente."""
    result = _normalize_triplets(["User->likes->cheese"])
    assert len(result) == 1
    assert result[0].subject == "User"
    assert result[0].predicate == "likes"
    assert result[0].object == "cheese"


def test_normalize_triplets_single_dict():
    """Un solo dict (no lista) se envuelve en lista."""
    result = _normalize_triplets({"subject": "User", "predicate": "likes", "object": "cheese"})
    assert len(result) == 1


def test_normalize_triplets_mixed():
    """Lista mixta de dicts y strings."""
    result = _normalize_triplets([
        {"subject": "User", "predicate": "likes", "object": "cheese"},
        "User->likes->coffee",
    ])
    assert len(result) == 2


def test_normalize_triplets_invalid_string():
    """String legacy con mas de 3 partes toma las primeras 3 (lenient)."""
    result = _normalize_triplets(["User->likes->cheese->extra"])
    assert len(result) == 1  # las 3 primeras partes forman un triplet valido
    assert result[0].subject == "User"
    assert result[0].predicate == "likes"
    assert result[0].object == "cheese"


def test_normalize_triplets_legacy_pipe_string():
    """String legacy separado por | tambien se acepta (real parser soporta ->|,|)."""
    result = _normalize_triplets(["User|likes|cheese"])
    assert len(result) == 1
    assert result[0].subject == "User"
    assert result[0].predicate == "likes"


def test_normalize_triplets_alternate_keys():
    """Dicts con keys alternativas (s, p, o) se aceptan (comportamiento real)."""
    result = _normalize_triplets([{"s": "User", "p": "likes", "o": "cheese"}])
    assert len(result) == 1
    assert result[0].subject == "User"


# =============================================================================
# Tests: _normalize_patterns
# =============================================================================

def test_normalize_patterns_dict():
    """Lista de dicts se normaliza."""
    result = _normalize_patterns([
        {"subject": "User", "predicate": "likes", "object": None},
    ])
    assert len(result) == 1
    assert result[0]["subject"] == "User"
    assert result[0]["predicate"] == "likes"
    assert result[0]["object"] is None


def test_normalize_patterns_legacy_string():
    """String legacy 'S|P|O' se normaliza. Vacio se convierte en None."""
    result = _normalize_patterns(["User|likes|"])
    assert len(result) == 1
    assert result[0]["subject"] == "User"
    assert result[0]["object"] is None


# =============================================================================
# Tests: _normalize_entity_types
# =============================================================================

def test_normalize_entity_types_all_valid():
    """Todos los tipos validos pasan sin cambios."""
    types = {"User": "Person", "Madrid": "Place", "cheese": "Food"}
    result = _normalize_entity_types(types)
    assert result == types


def test_normalize_entity_types_invalid_to_other():
    """Tipo invalido se reemplaza por 'Other'."""
    result = _normalize_entity_types({"User": "Alien"})
    assert result["User"] == "Other"


def test_normalize_entity_types_mixed():
    """Mezcla de validos e invalidos: solo los invalidos se cambian."""
    result = _normalize_entity_types({"User": "Person", "x": "Unknown"})
    assert result["User"] == "Person"
    assert result["x"] == "Other"


def test_normalize_entity_types_empty():
    """Dict vacio devuelve dict vacio."""
    assert _normalize_entity_types({}) == {}


def test_normalize_entity_types_not_a_dict():
    """Input no-dict devuelve dict vacio (defensivo)."""
    assert _normalize_entity_types(["not", "a", "dict"]) == {}
    assert _normalize_entity_types(None) == {}
