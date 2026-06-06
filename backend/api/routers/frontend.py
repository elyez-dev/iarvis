import os
import json

from fastapi import APIRouter, HTTPException
from schemas.chat import (
    ActionsResponse,
    ChatRequest,
    ChatResponse,
    SettingsUpdate,
    ChatListItem,
    ChatListResponse,
    ChatHistoryMessage,
    ChatHistoryResponse,
    NewChatResponse,
    ChatUpdateRequest,
    ChatDeleteResponse,
    DeleteMemoryResponse,
    TranslateRequest,
    TranslateResponse,
)
from services import chat_service
from services.action_log import ActionLog
from services.settings_service import SettingsService
from services.memory_deletion_service import MemoryDeletionService
from services.translation_service import get_translator

router = APIRouter(
    tags=["frontend"]
)

service = chat_service.ChatService()


@router.post(
    "/chat",
    summary="Chat with the assistant",
    description="Send a message to the assistant and receive a response.",
    response_model=ChatResponse,
    responses={
        200: {"description": "Successful response"},
        400: {"description": "Bad request"},
        500: {"description": "Internal server error"}
    }
)
async def chat(request: ChatRequest):
    try:
        result = await service.chat(request.message, request.chat_id)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return result


@router.get("/settings")
async def get_settings():
    s = SettingsService()
    return s.get_settings()


@router.put("/settings")
async def update_settings(body: SettingsUpdate):
    s = SettingsService()
    return s.update_setting(body.key, body.value)


@router.get("/chats", response_model=ChatListResponse)
async def list_chats():
    chats = await service.list_chats()
    return ChatListResponse(
        chats=[
            ChatListItem(id=c["id"], title=c["title"], message_count=c["message_count"])
            for c in chats
        ]
    )


@router.post("/chats", response_model=NewChatResponse)
async def create_chat():
    chat_id = await service.create_chat()
    return NewChatResponse(chat_id=chat_id)


@router.get("/chats/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    messages = await service.get_chat_history(session_id)
    return ChatHistoryResponse(
        session_id=session_id,
        messages=[
            ChatHistoryMessage(role=m["role"], content=m["content"])
            for m in messages
        ],
    )


@router.put("/chats/{session_id}")
async def update_chat_title(session_id: str, body: ChatUpdateRequest):
    return await service.update_chat_title(session_id, body.title)


@router.delete("/chats/{session_id}", response_model=ChatDeleteResponse)
async def delete_chat(session_id: str):
    result = await service.delete_chat(session_id)
    return ChatDeleteResponse(deleted=result["deleted"], detail=result["detail"])


@router.get("/actions/{chat_id}/pending", response_model=ActionsResponse)
async def get_pending_actions(chat_id: str):
    entries = await ActionLog.instance().peek(chat_id)
    notifications = [
        ActionDetail(
            type=e.action_type,
            summary=e.summary,
            detail=e.detail,
        )
        for e in entries
    ]
    return ActionsResponse(notifications=notifications)


@router.post("/actions/{chat_id}/ack")
async def ack_actions(chat_id: str):
    await ActionLog.instance().ack(chat_id, 999)
    return {"ok": True}


@router.delete("/memory", response_model=DeleteMemoryResponse)
async def delete_memory():
    service = MemoryDeletionService()
    return await service.delete_all()


@router.get("/languages")
async def get_languages():
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "languages.json")
    with open(config_path) as f:
        return json.load(f)


@router.post("/translate", response_model=TranslateResponse)
async def translate(body: TranslateRequest):
    import asyncio
    loop = asyncio.get_event_loop()

    def _run():
        translator = get_translator()
        text = body.text
        if body.is_light_or_dark:
            text = "light mode" if text == "light" else "dark mode"
        translation = translator.translate(text, body.src_lang, body.tgt_lang)
        if body.is_light_or_dark:
            translation = translation.replace(" mode", "").replace(" Mode", "").strip()
        return translation

    translation = await loop.run_in_executor(None, _run)
    return TranslateResponse(translation=translation)
