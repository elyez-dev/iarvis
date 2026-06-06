"""
Tests unitarios de decision_check del backend.

Valida la lógica de ChatService.decision_check() que:
  1. Parsea JSON del ROUTER ({actions: ["SEARCH","STORE","TOOL","NONE"]})
  2. Valida que sean keywords conocidos
  3. NONE debe ir solo
  4. Devuelve DecisionCheckResponse(search, store, tool) como booleans
"""

import json
from typing import Optional
import pytest
from pydantic import BaseModel

pytestmark = pytest.mark.unit


# Schema de respuesta (copia de schemas/chat.py para evitar dependencia)
class DecisionCheckResponse(BaseModel):
    search: bool = False
    store: bool = False
    tool: bool = False


VALID_ACTIONS = {"SEARCH", "STORE", "TOOL", "NONE"}


def _decision_check(message: str, tries: Optional[int] = None) -> dict:
    """Copia simplificada de ChatService.decision_check().

    La implementación real (chat_service.py) hace:
      1. json.loads del mensaje
      2. Extrae actions del dict
      3. Valida contra VALID_ACTIONS
      4. Si NONE presente, checkea que sea el único
      5. Devuelve DecisionCheckResponse con booleans
      6. Si algo falla, lanza HTTPException(400) con tries+1

    Este test prueba la lógica pura sin HTTP.
    """
    try:
        data = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Invalid JSON")

    actions = data.get("actions", [])
    if not isinstance(actions, list) or len(actions) == 0:
        raise ValueError("actions must be a non-empty list")

    for action in actions:
        if action not in VALID_ACTIONS:
            raise ValueError(f"Invalid action: {action}")

    if "NONE" in actions and len(actions) > 1:
        raise ValueError("NONE must appear alone")

    response = DecisionCheckResponse(
        search="SEARCH" in actions,
        store="STORE" in actions,
        tool="TOOL" in actions,
    )
    return response.model_dump()


# -- Tests: acciones válidas --------------------------------------------------

def test_search_only():
    """SEARCH solo debe devolver search=True, store=False, tool=False."""
    result = _decision_check('{"actions":["SEARCH"]}')
    assert result["search"] is True
    assert result["store"] is False
    assert result["tool"] is False


def test_store_only():
    """STORE solo debe devolver store=True."""
    result = _decision_check('{"actions":["STORE"]}')
    assert result["search"] is False
    assert result["store"] is True
    assert result["tool"] is False


def test_tool_only():
    """TOOL solo debe devolver tool=True."""
    result = _decision_check('{"actions":["TOOL"]}')
    assert result["search"] is False
    assert result["store"] is False
    assert result["tool"] is True


def test_none_only():
    """NONE solo debe devolver todo False."""
    result = _decision_check('{"actions":["NONE"]}')
    assert result["search"] is False
    assert result["store"] is False
    assert result["tool"] is False


def test_search_and_store():
    """SEARCH + STORE combinados."""
    result = _decision_check('{"actions":["SEARCH","STORE"]}')
    assert result["search"] is True
    assert result["store"] is True
    assert result["tool"] is False


def test_all_three():
    """SEARCH + STORE + TOOL combinados."""
    result = _decision_check('{"actions":["SEARCH","STORE","TOOL"]}')
    assert result["search"] is True
    assert result["store"] is True
    assert result["tool"] is True


# -- Tests: acciones inválidas ------------------------------------------------

def test_none_with_others():
    """NONE combinado con otras acciones debe lanzar error.

    Regla: si NONE está presente, debe ser el único elemento.
    """
    with pytest.raises(ValueError, match="NONE must appear alone"):
        _decision_check('{"actions":["NONE","SEARCH"]}')


def test_empty_actions():
    """Array vacío debe lanzar error."""
    with pytest.raises(ValueError, match="non-empty"):
        _decision_check('{"actions":[]}')


def test_missing_actions_key():
    """JSON sin clave actions debe lanzar error."""
    with pytest.raises(ValueError, match="actions"):
        _decision_check('{"foo":"bar"}')


def test_invalid_action_name():
    """Action no reconocida debe lanzar error."""
    with pytest.raises(ValueError, match="INVALID"):
        _decision_check('{"actions":["INVALID"]}')


def test_invalid_json():
    """JSON malformado debe lanzar error."""
    with pytest.raises(ValueError, match="Invalid JSON"):
        _decision_check("{invalid json}")


def test_invalid_not_json():
    """Texto plano no JSON debe lanzar error."""
    with pytest.raises(ValueError, match="Invalid JSON"):
        _decision_check("this is not json")


# -- Tests: orden y duplicados ------------------------------------------------

def test_actions_order_independent():
    """El orden de las actions no afecta al resultado."""
    r1 = _decision_check('{"actions":["STORE","SEARCH"]}')
    r2 = _decision_check('{"actions":["SEARCH","STORE"]}')
    assert r1 == r2


def test_duplicate_actions():
    """Actions duplicadas no afectan al booleano (set semantics)."""
    result = _decision_check('{"actions":["SEARCH","SEARCH","SEARCH"]}')
    assert result["search"] is True
    assert result["store"] is False


# -- Tests: formato del JSON --------------------------------------------------

def test_with_whitespace():
    """JSON con espacios y saltos de línea extra."""
    msg = """
    {
        "actions": ["SEARCH"]
    }
    """
    result = _decision_check(msg)
    assert result["search"] is True
