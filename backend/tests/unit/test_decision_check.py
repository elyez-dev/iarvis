"""
Unit tests for decision_check validation logic.
"""

import json
from typing import Optional
import pytest
from pydantic import BaseModel

pytestmark = pytest.mark.unit


# Inline copy to avoid dependency on real schemas.
class DecisionCheckResponse(BaseModel):
    search: bool = False
    store: bool = False
    tool: bool = False


VALID_ACTIONS = {"SEARCH", "STORE", "TOOL", "NONE"}


def _decision_check(message: str, tries: Optional[int] = None) -> dict:
    """Simplified copy of ChatService.decision_check() for isolated testing."""
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


# -- Valid actions --

def test_search_only():
    """SEARCH alone returns search=True, store=False, tool=False."""
    result = _decision_check('{"actions":["SEARCH"]}')
    assert result["search"] is True
    assert result["store"] is False
    assert result["tool"] is False


def test_store_only():
    """STORE alone returns store=True."""
    result = _decision_check('{"actions":["STORE"]}')
    assert result["search"] is False
    assert result["store"] is True
    assert result["tool"] is False


def test_tool_only():
    """TOOL alone returns tool=True."""
    result = _decision_check('{"actions":["TOOL"]}')
    assert result["search"] is False
    assert result["store"] is False
    assert result["tool"] is True


def test_none_only():
    """NONE alone returns all False."""
    result = _decision_check('{"actions":["NONE"]}')
    assert result["search"] is False
    assert result["store"] is False
    assert result["tool"] is False


def test_search_and_store():
    """SEARCH + STORE combined."""
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


# -- Invalid actions --

def test_none_with_others():
    """NONE combined with other actions raises an error."""
    with pytest.raises(ValueError, match="NONE must appear alone"):
        _decision_check('{"actions":["NONE","SEARCH"]}')


def test_empty_actions():
    """Empty actions list raises an error."""
    with pytest.raises(ValueError, match="non-empty"):
        _decision_check('{"actions":[]}')


def test_missing_actions_key():
    """Missing actions key raises an error."""
    with pytest.raises(ValueError, match="actions"):
        _decision_check('{"foo":"bar"}')


def test_invalid_action_name():
    """Unrecognized action raises an error."""
    with pytest.raises(ValueError, match="INVALID"):
        _decision_check('{"actions":["INVALID"]}')


def test_invalid_json():
    """Malformed JSON raises an error."""
    with pytest.raises(ValueError, match="Invalid JSON"):
        _decision_check("{invalid json}")


def test_invalid_not_json():
    """Plain text (not JSON) raises an error."""
    with pytest.raises(ValueError, match="Invalid JSON"):
        _decision_check("this is not json")


# -- Order and duplicates --

def test_actions_order_independent():
    """Action order does not affect the result."""
    r1 = _decision_check('{"actions":["STORE","SEARCH"]}')
    r2 = _decision_check('{"actions":["SEARCH","STORE"]}')
    assert r1 == r2


def test_duplicate_actions():
    """Duplicate actions do not affect the boolean result (set semantics)."""
    result = _decision_check('{"actions":["SEARCH","SEARCH","SEARCH"]}')
    assert result["search"] is True
    assert result["store"] is False


# -- JSON format --

def test_with_whitespace():
    """JSON with extra whitespace and line breaks."""
    msg = """
    {
        "actions": ["SEARCH"]
    }
    """
    result = _decision_check(msg)
    assert result["search"] is True
