import httpx
import json
import asyncio
import logging
from core import config
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

            # If user speaks English, skip translation
            if language_code == "en":
                logger.info("[Chat] skipping translation (English)")
                data = await self._send_to_n8n(message, chat_id)
                action_details = await self._sync_action_details(chat_id)
                return ChatResponse(
                    response=data["response"],
                    chat_id=data["chat_id"],
                    action_details=action_details,
                )

            # Translate input: User language -> English
            nllb_user_lang = NLLB_LANG_MAP.get(language_code, "spa_Latn")
            nllb_eng = "eng_Latn"

            message_to_translate = _normalize_casing_for_translation(message)
            if message_to_translate != message:
                logger.info("[Normalize] casing shouted -> lowercased: %r -> %r", message, message_to_translate)

            message_en = await asyncio.to_thread(
                translator.translate,
                text=message_to_translate,
                src_lang=nllb_user_lang,
                tgt_lang=nllb_eng
            )
            logger.info("[Traductor IN] %s: %r -> en: %r", language_code, message_to_translate, message_en)

            # Send to n8n
            data = await self._send_to_n8n(message_en, chat_id)

            # Translate output: English -> User language
            response_translated = await asyncio.to_thread(
                translator.translate,
                text=data["response"],
                src_lang=nllb_eng,
                tgt_lang=nllb_user_lang
            )
            logger.info("[Traductor OUT] en: %r -> %s: %r", data["response"], language_code, response_translated)

            action_details = await self._sync_action_details(chat_id)
            return ChatResponse(
                response=response_translated,
                chat_id=data["chat_id"],
                action_details=action_details,
            )

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            error_type = type(e).__name__
            raise ValueError(f"n8n request failed ({error_type}): {str(e)}")

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
