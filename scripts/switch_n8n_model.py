#!/usr/bin/env python3
"""
Cambia el modelo Ollama en todos los workflows activos de n8n.

Edita la base de datos SQLite de n8n para cambiar el campo 'model' de
todos los nodos Ollama Chat Model (lmChatOllama) en workflows activos.
Genera nuevas entradas en workflow_history + workflow_publish_history
para que /webhook use la configuracion actualizada.

Uso:
  python3 scripts/switch_n8n_model.py qwen2.5:3b
  python3 scripts/switch_n8n_model.py llama3.2:latest
  python3 scripts/switch_n8n_model.py --restore
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime


N8N_DB = os.path.expanduser("~/iarvis/iarvis/n8n/database.sqlite")
BACKUP_FILE = os.path.expanduser("~/.iarvis_n8n_model_backup.json")
DEFAULT_MODEL = "qwen2.5:3b"


def _ollama_node_types():
    return [
        "@n8n/n8n-nodes-langchain.lmChatOllama",
        "@n8n/n8n-nodes-langchain.lmOllama",
    ]


def _is_ollama_node(node: dict) -> bool:
    return node.get("type") in _ollama_node_types()


def _now_ts() -> str:
    """n8n datetime format: YYYY-MM-DD HH:MM:SS.fff"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _read_workflows() -> list[dict]:
    """Lee workflows activos con nodos, conexiones y datos de publicacion."""
    conn = sqlite3.connect(N8N_DB)
    workflows = []
    for row in conn.execute(
        "SELECT id, name, nodes, connections, versionId FROM workflow_entity WHERE active=1"
    ):
        wf = {
            "id": row[0],
            "name": row[1],
            "nodes": json.loads(row[2]),
            "connections": json.loads(row[3]),
            "versionId": row[4],
        }
        # Obtener authors del workflow_history mas reciente para este workflow
        cur = conn.execute(
            "SELECT authors FROM workflow_history WHERE workflowId = ? ORDER BY versionId DESC LIMIT 1",
            (wf["id"],),
        )
        row2 = cur.fetchone()
        wf["authors"] = row2[0] if row2 else "Eloy Gonzalez"
        workflows.append(wf)
    conn.close()
    return workflows


def _publish_workflow(wf: dict, new_version_id: str):
    """Inserta en workflow_history y workflow_publish_history."""
    conn = sqlite3.connect(N8N_DB)
    now = _now_ts()

    # Actualizar draft (workflow_entity)
    conn.execute(
        "UPDATE workflow_entity SET nodes = ?, connections = ?, versionId = ?, updatedAt = ? WHERE id = ?",
        (json.dumps(wf["nodes"]), json.dumps(wf["connections"]), new_version_id, now, wf["id"]),
    )

    # Crear snapshot en workflow_history
    conn.execute(
        "INSERT INTO workflow_history (versionId, workflowId, authors, nodes, connections, name, autosaved) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        (
            new_version_id,
            wf["id"],
            wf["authors"],
            json.dumps(wf["nodes"]),
            json.dumps(wf["connections"]),
            wf["name"],
        ),
    )

    # Activar la nueva version (esto es lo que /webhook lee)
    conn.execute(
        "INSERT INTO workflow_publish_history (workflowId, versionId, event, createdAt) "
        "VALUES (?, ?, 'activated', ?)",
        (wf["id"], new_version_id, now),
    )

    conn.commit()
    conn.close()


def _save_backup(workflows: list[dict]):
    """Guarda los modelos originales para poder restaurar."""
    backup = {}
    for wf in workflows:
        models = []
        for node in wf["nodes"]:
            if _is_ollama_node(node):
                models.append(node.get("parameters", {}).get("model", ""))
        backup[wf["name"]] = {
            "id": wf["id"],
            "models": models,
        }
    with open(BACKUP_FILE, "w") as f:
        json.dump(backup, f, indent=2)
    print(f"Backup saved: {BACKUP_FILE}")


def switch_model(model_name: str):
    """Cambia todos los nodos Ollama al modelo especificado."""
    workflows = _read_workflows()
    if not workflows:
        print("No active workflows found in n8n SQLite")
        sys.exit(1)

    if not os.path.exists(BACKUP_FILE):
        _save_backup(workflows)

    changed_count = 0
    for wf in workflows:
        has_ollama = False
        for node in wf["nodes"]:
            if _is_ollama_node(node):
                old = node.get("parameters", {}).get("model", "?")
                node["parameters"]["model"] = model_name
                print(f"  {wf['name']}: {node['name']} -> {model_name} (was {old})")
                has_ollama = True
        if has_ollama:
            new_vid = str(uuid.uuid4())
            _publish_workflow(wf, new_vid)
            changed_count += 1

    if changed_count == 0:
        print("No Ollama nodes found to change")
        sys.exit(1)

    print(f"\nSwitched to {model_name} in {changed_count} workflow(s)")
    print("Restart n8n to apply: docker compose restart n8n")


def restore_original():
    """Restaura los modelos originales desde el backup."""
    if not os.path.exists(BACKUP_FILE):
        print(f"No backup found at {BACKUP_FILE}")
        sys.exit(1)

    with open(BACKUP_FILE) as f:
        backup = json.load(f)

    for wf_name, info in backup.items():
        workflows = _read_workflows()
        wf = next((w for w in workflows if w["id"] == info["id"]), None)
        if not wf:
            print(f"  {wf_name}: not found or inactive, skipping")
            continue

        model_idx = 0
        has_changes = False
        for node in wf["nodes"]:
            if _is_ollama_node(node) and model_idx < len(info["models"]):
                target = info["models"][model_idx]
                current = node.get("parameters", {}).get("model", "?")
                if current != target:
                    node["parameters"]["model"] = target
                    print(f"  {wf_name}: {node['name']} -> {target} (was {current})")
                    has_changes = True
                model_idx += 1

        if has_changes:
            new_vid = str(uuid.uuid4())
            _publish_workflow(wf, new_vid)

    os.remove(BACKUP_FILE)
    print(f"\nRestored original models. Restart n8n: docker compose restart n8n")


def show_current():
    """Muestra los modelos actuales en los workflows activos."""
    workflows = _read_workflows()
    for wf in workflows:
        for node in wf["nodes"]:
            if _is_ollama_node(node):
                model = node.get("parameters", {}).get("model", "?")
                print(f"{wf['name']}: {node['name']} -> {model}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: switch_n8n_model.py <model_name> | --restore | --show")
        print(f"Default (restore target): {DEFAULT_MODEL}")
        show_current()
        sys.exit(0)

    arg = sys.argv[1]
    if arg == "--restore":
        restore_original()
    elif arg == "--show":
        show_current()
    else:
        switch_model(arg)
