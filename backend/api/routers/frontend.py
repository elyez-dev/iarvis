import uuid
import os
import json

from fastapi import APIRouter, HTTPException
from schemas.chat import (
    ActionDetail,
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
import psycopg

router = APIRouter(
    tags=["frontend"]
)

service = chat_service.ChatService()

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgres://n8n_user:n8n_password@postgres:5432/chat_history")


async def _pg_conn():
    return await psycopg.AsyncConnection.connect(POSTGRES_URL, autocommit=True)


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

    if result.chat_id:
        try:
            async with await _pg_conn() as conn:
                await conn.execute(
                    "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
                    [result.chat_id, "user", request.message],
                )
                await conn.execute(
                    "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
                    [result.chat_id, "assistant", result.response],
                )
                row = await conn.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE session_id = %s",
                    [result.chat_id],
                )
                count = (await row.fetchone())[0]
                if count == 2:
                    title = request.message[:40] + ("..." if len(request.message) > 40 else "")
                    await conn.execute(
                        "UPDATE chats SET title = %s WHERE session_id = %s AND title = 'New Chat'",
                        [title, result.chat_id],
                    )
        except Exception:
            pass

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
    async with await _pg_conn() as conn:
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

    chats = [
        ChatListItem(id=session_id, title=title, message_count=count)
        for session_id, title, count in results
    ]
    return ChatListResponse(chats=chats)


@router.post("/chats", response_model=NewChatResponse)
async def create_chat():
    chat_id = str(uuid.uuid4())
    async with await _pg_conn() as conn:
        await conn.execute(
            "INSERT INTO chats (session_id, title) VALUES (%s, %s) ON CONFLICT (session_id) DO NOTHING",
            [chat_id, "New Chat"],
        )
    return NewChatResponse(chat_id=chat_id)


@router.get("/chats/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    async with await _pg_conn() as conn:
        rows = await conn.execute(
            "SELECT role, content FROM chat_messages WHERE session_id = %s ORDER BY id",
            [session_id],
        )
        results = await rows.fetchall()

    messages = [
        ChatHistoryMessage(role=role, content=content)
        for role, content in results
    ]

    return ChatHistoryResponse(session_id=session_id, messages=messages)


@router.put("/chats/{session_id}")
async def update_chat_title(session_id: str, body: ChatUpdateRequest):
    async with await _pg_conn() as conn:
        await conn.execute(
            "UPDATE chats SET title = %s WHERE session_id = %s",
            [body.title, session_id],
        )
    return {"session_id": session_id, "title": body.title}


@router.delete("/chats/{session_id}", response_model=ChatDeleteResponse)
async def delete_chat(session_id: str):
    async with await _pg_conn() as conn:
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
    return ChatDeleteResponse(deleted=session_id, detail="Chat and all messages deleted")


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
