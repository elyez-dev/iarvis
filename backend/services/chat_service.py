import httpx
from core.config import settings
from schemas.chat import ChatResponse
from typing import Optional

class ChatService:
    def __init__(self):
        self.n8n_url = settings().n8n_url

    async def chat(self, message: str, chat_id: Optional[str] = None) -> ChatResponse:
        # send message to n8n and get response with httpx
        try:
            async with httpx.AsyncClient(timeout=settings().default_timeout) as client:
                payload = {"message": message}
                if chat_id:
                    payload["chat_id"] = chat_id
                
                response = await client.post(self.n8n_url+"/chat", json=payload)
                response.raise_for_status()

                # check if response is json and has the expected fields
                data = response.json()
                if "response" not in data or "chat_id" not in data:
                    raise ValueError("Invalid response from n8n: missing 'response' or 'chat_id' fields")
                
                return ChatResponse(response=data["response"], chat_id=data["chat_id"])
        except httpx.RequestError as e:
            error_type = type(e).__name__
            raise ValueError(f"n8n request failed ({error_type}): {str(e)}")