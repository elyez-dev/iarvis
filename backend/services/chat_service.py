import httpx
import json
import asyncio
import logging
import uuid
import psycopg
from core import config
from core.database import POSTGRES_URL
from core.user_settings import user_settings
from services.translation_service import translator, NLLB_LANG_MAP
from schemas.chat import ActionDetail, ChatResponse, DecisionCheckResponse
from services.action_log import ActionLog
from typing import Optional


logger = logging.getLogger(__name__)

def _normalize_casing_for_translation(text: str, threshold: float = 0.8) -> str:
    """NLLB rinde fatal con texto todo en mayúsculas (sesgo del corpus de
    entrenamiento; "HOLA" se tokeniza con subpalabras raras y el decoder
    se descarrila).

    Heurística: si más del `threshold` de las letras son mayúsculas,
    consideramos que el usuario está gritando y pasamos a minúsculas
    antes de traducir. El umbral por defecto (0.8) deja pasar frases
    normales con acrónimos legítimos (NASA, ONU, IBM) sin tocar.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return text
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    return text.lower() if upper_ratio > threshold else text


class ChatService:
    def __init__(self):
        self.n8n_url = config.settings().n8n_url
        self.timeout = config.settings().default_timeout
        self._action_log = ActionLog.instance()

    def _fresh_settings(self) -> dict:
        """Read current user settings from disk (not cached) so language/name/tone
        changes take effect without restart."""
        return user_settings().settings

    async def _sync_action_details(self, chat_id: Optional[str]) -> list[ActionDetail]:
        """Pop any action entries that arrived synchronously during the n8n call.
        SEARCH (librarian) is synchronous — its results are ready when the webhook
        returns. STORE/TOOL may also be ready by luck. Remaining ones arrive via SSE."""
        if not chat_id:
            return []
        entries = await self._action_log.pop(chat_id)
        return [
            ActionDetail(type=e.action_type, summary=e.summary, detail=e.detail)
            for e in entries
        ]

    async def _send_to_n8n(self, message: str, chat_id: Optional[str] = None) -> dict:
        """Send message to n8n and return response data."""
        payload = {"message": message, "settings": self._fresh_settings()}
        if chat_id:
            payload["chat_id"] = chat_id
            # Discard stale ActionLog entries from previous messages in this chat
            await self._action_log.discard(chat_id)

        url = f"{self.n8n_url.rstrip('/')}/chat"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                logger.info("Sending chat request to n8n: url=%s", url)
                response = await client.post(url, json=payload)
                response.raise_for_status()

                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Invalid response from n8n: expected a JSON object")

                if "response" not in data or "chat_id" not in data:
                    raise ValueError(
                        "Invalid response from n8n: missing 'response' or 'chat_id' fields "
                        f"(keys={list(data.keys())})"
                    )
                return data
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                logger.error("n8n chat call failed for url=%s error=%s", url, exc)
                raise ValueError(f"n8n chat request failed: {exc}") from exc

    async def chat(self, message: str, chat_id: Optional[str] = None) -> ChatResponse:
        try:
            language_code = self._fresh_settings().get("language_code", "es")
            logger.info("[Chat] language_code=%r user_msg_start=%r", language_code, message[:80])

            if language_code == "en":
                logger.info("[Chat] skipping translation (English)")
                data = await self._send_to_n8n(message, chat_id)
                action_details = await self._sync_action_details(chat_id)
                response_text = data["response"]
                response_chat_id = data["chat_id"]
            else:
                nllb_user_lang = NLLB_LANG_MAP.get(language_code, "spa_Latn")
                nllb_eng = "eng_Latn"

                message_to_translate = _normalize_casing_for_translation(message)
                if message_to_translate != message:
                    logger.info("[Normalize] casing shouted -> lowercased: %r -> %r", message, message_to_translate)

                message_en = await asyncio.to_thread(
                    translator.translate,
                    text=message_to_translate,
                    src_lang=nllb_user_lang,
                    tgt_lang=nllb_eng,
                )
                logger.info("[Traductor IN] %s: %r -> en: %r", language_code, message_to_translate, message_en)

                data = await self._send_to_n8n(message_en, chat_id)

                response_translated = await asyncio.to_thread(
                    translator.translate,
                    text=data["response"],
                    src_lang=nllb_eng,
                    tgt_lang=nllb_user_lang,
                )
                logger.info("[Traductor OUT] en: %r -> %s: %r", data["response"], language_code, response_translated)

                response_text = response_translated
                response_chat_id = data["chat_id"]
                action_details = await self._sync_action_details(chat_id)

            if response_chat_id:
                try:
                    await self._persist_messages(response_chat_id, message, response_text)
                except Exception:
                    pass

            return ChatResponse(
                response=response_text,
                chat_id=response_chat_id,
                action_details=action_details,
            )

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            error_type = type(e).__name__
            raise ValueError(f"n8n request failed ({error_type}): {str(e)}")

    async def list_chats(self) -> list[dict]:
        async with await psycopg.AsyncConnection.connect(
            POSTGRES_URL, autocommit=True
        ) as conn:
            rows = await conn.execute("""
                SELECT
                    ch.session_id,
                    ch.title,
                    COUNT(cm.id) as message_count
                FROM chats ch
                LEFT JOIN chat_messages cm ON cm.session_id = ch.session_id
                GROUP BY ch.session_id, ch.title
                ORDER BY ch.created_at DESC
            """)
            results = await rows.fetchall()
        return [
            {"id": sid, "title": title, "message_count": count}
            for sid, title, count in results
        ]

    async def create_chat(self) -> str:
        chat_id = str(uuid.uuid4())
        async with await psycopg.AsyncConnection.connect(
            POSTGRES_URL, autocommit=True
        ) as conn:
            await conn.execute(
                "INSERT INTO chats (session_id, title) VALUES (%s, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                [chat_id, "New Chat"],
            )
        return chat_id

    async def get_chat_history(self, session_id: str) -> list[dict]:
        async with await psycopg.AsyncConnection.connect(
            POSTGRES_URL, autocommit=True
        ) as conn:
            rows = await conn.execute(
                "SELECT role, content FROM chat_messages "
                "WHERE session_id = %s ORDER BY id",
                [session_id],
            )
            results = await rows.fetchall()
        return [{"role": role, "content": content} for role, content in results]

    async def update_chat_title(self, session_id: str, title: str) -> dict:
        async with await psycopg.AsyncConnection.connect(
            POSTGRES_URL, autocommit=True
        ) as conn:
            await conn.execute(
                "UPDATE chats SET title = %s WHERE session_id = %s",
                [title, session_id],
            )
        return {"session_id": session_id, "title": title}

    async def delete_chat(self, session_id: str) -> dict:
        async with await psycopg.AsyncConnection.connect(
            POSTGRES_URL, autocommit=True
        ) as conn:
            await conn.execute(
                "DELETE FROM chat_messages WHERE session_id = %s",
                [session_id],
            )
            await conn.execute(
                "DELETE FROM n8n_chat_histories WHERE session_id = %s",
                [session_id],
            )
            await conn.execute(
                "DELETE FROM chats WHERE session_id = %s",
                [session_id],
            )
        return {"deleted": session_id, "detail": "Chat and all messages deleted"}

    async def _persist_messages(
        self, chat_id: str, user_msg: str, assistant_msg: str
    ) -> None:
        async with await psycopg.AsyncConnection.connect(
            POSTGRES_URL, autocommit=True
        ) as conn:
            await conn.execute(
                "INSERT INTO chat_messages (session_id, role, content) "
                "VALUES (%s, %s, %s)",
                [chat_id, "user", user_msg],
            )
            await conn.execute(
                "INSERT INTO chat_messages (session_id, role, content) "
                "VALUES (%s, %s, %s)",
                [chat_id, "assistant", assistant_msg],
            )
            row = await conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE session_id = %s",
                [chat_id],
            )
            count = (await row.fetchone())[0]
            if count == 2:
                title = user_msg[:40] + ("..." if len(user_msg) > 40 else "")
                await conn.execute(
                    "UPDATE chats SET title = %s "
                    "WHERE session_id = %s AND title = 'New Chat'",
                    [title, chat_id],
                )

    async def decision_check(self, message: str, tries: Optional[int] = None) -> DecisionCheckResponse:
        """
        Validate the ROUTER LLM output (JSON string) and convert it into action flags.
        Expected payload: {"actions": ["SEARCH" | "STORE" | "TOOL" | "NONE", ...]}
        Rules:
          - actions must be a non-empty list of valid keywords.
          - NONE must appear alone if used.
        """
        try:
            data = json.loads(message)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ROUTER output is not valid JSON: {exc}") from exc

        if not isinstance(data, dict) or "actions" not in data:
            keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            raise ValueError(f"ROUTER JSON must contain key 'actions' (got: {keys})")

        actions = data["actions"]
        if not isinstance(actions, list) or not actions:
            raise ValueError(f"'actions' must be a non-empty list (got: {actions!r})")

        valid = {"STORE", "SEARCH", "TOOL", "NONE"}
        normalized = []
        for a in actions:
            if not isinstance(a, str):
                raise ValueError(f"Each action must be a string (got: {a!r})")
            up = a.strip().upper()
            if up not in valid:
                raise ValueError(f"Invalid action '{a}'. Must be one of: {sorted(valid)}")
            normalized.append(up)

        if "NONE" in normalized and len(set(normalized)) > 1:
            raise ValueError("NONE action must appear alone")

        if "NONE" in normalized:
            return DecisionCheckResponse(search=False, store=False, tool=False)

        return DecisionCheckResponse(
            search="SEARCH" in normalized,
            store="STORE" in normalized,
            tool="TOOL" in normalized,
        )
