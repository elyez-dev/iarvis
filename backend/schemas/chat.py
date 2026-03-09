from pydantic import BaseModel, Field
from typing import Optional

class ChatRequest(BaseModel):
    message: str = Field(..., example="Hello!")
    chat_id: Optional[str] = Field(None, example="1")

class ChatResponse(BaseModel):
    response: str
    chat_id: Optional[str] = Field(None, example="1")