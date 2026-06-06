"""
Utilidades minimas para tests E2E.

El aislamiento de bases de datos lo proporciona el stack de test
(docker-compose.test.yml). Este modulo solo proporciona:
  - build_test_session_id(): genera IDs con prefijo test_e2e_
  - cleanup_postgres_test_data(): limpia n8n_chat_histories de produccion
    (n8n es compartido con produccion, unica fuga de datos controlada)
"""

import uuid
import logging
import subprocess

logger = logging.getLogger(__name__)
TEST_SESSION_PREFIX = "test_e2e_"


def build_test_session_id() -> str:
    return f"{TEST_SESSION_PREFIX}{uuid.uuid4().hex[:16]}"


def cleanup_postgres_test_data(postgres_url: str = None) -> None:
    """Borra sesiones test_e2e_ de n8n_chat_histories en produccion.

    n8n usa la Postgres de produccion para su chat memory (no se puede
    cambiar sin editar el workflow). Esta funcion limpia solo las filas
    con session_id que empiezan por test_e2e_.

    Intenta psycopg primero; si no, usa docker exec como fallback.
    """
    import os

    # Metodo 1: psycopg
    url = postgres_url or os.getenv("POSTGRES_URL", "")
    if url:
        try:
            import psycopg
            conn = psycopg.connect(url)
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM n8n_chat_histories WHERE session_id LIKE %s",
                    (f"{TEST_SESSION_PREFIX}%",),
                )
            conn.commit()
            conn.close()
            logger.info("PostgreSQL n8n_chat_histories cleaned via psycopg")
            return
        except Exception as e:
            logger.warning("psycopg cleanup failed (%s), trying docker exec", e)

    # Metodo 2: docker exec (fallback)
    sql = f"DELETE FROM n8n_chat_histories WHERE session_id LIKE '{TEST_SESSION_PREFIX}%';"
    result = subprocess.run(
        ["docker", "exec", "iarvis_postgres", "psql",
         "-U", "n8n_user", "-d", "chat_history", "-c", sql],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        logger.info("PostgreSQL n8n_chat_histories cleaned via docker exec")
    else:
        logger.warning("docker exec cleanup failed: %s", result.stderr[:200])
