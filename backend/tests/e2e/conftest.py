"""
Fixtures para tests E2E.

El aislamiento de bases de datos lo proporciona el stack de test
(docker-compose.test.yml + scripts/run_e2e_tests.sh):
  - postgres_test, qdrant_test, dgraph_test son instancias efimeras
  - se destruyen con docker compose down -v al terminar
  - el unico dato que toca produccion es n8n_chat_histories (n8n es
    compartido), que limpia el script de orquestacion por prefijo test_e2e_

Este conftest solo proporciona:
  - healthcheck del backend de test
  - warmup (carga NLLB + Ollama)
  - helpers (run_chat_prompt, extract_actions_from_response)
"""

import os
import json
import time
import logging
import pytest
import httpx

logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_prompts() -> dict:
    path = os.path.join(_DATA_DIR, "prompts.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def latency_prompts(test_prompts: dict) -> dict:
    return test_prompts.get("latency", {})


# ---------------------------------------------------------------------------
# Healthcheck
# ---------------------------------------------------------------------------

def _healthcheck(url: str, label: str, timeout: int = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=5)
            if resp.status_code < 500:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(1)
    logger.warning("Healthcheck failed for %s (%s)", label, url)
    return False


@pytest.fixture(scope="session")
def services_ready() -> bool:
    ok = _healthcheck(f"{BACKEND_URL}/frontend/settings", "Backend /settings")
    if not ok:
        pytest.skip("Backend not available at " + BACKEND_URL)
    return True


# ---------------------------------------------------------------------------
# Warmup: cargar NLLB + Ollama antes de medir latencia
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def warmup_backend(http_client, services_ready: bool) -> None:
    """Warm up NLLB and Ollama before measuring."""
    logger.info("Warming up NLLB + Ollama...")
    t0 = time.perf_counter()
    try:
        http_client.post("/frontend/chat", json={
            "message": "hola",
            "chat_id": "warmup-e2e-session",
        }, timeout=180)
        elapsed = time.perf_counter() - t0
        logger.info("Warmup complete in %.1fs", elapsed)
    except Exception as exc:
        logger.warning("Warmup failed (continuing): %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_chat_prompt(
    client: httpx.Client,
    prompt: str,
    chat_id: str = None,
) -> dict:
    """POST /frontend/chat and return response JSON."""
    if chat_id is None:
        chat_id = "test_e2e_" + str(time.time()).replace(".", "")
    payload = {"message": prompt, "chat_id": chat_id}
    resp = client.post("/frontend/chat", json=payload)
    assert resp.status_code == 200, (
        f"Chat endpoint returned {resp.status_code}: {resp.text[:200]}"
    )
    return resp.json()


def extract_actions_from_response(response: dict) -> list[str]:
    """Extract action types from action_details."""
    details = response.get("action_details", [])
    if isinstance(details, list):
        actions = [d.get("type", "").upper() for d in details if isinstance(d, dict)]
        return actions if actions else ["NONE"]
    return []


def model_skip_condition(model: dict, skip_key: str = "skip_accuracy") -> bool:
    return model.get(skip_key, False)
