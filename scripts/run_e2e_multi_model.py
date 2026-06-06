#!/usr/bin/env python3
"""
Ejecuta secuencialmente los tests E2E que faltan para todos los modelos.
Cambia el modelo de n8n entre ejecuciones.
Progreso y resultados en /tmp/e2e_progress.log
"""
import subprocess
import sqlite3
import json
import time
import os
import sys
from datetime import datetime

REPO_ROOT = "/home/eloi/iarvis/iarvis"
VENV_PYTHON = f"{REPO_ROOT}/.venv/bin/python"
N8N_DB = f"{REPO_ROOT}/n8n/database.sqlite"
TEST_ACC = f"{REPO_ROOT}/backend/tests/e2e/test_accuracy.py"
TEST_LAT = f"{REPO_ROOT}/backend/tests/e2e/test_latency.py"
PYTHONPATH = f"backend"

LOG_FILE = "/tmp/e2e_progress.log"

MODELS = [
    {
        "name": "gemma2:2b",
        "tests": [
            ("router", f"{TEST_ACC}::TestRouterAccuracy"),
            ("archivist", f"{TEST_ACC}::TestArchivistJSONQuality"),
            ("store", f"{TEST_ACC}::TestStorePersistence"),
            ("search", f"{TEST_ACC}::TestSearchRetrieval"),
            ("tool", f"{TEST_ACC}::TestToolExecution"),
        ],
    },
    {
        "name": "qwen2.5:1.5b",
        "tests": [
            ("store", f"{TEST_ACC}::TestStorePersistence"),
            ("search", f"{TEST_ACC}::TestSearchRetrieval"),
            ("tool", f"{TEST_ACC}::TestToolExecution"),
        ],
    },
    {
        "name": "qwen2.5:3b",
        "tests": [
            ("store", f"{TEST_ACC}::TestStorePersistence"),
            ("search", f"{TEST_ACC}::TestSearchRetrieval"),
            ("tool", f"{TEST_ACC}::TestToolExecution"),
        ],
    },
    {
        "name": "llama3.2:latest",
        "tests": [
            ("store", f"{TEST_ACC}::TestStorePersistence"),
            ("search", f"{TEST_ACC}::TestSearchRetrieval"),
            ("tool", f"{TEST_ACC}::TestToolExecution"),
            ("complex_latency", f"{TEST_LAT}::TestLatency::test_complex_message_latency"),
        ],
    },
]

ITERATIONS = 10
LATENCY_ITERATIONS = 5  # reduced for llama3.2 to avoid timeout

OLLAMA_TYPES = [
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    "@n8n/n8n-nodes-langchain.lmOllama",
]


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def switch_n8n_model(target: str):
    """Update all Ollama nodes in n8n SQLite to use target model."""
    conn = sqlite3.connect(N8N_DB)
    for t, c in [("workflow_entity", "id"), ("workflow_history", "versionId")]:
        for row in conn.execute(f"SELECT {c}, nodes FROM {t}"):
            eid, nodes_json = row
            nodes = json.loads(nodes_json)
            changed = False
            for node in nodes:
                if node.get("type") in OLLAMA_TYPES:
                    current = node.get("parameters", {}).get("model", "")
                    if current != target:
                        node["parameters"]["model"] = target
                        changed = True
            if changed:
                conn.execute(f"UPDATE {t} SET nodes=? WHERE {c}=?", (json.dumps(nodes), eid))
    conn.commit()
    conn.close()

    log(f"Waiting 25s for n8n to restart...")
    subprocess.run(["docker", "compose", "restart", "n8n"], capture_output=True, cwd=REPO_ROOT)
    time.sleep(25)

    # Verify n8n health
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:5678/healthz", timeout=5)
        log("n8n healthy")
    except Exception:
        log("WARNING: n8n health check failed")


def warmup():
    import urllib.request
    log("Warming up...")
    data = json.dumps({"message": "hola", "chat_id": "warmup-e2e-suite"}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/frontend/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=180)
    log("Warmup done")


def run_pytest(test_label: str, test_path: str, model: str, iterations: int,
               extra_args: list = None) -> bool:
    extra_args = extra_args or []
    cmd = [
        VENV_PYTHON, "-m", "pytest",
        test_path,
        "--e2e", f"--model={model}", f"--iterations={iterations}",
        "-v", "--tb=line", "-s",
    ] + extra_args

    log(f"  Starting: {test_label} ({iterations} iter)")
    t0 = time.time()
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, cwd=REPO_ROOT, env=env,
    )
    stdout, _ = proc.communicate()

    # Write test output to log
    with open(LOG_FILE, "a") as f:
        f.write(f"--- {test_label} output ---\n")
        f.write(stdout[-2000:])  # last 2000 chars
        f.write(f"--- end {test_label} ---\n")

    elapsed = time.time() - t0
    ok = proc.returncode == 0
    status = "OK" if ok else f"FAILED (rc={proc.returncode})"
    log(f"  Finished: {test_label} in {elapsed:.0f}s → {status}")
    return ok


def main():
    with open(LOG_FILE, "w") as f:
        f.write(f"=== E2E multi-model run started at {datetime.now()} ===\n\n")

    total_start = time.time()
    passed = 0
    failed = 0

    for model_entry in MODELS:
        model_name = model_entry["name"]
        log(f"\n{'='*60}")
        log(f"MODEL: {model_name}")
        log(f"{'='*60}")

        # Switch model
        log(f"Switching n8n to {model_name}...")
        switch_n8n_model(model_name)

        # Warmup
        warmup()

        # Run tests
        for test_label, test_path in model_entry["tests"]:
            iters = LATENCY_ITERATIONS if "latency" in test_label else ITERATIONS
            ok = run_pytest(test_label, test_path, model_name, iters)
            if ok:
                passed += 1
            else:
                failed += 1
                log(f"  WARNING: {test_label} for {model_name} failed, continuing...")

    total_elapsed = time.time() - total_start
    log(f"\n{'='*60}")
    log(f"DONE in {total_elapsed/60:.1f} min — {passed} passed, {failed} failed")
    log(f"{'='*60}")
    log("Now run: python3 scripts/generate_e2e_report.py")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
