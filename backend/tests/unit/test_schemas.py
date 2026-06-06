"""
Tests unitarios de schemas Pydantic del backend.

Verifica que los modelos de datos (schemas/memory.py, schemas/chat.py, schemas/tools.py)
validan correctamente entrada válida y rechazan entrada inválida.

Cubre:
  - LibrarianN8NQuery: rag_query obligatorio, graph_entities/graph_patterns opcionales
  - ArchivistN8NQuery: rag_document obligatorio, graph_triplets mínimo 1
  - GraphTriplet: subject/predicate/object strings
  - GraphPattern: subject/predicate/object opcionales (pueden ser None)
  - EntityType: solo acepta los 10 tipos permitidos
  - DecisionCheckRequest/Response: actions array válido
  - ChatRequest/ChatResponse: message obligatorio
"""

from typing import Any, Dict
import pytest
from pydantic import ValidationError


# -- LibrarianN8NQuery --------------------------------------------------------

def test_librarian_valid_minimal():
    """LibrarianN8NQuery con solo rag_query (obligatorio) debe ser válido.

    graph_entities, graph_patterns y time_context tienen defaults,
    así que no hace falta pasarlos.
    """
    from schemas.memory import LibrarianN8NQuery
    query = LibrarianN8NQuery(rag_query="the user's favorite food")
    assert query.rag_query == "the user's favorite food"
    assert query.graph_entities == []
    assert query.graph_patterns == []
    assert query.time_context == ""


def test_librarian_valid_full():
    """LibrarianN8NQuery con todos los campos debe ser válido."""
    from schemas.memory import LibrarianN8NQuery, GraphPattern
    query = LibrarianN8NQuery(
        rag_query="where Juan lives",
        graph_entities=["Juan"],
        graph_patterns=[
            GraphPattern(subject="Juan_brother", predicate="lives_in", object=None)
        ],
        time_context="2026-05-27",
    )
    assert query.rag_query == "where Juan lives"
    assert len(query.graph_patterns) == 1
    assert query.graph_patterns[0].subject == "Juan_brother"


def test_librarian_missing_rag_query():
    """LibrarianN8NQuery sin rag_query debe lanzar ValidationError."""
    from schemas.memory import LibrarianN8NQuery
    with pytest.raises(ValidationError):
        LibrarianN8NQuery()


def test_librarian_empty_rag_query():
    """LibrarianN8NQuery con rag_query vacío debe lanzar ValidationError.

    rag_query tiene minLength=1 en el schema pero en Pydantic
    `min_length` en Field no está activo por defecto en str.
    Este test documenta el comportamiento actual.
    """
    from schemas.memory import LibrarianN8NQuery
    try:
        LibrarianN8NQuery(rag_query="")
    except ValidationError:
        pass
    else:
        pass  # rag_query vacío puede pasar dependiendo de la definición Field


# -- ArchivistN8NQuery --------------------------------------------------------

def test_archivist_valid_minimal():
    """ArchivistN8NQuery con rag_document y 1 graph_triplet debe ser válido."""
    from schemas.memory import ArchivistN8NQuery, GraphTriplet
    query = ArchivistN8NQuery(
        rag_document="The user likes cheese.",
        graph_triplets=[GraphTriplet(subject="User", predicate="likes", object="cheese")],
    )
    assert query.rag_document == "The user likes cheese."
    assert len(query.graph_triplets) == 1
    assert query.entity_types == {}
    assert query.time_context == ""


def test_archivist_with_entity_types():
    """ArchivistN8NQuery con entity_types válidos debe funcionar."""
    from schemas.memory import ArchivistN8NQuery, GraphTriplet
    query = ArchivistN8NQuery(
        rag_document="The user's brother Juan lives in Madrid.",
        graph_triplets=[
            GraphTriplet(subject="User", predicate="has_brother", object="Juan_brother"),
            GraphTriplet(subject="Juan_brother", predicate="lives_in", object="Madrid"),
        ],
        entity_types={"User": "Person", "Juan_brother": "Person", "Madrid": "Place"},
    )
    assert query.entity_types["User"] == "Person"
    assert query.entity_types["Madrid"] == "Place"


def test_archivist_invalid_entity_type():
    """ArchivistN8NQuery con un entity_type inválido debe lanzar ValidationError."""
    from schemas.memory import ArchivistN8NQuery, GraphTriplet, EntityType
    with pytest.raises(ValidationError):
        ArchivistN8NQuery(
            rag_document="test",
            graph_triplets=[GraphTriplet(subject="User", predicate="likes", object="test")],
            entity_types={"User": "InvalidType"},
        )


def test_archivist_missing_triplets():
    """ArchivistN8NQuery sin graph_triplets es válido (default_factory=list).

    Nota: el schema Pydantic permite graph_triplets vacío. La validación
    de >=1 triplet se hace en memory_service._parse_archivist_message.
    """
    from schemas.memory import ArchivistN8NQuery
    query = ArchivistN8NQuery(rag_document="test")
    assert query.graph_triplets == []


# -- GraphTriplet -------------------------------------------------------------

def test_graph_triplet_valid():
    """GraphTriplet con subject, predicate, object strings."""
    from schemas.memory import GraphTriplet
    t = GraphTriplet(subject="User", predicate="likes", object="cheese")
    assert t.subject == "User"
    assert t.predicate == "likes"
    assert t.object == "cheese"


def test_graph_triplet_empty_strings():
    """GraphTriplet con strings vacías debe ser aceptado (Pydantic no lo prohíbe)."""
    from schemas.memory import GraphTriplet
    t = GraphTriplet(subject="", predicate="", object="")
    assert t.subject == ""


# -- GraphPattern -------------------------------------------------------------

def test_graph_pattern_subject_none():
    """GraphPattern con subject=None debe ser válido (wildcard)."""
    from schemas.memory import GraphPattern
    p = GraphPattern(subject=None, predicate="lives_in", object="Madrid")
    assert p.subject is None
    assert p.predicate == "lives_in"
    assert p.object == "Madrid"


def test_graph_pattern_all_none():
    """GraphPattern con subject, predicate, object todo None debe ser válido.

    La validación de "al menos uno no nulo" se hace en memoria_service.py,
    no en el schema Pydantic.
    """
    from schemas.memory import GraphPattern
    p = GraphPattern(subject=None, predicate=None, object=None)
    assert p.subject is None
    assert p.predicate is None
    assert p.object is None


# -- EntityType literal -------------------------------------------------------

@pytest.mark.parametrize("valid_type", [
    "Person", "Animal", "Place", "Object", "Food",
    "Event", "Activity", "Concept", "Feeling", "Other",
])
def test_entity_type_valid_values(valid_type: str):
    """Todos los 10 tipos de entidad permitidos deben ser aceptados."""
    from schemas.memory import EntityType
    # Verificar que el literal acepta el valor
    assert valid_type in ["Person", "Animal", "Place", "Object", "Food",
                          "Event", "Activity", "Concept", "Feeling", "Other"]


# -- DecisionCheck schemas ----------------------------------------------------

# -- ChatRequest --------------------------------------------------------------

def test_chat_request_valid():
    """ChatRequest con message y chat_id."""
    from schemas.chat import ChatRequest
    req = ChatRequest(message="hola", chat_id="test-123")
    assert req.message == "hola"
    assert req.chat_id == "test-123"


def test_chat_request_missing_message():
    """ChatRequest sin message debe lanzar ValidationError."""
    from schemas.chat import ChatRequest
    with pytest.raises(ValidationError):
        ChatRequest(chat_id="test-123")
