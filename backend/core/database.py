import os
import logging

import psycopg

logger = logging.getLogger(__name__)

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgres://n8n_user:n8n_password@postgres:5432/chat_history",
)


async def init_database():
    async with await psycopg.AsyncConnection.connect(
        POSTGRES_URL, autocommit=True
    ) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(255) NOT NULL,
                role VARCHAR(10) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages(session_id, id)
        """)
    logger.info("chat_messages table ready")
