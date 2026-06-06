"""
Tests E2E de latencia end-to-end del flujo iArvis.

Mide el tiempo desde que se envía un mensaje a /frontend/chat hasta que
se recibe la respuesta traducida, para cada modelo de Ollama configurado.

Dos tipos de mensaje:
  - simple: "hola" → clasificación NONE, respuesta trivial
  - complex: "explícame en unas 100 palabras la diferencia entre vino tinto y blanco"
             → clasificación NONE, respuesta larga (mide generación de texto)

Para cada modelo × mensaje se ejecutan N iteraciones (configurable con
--iterations, default 5). Se calculan media, p50, p95 y desviación.

Los resultados se guardan en backend/tests/reports/latency_{timestamp}.json.
"""

import os
import json
import time
import logging
import pytest

from tests.utils.metrics import compute_latency_stats, save_report
from tests.e2e.conftest import (
    run_chat_prompt,
    model_skip_condition,
)

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.latency,
]


# =============================================================================
# Tests parametrizados por modelo
# =============================================================================


def pytest_generate_tests(metafunc):
    """Genera tests parametrizados para cada modelo no-skipeado.

    Esta función se ejecuta en colección y permite generar un test por modelo
    sin tener que anidar bucles dentro del test.
    """
    if "model" in metafunc.fixturenames:
        models_path = os.path.join(os.path.dirname(__file__), "..", "data", "models.json")
        with open(models_path) as f:
            all_models = json.load(f)["models"]

        # Filtrar los que no son de embedding y no tienen skip
        models = [
            m for m in all_models
            if not m.get("embedding", False) and not m.get("skip_latency", False)
        ]

        # Aplicar filtro CLI --model si existe
        model_filter = metafunc.config.getoption("--model", default=None)
        if model_filter:
            models = [m for m in models if model_filter.lower() in m["name"].lower()]

        metafunc.parametrize(
            "model",
            models,
            ids=[m["name"] for m in models],
            scope="session",
        )


# =============================================================================
# Test de latencia
# =============================================================================


class TestLatency:
    """Suite de tests de latencia end-to-end.

    Para cada modelo, envía un mensaje simple y uno complejo N veces y mide
    el tiempo de respuesta. Al final, computa estadísticas y las guarda.
    """

    def test_simple_message_latency(
        self,
        http_client,
        model: dict,
        iterations: int,
        latency_prompts: dict,
        report_dir: str,
        warmup_backend,
    ):
        """Mide latencia media para un mensaje simple ('hola').

        Args:
            http_client: Cliente HTTP (fixture).
            model: Dict del modelo actual.
            iterations: Número de iteraciones (fixture --iterations).
            latency_prompts: Diccionario con prompts de latencia.
            report_dir: Directorio para reportes.
        """
        prompt = latency_prompts.get("simple", "hola")
        model_name = model["name"]
        test_t0 = time.perf_counter()
        times = []

        for i in range(iterations):
            t0 = time.perf_counter()
            response = run_chat_prompt(http_client, prompt)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

            logger.info(
                "[%s] simple iter %d/%d: %.2fs",
                model_name, i + 1, iterations, elapsed,
            )

            # Sanity check: el backend devolvió respuesta no vacía
            assert "response" in response, f"Missing 'response' in iteration {i}"
            assert len(response["response"]) > 0, f"Empty response in iteration {i}"

        # Calcular estadísticas
        stats = compute_latency_stats(times)
        stats["model"] = model_name
        stats["prompt_type"] = "simple"
        stats["prompt_text"] = prompt

        logger.info(
            "[%s] simple latency stats: mean=%.2fs p50=%.2fs p95=%.2fs (n=%d)",
            model_name, stats["mean"], stats["p50"], stats["p95"], stats["n"],
        )

        # Guardar reporte parcial
        report = {
            "model": model_name,
            "prompt_type": "simple",
            "prompt_text": prompt,
            "iterations": iterations,
            "test_duration_s": round(time.perf_counter() - test_t0, 2),
            "stats": stats,
            "raw_times": [round(t, 3) for t in times],
        }
        save_report(report, report_dir, "latency")

        # Assert básico: la media debe ser menor que el timeout
        timeout = 180  # segundos
        assert stats["mean"] < timeout, (
            f"Mean latency {stats['mean']}s exceeds sanity timeout {timeout}s"
        )

    def test_complex_message_latency(
        self,
        http_client,
        model: dict,
        iterations: int,
        latency_prompts: dict,
        report_dir: str,
        warmup_backend,
    ):
        """Mide latencia media para un mensaje que requiere generar texto largo.

        Args:
            http_client: Cliente HTTP (fixture).
            model: Dict del modelo actual.
            iterations: Número de iteraciones (fixture --iterations).
            latency_prompts: Diccionario con prompts de latencia.
            report_dir: Directorio para reportes.
        """
        prompt = latency_prompts.get(
            "complex",
            "explícame en unas 100 palabras cuál es la diferencia entre el vino tinto y el vino blanco",
        )
        model_name = model["name"]
        test_t0 = time.perf_counter()
        times = []

        for i in range(iterations):
            t0 = time.perf_counter()
            response = run_chat_prompt(http_client, prompt)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

            logger.info(
                "[%s] complex iter %d/%d: %.2fs",
                model_name, i + 1, iterations, elapsed,
            )

            assert "response" in response, f"Missing 'response' in iteration {i}"
            assert len(response["response"]) > 0, f"Empty response in iteration {i}"

        stats = compute_latency_stats(times)
        stats["model"] = model_name
        stats["prompt_type"] = "complex"
        stats["prompt_text"] = prompt

        logger.info(
            "[%s] complex latency stats: mean=%.2fs p50=%.2fs p95=%.2fs (n=%d)",
            model_name, stats["mean"], stats["p50"], stats["p95"], stats["n"],
        )

        report = {
            "model": model_name,
            "prompt_type": "complex",
            "prompt_text": prompt,
            "iterations": iterations,
            "test_duration_s": round(time.perf_counter() - test_t0, 2),
            "stats": stats,
            "raw_times": [round(t, 3) for t in times],
        }
        save_report(report, report_dir, "latency")

        assert stats["mean"] < 180, (
            f"Mean latency {stats['mean']}s exceeds sanity timeout 180s"
        )
