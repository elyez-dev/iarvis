from pydantic import BaseModel, Field
from typing import Optional

class ChatRequest(BaseModel):
    message: str = Field(..., example="Hello!")
    chat_id: Optional[str] = Field(None, example="1")

class ChatResponse(BaseModel):
    response: str = Field(..., example="Hi there! How can I assist you today?")
    chat_id: Optional[str] = Field(None, example="1")

class DecisionCheckResponse(BaseModel):
    search: bool = Field(..., example=True)
    store: bool = Field(..., example=False)
    tool: bool = Field(..., example=False)