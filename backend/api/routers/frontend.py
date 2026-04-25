from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from schemas.chat import ChatRequest, ChatResponse, DecisionCheckResponse
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

