"""
Utilidades de cálculo de métricas para tests E2E.

Proporciona:
  - compute_latency_stats: media, p50, p95, p99, std, min, max
  - compute_accuracy: ratio de aciertos
  - save_report: guarda resultados en JSON dentro de tests/reports/
"""

import os
import json
import statistics
from datetime import datetime, timezone
from typing import Sequence


def compute_latency_stats(times: Sequence[float]) -> dict:
    """Calcula estadísticas de latencia a partir de una lista de tiempos en segundos.

    Args:
        times: Lista de tiempos de respuesta (segundos).

    Returns:
        Dict con mean, p50, p95, p99, std, min, max, n.
        Si la lista está vacía, todos los valores son 0.0.
    """
    if not times:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0,
                "std": 0.0, "min": 0.0, "max": 0.0, "n": 0}

    sorted_times = sorted(times)
    n = len(sorted_times)

    def percentile(p: float) -> float:
        """Calcula percentil usando interpolación lineal."""
        if n == 1:
            return sorted_times[0]
        k = (p / 100.0) * (n - 1)
        f = int(k)
        c = k - f
        if f + 1 < n:
            return sorted_times[f] + c * (sorted_times[f + 1] - sorted_times[f])
        return sorted_times[f]

    return {
        "mean": round(statistics.mean(times), 2),
        "p50": round(percentile(50), 2),
        "p95": round(percentile(95), 2),
        "p99": round(percentile(99), 2),
        "std": round(statistics.stdev(times), 2) if n > 1 else 0.0,
        "min": round(min(times), 2),
        "max": round(max(times), 2),
        "n": n,
    }


def compute_accuracy(correct: int, total: int) -> float:
    """Calcula ratio de aciertos.

    Args:
        correct: Número de intentos correctos.
        total: Número total de intentos.

    Returns:
        Ratio 0.0-1.0. Si total es 0, devuelve 0.0.
    """
    if total == 0:
        return 0.0
    return round(correct / total, 4)


def save_report(report: dict, report_dir: str, test_type: str) -> str:
    """Guarda un reporte de test en un fichero JSON.

    Args:
        report: Datos del reporte (serializables a JSON).
        report_dir: Directorio donde guardar (ej: 'backend/tests/reports').
        test_type: Tipo de test ('latency' o 'accuracy').

    Returns:
        Ruta absoluta al fichero generado.
    """
    os.makedirs(report_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{test_type}_{timestamp}.json"
    filepath = os.path.join(report_dir, filename)

    report["_generated_at"] = datetime.now(timezone.utc).isoformat()
    report["_test_type"] = test_type

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return filepath
