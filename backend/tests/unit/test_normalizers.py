"""
Tests unitarios de funciones normalizadoras del backend.

Cubre las funciones auxiliares de memory_service.py que transforman
datos entre formatos legacy y actuales:
  - _normalize_triplets: acepta dicts, strings "S->P->O", y mezclas
  - _normalize_patterns: acepta dicts y strings "S|P|O"
  - _normalize_entity_types: valida contra tipos permitidos

Cada función se testea aislada (sin depender de schemas reales del backend)
usando réplicas inline de la lógica.
"""

from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
import pytest

pytestmark = pytest.mark.unit


# -- Data classes para los tests (equivalentes a los Pydantic schemas) --------

@dataclass
class GraphTriplet:
    subject: str
    predicate: str
    object: str


@dataclass
class GraphPattern:
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object: Optional[str] = None


# -- _normalize_triplets ------------------------------------------------------

ALLOWED_ENTITY_TYPES = {
    "Person", "Animal", "Place", "Object", "Food",
    "Event", "Activity", "Concept", "Feeling", "Other",
}


def _normalize_triplets(triplets_input: Any) -> List[GraphTriplet]:
    """Copia de memory_service._normalize_triplets."""
    if not isinstance(triplets_input, list):
        triplets_input = [triplets_input]

    result = []
    for item in triplets_input:
        if isinstance(item, str):
            parts = [p.strip() for p in item.split("->")]
            if len(parts) == 3:
                result.append(GraphTriplet(subject=parts[0], predicate=parts[1], object=parts[2]))
        elif isinstance(item, dict):
            result.append(GraphTriplet(subject=item["subject"], predicate=item["predicate"], object=item["object"]))
        elif isinstance(item, GraphTriplet):
            result.append(item)
    return result


def _normalize_patterns(patterns_input: Any) -> List[GraphPattern]:
    """Copia de memory_service._normalize_patterns."""
    if not isinstance(patterns_input, list):
        patterns_input = [patterns_input]

    result = []
    for item in patterns_input:
        if isinstance(item, str):
            parts = [p.strip() for p in item.split("|")]
            if len(parts) == 3:
                result.append(GraphPattern(
                    subject=parts[0] if parts[0] else None,
                    predicate=parts[1] if parts[1] else None,
                    object=parts[2] if parts[2] else None,
                ))
        elif isinstance(item, dict):
            result.append(GraphPattern(**item))
        elif isinstance(item, GraphPattern):
            result.append(item)
    return result


def _normalize_entity_types(types: Dict[str, str]) -> Dict[str, str]:
    """Copia de memory_service._normalize_entity_types."""
    result = {}
    for entity, etype in types.items():
        result[entity] = etype if etype in ALLOWED_ENTITY_TYPES else "Other"
    return result


# =============================================================================
# Tests: _normalize_triplets
# =============================================================================

class TestNormalizeTriplets:

    def test_list_of_dicts(self):
        """Lista de dicts con los 3 campos."""
        result = _normalize_triplets([
            {"subject": "User", "predicate": "likes", "object": "cheese"},
        ])
        assert len(result) == 1
        assert result[0].subject == "User"
        assert result[0].predicate == "likes"
        assert result[0].object == "cheese"

    def test_legacy_strings(self):
        """Strings formato legacy 'S->P->O'."""
        result = _normalize_triplets(["User->likes->cheese"])
        assert len(result) == 1
        assert result[0].subject == "User"

    def test_mixed_list(self):
        """Mezcla de dicts y strings."""
        result = _normalize_triplets([
            {"subject": "User", "predicate": "likes", "object": "cheese"},
            "User->likes->coffee",
        ])
        assert len(result) == 2

    def test_single_dict_not_list(self):
        """Un solo dict (sin lista) se envuelve automáticamente."""
        result = _normalize_triplets({"subject": "User", "predicate": "likes", "object": "cheese"})
        assert len(result) == 1

    def test_empty_list(self):
        """Lista vacía devuelve lista vacía."""
        result = _normalize_triplets([])
        assert result == []

    def test_invalid_legacy_string(self):
        """String mal formado (menos de 3 partes) se ignora."""
        result = _normalize_triplets(["User->likes"])
        assert len(result) == 0

    def test_string_with_spaces(self):
        """String legacy con espacios alrededor de -> se limpia."""
        result = _normalize_triplets(["User -> likes -> cheese"])
        assert result[0].predicate == "likes"

    def test_predicate_with_underscore(self):
        """Predicate con snake_case se mantiene."""
        result = _normalize_triplets(["User->has_brother->Juan"])
        assert result[0].predicate == "has_brother"

    def test_multi_word_object(self):
        """Object con snake_case se mantiene."""
        result = _normalize_triplets(["User->bought->red_Toyota"])
        assert result[0].object == "red_Toyota"


# =============================================================================
# Tests: _normalize_patterns
# =============================================================================

class TestNormalizePatterns:

    def test_dict_with_none_value(self):
        """Pattern con object=None (wildcard)."""
        result = _normalize_patterns([
            {"subject": "User", "predicate": "likes", "object": None},
        ])
        assert len(result) == 1
        assert result[0].subject == "User"
        assert result[0].object is None

    def test_dict_all_none(self):
        """Pattern con todo None (wildcard total)."""
        result = _normalize_patterns([
            {"subject": None, "predicate": None, "object": None},
        ])
        assert result[0].subject is None

    def test_legacy_pipe_string(self):
        """String legacy 'S|P|O' con pipe."""
        result = _normalize_patterns(["User|likes|cheese"])
        assert result[0].subject == "User"
        assert result[0].predicate == "likes"
        assert result[0].object == "cheese"

    def test_legacy_pipe_with_empty(self):
        """String legacy con parte vacía 'S|P|' → None."""
        result = _normalize_patterns(["User|likes|"])
        assert result[0].object is None

    def test_legacy_pipe_all_empty(self):
        """String legacy '||' → todo None."""
        result = _normalize_patterns(["||"])
        assert result[0].subject is None
        assert result[0].object is None

    def test_invalid_legacy_string(self):
        """String con menos de 3 partes se ignora."""
        result = _normalize_patterns(["User|likes"])
        assert len(result) == 0

    def test_single_dict(self):
        """Un solo dict se envuelve en lista."""
        result = _normalize_patterns({"subject": "User", "predicate": "likes", "object": None})
        assert len(result) == 1

    def test_empty_list(self):
        """Lista vacía devuelve lista vacía."""
        result = _normalize_patterns([])
        assert result == []


# =============================================================================
# Tests: _normalize_entity_types
# =============================================================================

class TestNormalizeEntityTypes:

    def test_all_valid_types(self):
        """Los 10 tipos válidos pasan sin cambios."""
        types = {
            "a": "Person", "b": "Animal", "c": "Place", "d": "Object",
            "e": "Food", "f": "Event", "g": "Activity", "h": "Concept",
            "i": "Feeling", "j": "Other",
        }
        result = _normalize_entity_types(types)
        assert result == types

    def test_invalid_type(self):
        """Tipo no reconocido se mapea a 'Other'."""
        result = _normalize_entity_types({"User": "Alien"})
        assert result["User"] == "Other"

    def test_case_sensitive(self):
        """El enum es case-sensitive: 'person' (minúscula) no es válido."""
        result = _normalize_entity_types({"User": "person"})
        assert result["User"] == "Other"

    def test_mixed_valid_and_invalid(self):
        """Mezcla de válidos e inválidos."""
        result = _normalize_entity_types({
            "User": "Person",
            "Juan": "Human",  # inválido
            "Madrid": "Place",
        })
        assert result["User"] == "Person"
        assert result["Juan"] == "Other"
        assert result["Madrid"] == "Place"

    def test_empty_dict(self):
        """Dict vacío devuelve dict vacío."""
        assert _normalize_entity_types({}) == {}

    def test_numeric_type_value(self):
        """Valor numérico no es string, no está en ALLOWED_TYPES → se mapea a 'Other'.

        Nota: la comprobación `etype in ALLOWED_ENTITY_TYPES` con un int
        simplemente devuelve False (no lanza excepción), así que el resultado
        es User → Other.
        """
        result = _normalize_entity_types({"User": 123})
        assert result["User"] == "Other"
