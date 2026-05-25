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
)
from services import chat_service
from services.action_log import ActionLog
from services.settings_service import SettingsService
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
            SELECT cm.session_id, cm.content
            FROM chat_messages cm
            WHERE cm.id IN (
                SELECT MIN(id) FROM chat_messages GROUP BY session_id
            )
            ORDER BY cm.id DESC
        """)
        results = await rows.fetchall()

    chats = []
    for session_id, first_msg in results:
        title = first_msg[:40] + ("..." if len(first_msg) > 40 else "")
        async with await _pg_conn() as conn:
            count_row = await conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE session_id = %s",
                [session_id],
            )
            count = (await count_row.fetchone())[0]
        chats.append(ChatListItem(id=session_id, title=title, message_count=count))

    return ChatListResponse(chats=chats)


@router.post("/chats", response_model=NewChatResponse)
async def create_chat():
    chat_id = str(uuid.uuid4())
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


@router.get("/languages")
async def get_languages():
    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "languages.json")
    with open(config_path) as f:
        return json.load(f)
