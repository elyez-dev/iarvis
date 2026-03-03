from pydantic import BaseModel
from typing import Optional

class ChatRequest(BaseModel):
    message: str
    chat_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    chat_id: str