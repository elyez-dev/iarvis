from fastapi import APIRouter
from fastapi.responses import JSONResponse
import logging
from schemas.chat import ChatRequest
from schemas.memory import ArchivistQueryResponse, LibrarianQueryResponse
from services import chat_service, memory_service
import httpx

from api.routes import TrackedValidationRoute
from schemas.chat import DecisionCheckResponse


logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["n8n"]
)
tracked_router = APIRouter(route_class=TrackedValidationRoute)

chatService = chat_service.ChatService()
memoryService = memory_service.MemoryService()

# endpoint for n8n to check the AI's decision-making string format
# use tracked_router to get the tries counter in case of validation errors
@tracked_router.post(
    "/decision_check",
    summary="Checks the ROUTER AI response format",
    description="Verifies that the AI's decision-making string is formatted correctly.",
    response_model=DecisionCheckResponse,
    responses={
        200: {"description": "Correct format"},
        400: {"description": "Bad request"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"}
    }
)
async def decision_check(request: ChatRequest):
    try:
        return await chatService.decision_check(request.message, request.tries)
    except ValueError as e:
        next_tries = (request.tries or 0) + 1
        return JSONResponse(
            status_code=400,
            content={"detail": str(e), "tries": next_tries}
        )
    except Exception as e:
        next_tries = (request.tries or 0) + 1
        return JSONResponse(
            status_code=500,
            content={"detail": str(e), "tries": next_tries}
        )
    
# endpoint for n8n to check the librarian database query format and return results
@tracked_router.post(
    "/librarian_query",
    summary="Checks the librarian database query format and returns results",
    description="Verifies that the AI's database query is formatted correctly and returns mock results.",
    response_model=LibrarianQueryResponse,
    responses={
        200: {"description": "Query executed successfully"},
        400: {"description": "Bad request"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"}
    }
)
async def librarian_query(request: ChatRequest):
    try:
        return await memoryService.librarian_query(request.message)
    except ValueError as e:
        next_tries = (request.tries or 0) + 1
        logger.warning("Librarian query validation/runtime error: %s", e)
        return JSONResponse(
            status_code=400,
            content={"detail": str(e), "tries": next_tries}
        )
    except Exception as e:
        next_tries = (request.tries or 0) + 1
        logger.exception("Unexpected librarian_query error")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e), "tries": next_tries}
        )


@tracked_router.post(
    "/archivist_query",
    summary="Checks and stores archivist memory payload",
    description="Parses AI archivist JSON from message and stores it in Qdrant.",
    response_model=ArchivistQueryResponse,
    responses={
        200: {"description": "Memory stored successfully"},
        400: {"description": "Bad request"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"}
    }
)
async def archivist_query(request: ChatRequest):
    try:
        return await memoryService.archivist_query(request.message)
    except ValueError as e:
        next_tries = (request.tries or 0) + 1
        logger.warning("Archivist query validation/runtime error: %s", e)
        return JSONResponse(
            status_code=400,
            content={"detail": str(e), "tries": next_tries}
        )
    except Exception as e:
        next_tries = (request.tries or 0) + 1
        logger.exception("Unexpected archivist_query error")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e), "tries": next_tries}
        )

router.include_router(tracked_router, tags=["n8n"])