#!/bin/bash

# Backup n8n workflows to <repo>/workflows/
# Robust to cwd: resolves paths relative to this script, not the caller.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$REPO_ROOT/workflows"

CONTAINER_NAME="${N8N_CONTAINER_NAME:-iarvis_n8n}"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="$BACKUP_DIR/workflows_$TIMESTAMP.json"

mkdir -p "$BACKUP_DIR"

echo "Exporting n8n workflows from container '$CONTAINER_NAME'..."

docker exec -t "$CONTAINER_NAME" \
  n8n export:workflow --all \
  --output="/home/node/workflows_$TIMESTAMP.json"

docker cp "$CONTAINER_NAME:/home/node/workflows_$TIMESTAMP.json" "$BACKUP_FILE"

docker exec -t "$CONTAINER_NAME" \
  rm "/home/node/workflows_$TIMESTAMP.json"

echo "Backup completed:"
echo "  $BACKUP_FILE"
