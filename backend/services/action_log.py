import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ActionEntry:
    chat_id: str
    action_type: str  # "STORE", "SEARCH", "TOOL"
    summary: str
    detail: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class ActionLog:
    """
    In-process log that tracks action results during a chat request.
    n8n's subflows call /n8n/archivist_query, /n8n/librarian_query,
    /n8n/execute_tool — each of those writes its result here keyed by chat_id.

    Two consumption patterns:
    - pop(): destructive, used by chat_service._sync_action_details for
      synchronous SEARCH results included in ChatResponse.
    - peek()/ack(): non-destructive then confirm, used by the frontend
      polling endpoint for async STORE/TOOL results.
    """

    _instance: Optional["ActionLog"] = None

    def __init__(self):
        self._entries: dict[str, list[ActionEntry]] = {}
        self._ack_index: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> "ActionLog":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def add(
        self,
        chat_id: str,
        action_type: str,
        summary: str,
        detail: Optional[str] = None,
    ) -> None:
        async with self._lock:
            entry = ActionEntry(
                chat_id=chat_id,
                action_type=action_type,
                summary=summary,
                detail=detail,
            )
            self._entries.setdefault(chat_id, []).append(entry)
            logger.info(
                "ActionLog: recorded %s for chat_id=%s summary=%r",
                action_type,
                chat_id,
                summary[:80],
            )

    async def pop(self, chat_id: str) -> list[ActionEntry]:
        async with self._lock:
            self._ack_index.pop(chat_id, None)
            return self._entries.pop(chat_id, [])

    async def peek(self, chat_id: str) -> list[ActionEntry]:
        async with self._lock:
            idx = self._ack_index.get(chat_id, 0)
            all_entries = self._entries.get(chat_id, [])
            return list(all_entries[idx:])

    async def ack(self, chat_id: str, count: int) -> None:
        async with self._lock:
            all_entries = self._entries.get(chat_id, [])
            new_idx = min(self._ack_index.get(chat_id, 0) + count, len(all_entries))
            self._ack_index[chat_id] = new_idx
            if new_idx >= len(all_entries):
                self._entries.pop(chat_id, None)
                self._ack_index.pop(chat_id, None)

    async def discard(self, chat_id: str) -> None:
        async with self._lock:
            self._entries.pop(chat_id, None)
            self._ack_index.pop(chat_id, None)
