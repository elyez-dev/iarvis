#!/usr/bin/env bash
# =============================================================================
# run_e2e_tests.sh — Ejecuta la suite E2E contra un stack de test aislado.
#
# Flujo:
#   1. Para el backend de producción
#   2. Levanta stack de test (postgres_test, qdrant_test, dgraph_test, backend_test)
#   3. Espera a que el backend_test responda
#   4. Aplica schema de dgraph
#   5. Ejecuta tests E2E
#   6. Destruye el stack de test (incluyendo volúmenes)
#   7. Limpia n8n_chat_histories de producción (único dato que toca n8n)
#   8. Restaura el backend de producción
#
# Uso:
#   ./scripts/run_e2e_tests.sh [pytest args...]
#
# Ejemplos:
#   ./scripts/run_e2e_tests.sh --model=qwen2.5:3b --iterations=5
#   ./scripts/run_e2e_tests.sh --model=qwen2.5:3b --model=qwen2.5:1.5b --iterations=3 -v
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
COMPOSE_FILE="$REPO_ROOT/docker-compose.test.yml"
TEST_DIR="$REPO_ROOT/backend/tests"
N8N_CHAT_TABLE="n8n_chat_histories"
TEST_PREFIX="test_e2e_"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup_test_data_in_n8n_postgres() {
    echo -e "${YELLOW}==> Limpiando n8n_chat_histories de producción (prefijo ${TEST_PREFIX})...${NC}"
    docker exec iarvis_postgres psql -U n8n_user -d chat_history -c \
        "DELETE FROM ${N8N_CHAT_TABLE} WHERE session_id LIKE '${TEST_PREFIX}%';" \
        2>/dev/null || echo "  (no rows or postgres not reachable)"
}

# -- Paso 1: Parar y eliminar backend de producción ----------------------------
# Eliminamos el contenedor (no solo lo paramos) para liberar el hostname
# "backend" en la red Docker, asi n8n resuelve al backend_test via el alias.
echo -e "${YELLOW}==> Parando y eliminando backend de produccion...${NC}"
cd "$REPO_ROOT"
docker compose stop backend
docker compose rm -f backend

# -- Paso 2: Levantar stack de test -------------------------------------------
echo -e "${YELLOW}==> Levantando stack de test...${NC}"
docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true
docker compose -f "$COMPOSE_FILE" build backend_test
docker compose -f "$COMPOSE_FILE" up -d postgres_test qdrant_test dgraph_test mock_tool

# -- Paso 3: Esperar a que DBs estén listas -----------------------------------
echo -e "${YELLOW}==> Esperando a que los servicios de test estén listos...${NC}"
sleep 3

echo -e "${YELLOW}==> Levantando backend_test...${NC}"
docker compose -f "$COMPOSE_FILE" up -d backend_test

# Esperar a que el backend responda
echo -n "  Esperando backend_test en http://localhost:8000 ..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/frontend/settings > /dev/null 2>&1; then
        echo " OK"
        break
    fi
    sleep 2
    echo -n "."
done

# -- Paso 4: Aplicar schema de dgraph -----------------------------------------
echo -e "${YELLOW}==> Aplicando schema de dgraph...${NC}"
docker cp "$REPO_ROOT/scripts/init_dgraph_schema.py" iarvis_backend_test:/tmp/init_schema.py 2>/dev/null || true
docker exec iarvis_backend_test python /tmp/init_schema.py 2>/dev/null || \
    echo "  (dgraph schema script not available or already applied, continuing)"

# -- Paso 5: Ejecutar tests ---------------------------------------------------
echo -e "${YELLOW}==> Ejecutando tests E2E...${NC}"
cd "$REPO_ROOT"
PYTHONPATH=backend "$VENV_PYTHON" -m pytest "$TEST_DIR/e2e/" \
    --e2e "$@" \
    -v --tb=short

TEST_EXIT_CODE=$?

# -- Paso 6: Destruir stack de test -------------------------------------------
echo -e "${YELLOW}==> Destruyendo stack de test...${NC}"
docker compose -f "$COMPOSE_FILE" down -v

# -- Paso 7: Limpiar n8n_chat_histories ---------------------------------------
cleanup_test_data_in_n8n_postgres

# -- Paso 8: Restaurar backend de producción ----------------------------------
echo -e "${YELLOW}==> Restaurando backend de produccion...${NC}"
docker compose up -d backend

# -- Resultado ----------------------------------------------------------------
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}==> Tests E2E completados con éxito.${NC}"
else
    echo -e "${RED}==> Tests E2E fallaron (exit code $TEST_EXIT_CODE).${NC}"
fi
exit $TEST_EXIT_CODE
