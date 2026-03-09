import httpx
import asyncio
from core import config
from core.user_settings import user_settings
from schemas.chat import ChatResponse
from services.translation_service import translator, NLLB_LANG_MAP
from schemas.chat import ChatResponse, DecisionCheckResponse
from typing import Optional

class ChatService:
    def __init__(self):
        self.n8n_url = config.settings().n8n_url
        self.user_settings = user_settings().settings

    async def _send_to_n8n(self, message: str, chat_id: Optional[str] = None) -> dict:
        """Send message to n8n and return response data"""
        async with httpx.AsyncClient(timeout=config.settings().default_timeout) as client:
            payload = {"message": message, "settings": self.user_settings}
            if chat_id:
                payload["chat_id"] = chat_id
            
            response = await client.post(self.n8n_url+"/chat", json=payload)
            response.raise_for_status()

            data = response.json()
            if "response" not in data or "chat_id" not in data:
                raise ValueError("Invalid response from n8n: missing 'response' or 'chat_id' fields")
            return data
        

    async def chat(self, message: str, chat_id: Optional[str] = None) -> ChatResponse:
        try:
            language_code = self.user_settings.get("language_code", "es")
            
            # If user speaks English, skip translation
            if language_code == "en":
                data = await self._send_to_n8n(message, chat_id)
                return ChatResponse(response=data["response"], chat_id=data["chat_id"])
            
            # Translate input: User language -> English
            nllb_user_lang = NLLB_LANG_MAP.get(language_code, "spa_Latn")
            nllb_eng = "eng_Latn"
            
            message_en = await asyncio.to_thread(
                translator.translate, 
                text=message, 
                src_lang=nllb_user_lang, 
                tgt_lang=nllb_eng
            )
            print(f"[Traductor IN] {language_code}: '{message}' -> en: '{message_en}'")

            # Send to n8n
            data = await self._send_to_n8n(message_en, chat_id)
            
            # Translate output: English -> User language
            response_translated = await asyncio.to_thread(
                translator.translate, 
                text=data["response"], 
                src_lang=nllb_eng, 
                tgt_lang=nllb_user_lang
            )
            print(f"[Traductor OUT] en: '{data['response']}' -> {language_code}: '{response_translated}'")

            return ChatResponse(response=response_translated, chat_id=data["chat_id"])

        except httpx.RequestError as e:
            error_type = type(e).__name__
            raise ValueError(f"n8n request failed ({error_type}): {str(e)}")

    async def decision_check(self, keywords_str: str, tries: Optional[int] = None) -> DecisionCheckResponse:
        """
        Validate keywords string and return decision flags.
        Keywords should be comma-separated: "SEARCH,STORE" or "NONE"
        Valid keywords: STORE, SEARCH, TOOL, NONE.
        NONE must be sent alone, other keywords can be combined.
        """
        # Parse comma-separated string and clean up whitespace
        keywords = [kw.strip().upper() for kw in keywords_str.split(",") if kw.strip()]
        
        valid_keywords = {"STORE", "SEARCH", "TOOL", "NONE"}
        
        # Validate all keywords are valid
        if not all(kw in valid_keywords for kw in keywords):
            raise ValueError(f"Invalid keywords. Must be one of: {valid_keywords}")
        
        # NONE must be alone
        if "NONE" in keywords and len(keywords) > 1:
            raise ValueError("NONE keyword must be sent alone")
        
        # If NONE, return all False
        if "NONE" in keywords:
            return DecisionCheckResponse(search=False, store=False, tool=False)
        
        # Otherwise, return True for each keyword present
        return DecisionCheckResponse(
            search="SEARCH" in keywords,
            store="STORE" in keywords,
            tool="TOOL" in keywords
        )
        