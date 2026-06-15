from pydantic import BaseModel, Field
from typing import List, Optional


class TranslateRequest(BaseModel):
    text: str
    src_lang: str = "eng_Latn"
    tgt_lang: str
    is_light_or_dark: bool = False


class TranslateResponse(BaseModel):
    translation: str


class ActionDetail(BaseModel):
    type: str = Field(..., example="STORE")
    summary: str = Field(..., example="The user likes cheese.")
    detail: Optional[str] = Field(None, example="User -[likes]-> cheese")


class ChatRequest(BaseModel):
    message: str = Field(..., example="Hello!")
    chat_id: Optional[str] = Field(None, example="1")
    tries: Optional[int] = Field(0)


class ChatResponse(BaseModel):
    response: str = Field(..., example="Hi there! How can I assist you today?")
    chat_id: Optional[str] = Field(None, example="1")
    action_details: List[ActionDetail] = Field(
        default_factory=list,
        description="SEARCH results available synchronously; STORE/TOOL arrive via polling",
    )


class ActionsResponse(BaseModel):
    notifications: List[ActionDetail] = Field(default_factory=list)


class DecisionCheckResponse(BaseModel):
    search: bool = Field(..., example=True)
    store: bool = Field(..., example=False)
    tool: bool = Field(..., example=False)


class SettingsUpdate(BaseModel):
    key: str
    value: str


class ChatListItem(BaseModel):
    id: str
    title: str
    message_count: int


class ChatListResponse(BaseModel):
    chats: list[ChatListItem]


class ChatHistoryMessage(BaseModel):
    role: str
    content: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatHistoryMessage]


class NewChatResponse(BaseModel):
    chat_id: str


class ChatUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class ChatDeleteResponse(BaseModel):
    deleted: str
    detail: str


class DeleteMemoryResponse(BaseModel):
    deleted: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)