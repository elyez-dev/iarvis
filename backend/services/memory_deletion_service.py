import logging
import os

import psycopg

from core import config
from schemas.chat import DeleteMemoryResponse
from services.graph_service import GraphService
from services.memory_service import MemoryService


logger = logging.getLogger(__name__)

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgres://n8n_user:n8n_password@postgres:5432/chat_history",
)


class MemoryDeletionService:
    async def delete_rag(self) -> str:
        """Clear the vector database. Returns error string or ''."""
        service = MemoryService()
        return await service.delete_all_in_rag()

    async def delete_graph(self) -> str:
        """Clear the knowledge graph. Returns error string or ''."""
        try:
            service = GraphService()
            return await service.delete_all()
        except Exception as exc:
            msg = f"GraphService initialization failed: {exc}"
            logger.error("delete_graph: %s", msg)
            return msg

    async def delete_chat_history(self) -> str:
        """Truncate both chat message tables. Returns error string or ''."""
        try:
            async with await psycopg.AsyncConnection.connect(
                POSTGRES_URL, autocommit=True
            ) as conn:
                await conn.execute(
                    "TRUNCATE TABLE chat_messages, n8n_chat_histories, chats"
                )
            logger.info("delete_chat_history: both tables truncated")
            return ""
        except Exception as exc:
            msg = f"PostgreSQL truncate failed: {exc}"
            logger.error("delete_chat_history: %s", msg)
            return msg

    async def delete_all(self) -> DeleteMemoryResponse:
        deleted: list[str] = []
        errors: list[str] = []

        err = await self.delete_rag()
        if err:
            errors.append(f"RAG: {err}")
        else:
            deleted.append("rag")

        err = await self.delete_graph()
        if err:
            errors.append(f"Graph: {err}")
        else:
            deleted.append("graph")

        err = await self.delete_chat_history()
        if err:
            errors.append(f"Chat history: {err}")
        else:
            deleted.append("chat_history")

        return DeleteMemoryResponse(deleted=deleted, errors=errors)
