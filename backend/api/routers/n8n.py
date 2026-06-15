from fastapi import APIRouter
from fastapi.responses import JSONResponse
import logging
from schemas.chat import ChatRequest
from schemas.memory import ArchivistQueryResponse, LibrarianQueryResponse
from schemas.tools import ExecuteToolRequest, ExecuteToolResponse, ToolListResponse
from services import chat_service, memory_service, tool_service
from services.action_log import ActionLog
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
toolService = tool_service.ToolService()
action_log = ActionLog.instance()

# Tracked to include tries counter on validation errors.
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
        result = await memoryService.librarian_query(request.message)
        if request.chat_id:
            lines = []
            if result.memory_results and result.memory_results != "NONE":
                lines.append(f"**RAG:**\n{result.memory_results}")
            if result.graph_results and result.graph_results != "NONE":
                lines.append(f"**KNOWLEDGE GRAPHS:**\n{result.graph_results}")
            if lines:
                await action_log.add(request.chat_id, "SEARCH", "\n\n".join(lines))
        return result
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
        result = await memoryService.archivist_query(request.message)
        if request.chat_id:
            n8n_query = result.n8n_query
            triplets_str = ", ".join(
                f"{t.subject} -[{t.predicate}]-> {t.object}"
                for t in n8n_query.graph_triplets
            )
            summary = (
                f"**RAG:**\n{n8n_query.rag_document}\n\n"
                f"**KNOWLEDGE GRAPHS:**\n{triplets_str}"
            )
            await action_log.add(request.chat_id, "STORE", summary)
        return result
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

# --- Tool endpoints ---

@tracked_router.get(
    "/list_tools",
    summary="List available tools",
    description="Returns the catalog of available tools with their parameters.",
    response_model=ToolListResponse,
    responses={
        200: {"description": "Tool catalog returned"},
    },
)
async def list_tools():
    return toolService.list_public_tools()


@tracked_router.post(
    "/execute_tool",
    summary="Validate and execute a tool",
    description="Validates the tool_id and parameters, then calls the corresponding n8n tool webhook.",
    response_model=ExecuteToolResponse,
    responses={
        200: {"description": "Tool executed (check success field)"},
        400: {"description": "Bad request"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)
async def execute_tool(request: ExecuteToolRequest):
    try:
        result = await toolService.execute_tool(request.tool_id, request.parameters)
        if request.chat_id:
            summary = (
                f"Tool `{request.tool_id}` completed."
                if result.success
                else f"Tool `{request.tool_id}` failed: {result.error}"
            )
            await action_log.add(
                request.chat_id, "TOOL", summary,
                detail=str(result.result) if result.result else None,
            )
        return result
    except Exception as e:
        logger.exception("Unexpected execute_tool error")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)},
        )


router.include_router(tracked_router, tags=["n8n"])