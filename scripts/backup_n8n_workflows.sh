#!/bin/bash

# ===== CONFIG =====
CONTAINER_NAME="iarvis_n8n"
BACKUP_DIR="../n8n/workflows" # local folder
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")

# ===== CREATE FOLDER IF NOT EXISTS =====
mkdir -p "$BACKUP_DIR"

echo "Exporting n8n workflows..."

# ===== EXPORT WORKFLOWS INSIDE CONTAINER =====
docker exec -t $CONTAINER_NAME \
  n8n export:workflow --all \
  --output=/home/node/workflows_$TIMESTAMP.json

# ===== COPY FILE TO HOST =====
docker cp $CONTAINER_NAME:/home/node/workflows_$TIMESTAMP.json \
  "$BACKUP_DIR/workflows_$TIMESTAMP.json"

# ===== CLEAN TEMP FILE INSIDE CONTAINER =====
docker exec -t $CONTAINER_NAME \
  rm /home/node/workflows_$TIMESTAMP.json

echo "Backup completed:"
echo "$BACKUP_DIR/workflows_$TIMESTAMP.json"