from fastapi import APIRouter, HTTPException
from schemas.chat import ChatRequest, ChatResponse
from services import chat_service
import httpx

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
        return await service.chat(request.message, request.chat_id)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post(
    "/decision_check",
    summary="Checks the format of the string of the AI decision making process",
    description="Verifies that the AI's decision-making string is formatted correctly.",
    response_model=ChatResponse,
    responses={
        200: {"description": "Successful response"},
        400: {"description": "Bad request"},
        500: {"description": "Internal server error"}
    }
)
async def decision_check(request: ChatRequest):
    try:
        return await service.decision_check(request.message)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))