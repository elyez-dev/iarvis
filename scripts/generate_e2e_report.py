#!/usr/bin/env python3
"""
Genera un reporte consolidado multi-modelo desde los JSON de tests E2E.

Lee todos los JSON en backend/tests/reports/ y produce:
  docs/e2e-multi-model-report.md

con tablas comparativas de latencia, certeza, y conclusiones para la memoria.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "tests", "reports")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "docs", "e2e-multi-model-report.md")

MODEL_LABELS = {
    "qwen2.5:1.5b": "Qwen 2.5 1.5B",
    "qwen2.5:3b": "Qwen 2.5 3B",
    "qwen2.5-coder:1.5b": "Qwen Coder 1.5B",
    "gemma2:2b": "Gemma 2 2B",
    "llama3.2:latest": "Llama 3.2 3B",
}


def load_reports():
    """Carga todos los JSON de reports/ y los organiza por modelo y tipo."""
    if not os.path.isdir(REPORTS_DIR):
        print(f"No reports dir: {REPORTS_DIR}", file=sys.stderr)
        return {}

    data = defaultdict(lambda: defaultdict(dict))
    for fname in sorted(os.listdir(REPORTS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(REPORTS_DIR, fname)
        with open(path) as f:
            report = json.load(f)

        model = report.get("model", "unknown")
        test_type = report.get("test") or report.get("prompt_type", "unknown")

        if report.get("prompt_type"):  # latency report
            key = f"latency_{report['prompt_type']}"
        else:
            key = test_type

        data[model][key] = report

    return data


def format_latency_row(model: str, reports: dict) -> str:
    simple = reports.get("latency_simple", {}).get("stats", {})
    complex_ = reports.get("latency_complex", {}).get("stats", {})
    s_dur = reports.get("latency_simple", {}).get("test_duration_s", "?")
    c_dur = reports.get("latency_complex", {}).get("test_duration_s", "?")

    def fmt(stats, key):
        val = stats.get(key, "?")
        return f"{val:.1f}s" if isinstance(val, (int, float)) else str(val)

    label = MODEL_LABELS.get(model, model)
    return (
        f"| {label:20s} | {fmt(simple,'mean'):>8s} | {fmt(simple,'p50'):>8s} "
        f"| {fmt(simple,'p95'):>8s} | {fmt(simple,'std'):>6s} "
        f"| {fmt(complex_,'mean'):>8s} | {fmt(complex_,'p50'):>8s} "
        f"| {fmt(complex_,'p95'):>8s} | {fmt(complex_,'std'):>6s} "
        f"| {s_dur}s / {c_dur}s |"
    )


def format_accuracy_row(model: str, reports: dict) -> str:
    label = MODEL_LABELS.get(model, model)

    def pct(key):
        r = reports.get(key, {})
        return f"{r.get('overall_accuracy', 0) * 100:.0f}%"

    return (
        f"| {label:20s} | {pct('router_classification'):>6s} "
        f"| {pct('archivist_end_to_end'):>6s} "
        f"| {pct('librarian_end_to_end'):>6s} "
        f"| {pct('store_persistence'):>6s} "
        f"| {pct('search_retrieval'):>6s} "
        f"| {pct('tool_execution_mock'):>6s} |"
    )


def format_latency_table(data: dict) -> str:
    models = sorted(data.keys())
    header = (
        "| Modelo | Simple mean | Simple p50 | Simple p95 | Simple std | "
        "Complex mean | Complex p50 | Complex p95 | Complex std | Duracion total |\n"
        "|--------|------------|-----------|-----------|-----------|"
        "------------|-----------|-----------|-----------|---------------|"
    )
    rows = "\n".join(format_latency_row(m, data[m]) for m in models)
    return header + "\n" + rows


def format_accuracy_table(data: dict) -> str:
    models = sorted(data.keys())
    header = (
        "| Modelo | ROUTER | ARCHIVIST | LIBRARIAN | STORE persist | SEARCH retrieve | TOOL mock |\n"
        "|--------|--------|-----------|-----------|---------------|-----------------|-----------|"
    )
    rows = "\n".join(format_accuracy_row(m, data[m]) for m in models)
    return header + "\n" + rows


def format_raw_times(data: dict) -> str:
    """Muestra raw times para visualizar dispersion."""
    lines = []
    for model in sorted(data.keys()):
        label = MODEL_LABELS.get(model, model)
        simple_times = data[model].get("latency_simple", {}).get("raw_times", [])
        complex_times = data[model].get("latency_complex", {}).get("raw_times", [])

        lines.append(f"**{label}**")
        if simple_times:
            bars = "".join("█" if t > 18 else "▆" for t in simple_times)
            vals = ", ".join(f"{t:.1f}s" for t in simple_times)
            lines.append(f"  Simple:  [{vals}]")
            lines.append(f"           [{bars}] ({len(simple_times)} iter)")
        if complex_times:
            avg = sum(complex_times) / len(complex_times)
            bars = "".join("█" if t > avg else "▄" for t in complex_times)
            vals = ", ".join(f"{t:.1f}s" for t in complex_times)
            lines.append(f"  Complex: [{vals}]")
            lines.append(f"           [{bars}] ({len(complex_times)} iter)")
    return "\n".join(lines)


def generate_report():
    data = load_reports()
    if not data:
        print("No report data found!", file=sys.stderr)
        sys.exit(1)

    models = sorted(data.keys())
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    report = f"""# Informe comparativo multi-modelo — iArvis E2E

> **Generado**: {generated_at}
> **Modelos testeados**: {len(models)} ({', '.join(MODEL_LABELS.get(m, m) for m in models)})
> **Iteraciones por test**: 10
> **Hardware**: HP Compaq 8200 Elite SFF, Nvidia T600 4GB, Ubuntu Server

---

## 1. Latencia end-to-end

Tiempo total desde `POST /frontend/chat` hasta respuesta traducida (incluye
NLLB ES↔EN + n8n workflow + Ollama inferencia).

{format_latency_table(data)}

### Raw times por iteracion

{format_raw_times(data)}

---

## 2. Certeza (accuracy)

Porcentaje de ejecuciones correctas. ROUTER mide clasificacion SEARCH/NONE.
ARCHIVIST/LIBRARIAN miden que el flujo no crashee (respuesta no vacia).
STORE persist y SEARCH retrieve miden verificacion real contra Qdrant.
TOOL mock mide ejecucion del pipeline de herramientas.

{format_accuracy_table(data)}

---

## 3. Conclusiones para la memoria

### Mejor modelo global

_(A rellenar tras analizar los datos: cual tiene mejor balance velocidad/calidad)_

### Latencia

_(A rellenar: comparativa de tiempos, cual es mas rapido, cual mas lento, diferencias)_

### Certeza

_(A rellenar: cual clasifica mejor, cual genera JSON mas fiable, cual recupera mejor)_

### Observaciones

- Simple (\"hola\") mide overhead de traduccion + n8n; ~17s con qwen2.5:3b.
- Complex (100 palabras) mide generacion de texto; dominado por velocidad de inferencia.
- La desviacion estandar (std) indica consistencia: <1s = muy predecible, >5s = variable.
- El mock tool (`tool_test_echo`) no depende de integraciones externas.

---

## 4. Datos crudos

Los JSON completos estan en `backend/tests/reports/`. Para regenerar este
informe: `python3 scripts/generate_e2e_report.py`
"""

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        f.write(report)

    print(f"Report generated: {OUTPUT_FILE}")
    print(f"Models: {', '.join(models)}")


if __name__ == "__main__":
    generate_report()
