import json
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


def _set_request_body(request: Request, body: bytes) -> None:
    """Allow the request body to be read multiple times."""
    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    request._receive = receive


class TrackedValidationRoute(APIRoute):
    """APIRoute that adds the tries counter to validation errors."""

    tries_field = "tries"

    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request):
            body_bytes = await request.body()
            _set_request_body(request, body_bytes)
            try:
                return await original_route_handler(request)
            except RequestValidationError as exc:
                tries = self._extract_tries(request, body_bytes)
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": "Validation error",
                        "errors": exc.errors(),
                        "tries": tries + 1,
                    },
                )

        return custom_route_handler

    def _extract_tries(self, request: Request, body_bytes: bytes) -> int:
        """Best-effort extraction of the tries counter from the request."""
        tries_value = request.query_params.get(self.tries_field)
        if tries_value is not None:
            try:
                return int(tries_value)
            except (TypeError, ValueError):
                return 0

        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode() or "{}")
            except (ValueError, UnicodeDecodeError):
                return 0
            if isinstance(payload, dict):
                try:
                    return int(payload.get(self.tries_field) or 0)
                except (TypeError, ValueError):
                    return 0

        return 0
