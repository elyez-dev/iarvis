import json
import logging
import os
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse

import httpx

from core import config
from schemas.tools import (
    ExecuteToolResponse,
    PublicToolInfo,
    ToolListResponse,
    ToolParameter,
)

logger = logging.getLogger(__name__)

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "tools_registry.json")


def _load_registry() -> list:
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)


def _build_tool_webhook_url(webhook_path: str) -> str:
    n8n_url = config.settings().n8n_url
    parsed = urlparse(n8n_url)
    base = urlunparse(parsed._replace(path=""))
    return f"{base}/webhook/{webhook_path}"


class ToolService:

    def list_public_tools(self) -> ToolListResponse:
        tools: List[PublicToolInfo] = []
        prompt_lines: List[str] = []
        for t in _load_registry():
            params = {
                name: ToolParameter(**schema)
                for name, schema in t["parameters"].items()
            }
            tools.append(
                PublicToolInfo(
                    tool_id=t["tool_id"],
                    display_name=t["display_name"],
                    description=t["description"],
                    example=t.get("example"),
                    parameters=params,
                )
            )
            param_lines = []
            for name, spec in t["parameters"].items():
                req = "required" if spec.get("required", False) else "optional"
                param_lines.append(f"    {name} ({req}): {spec['description']}")
            example_str = json.dumps(t["example"]) if t.get("example") else "{}"
            prompt_lines.append(
                f'{t["tool_id"]}: {t["description"]}\n'
                f'  Parameters:\n'
                + "\n".join(param_lines) + "\n"
                f'  Example: {example_str}'
            )
        return ToolListResponse(
            tools=tools,
            tools_prompt="\n\n".join(prompt_lines),
        )

    def _find_tool(self, tool_id: str) -> dict | None:
        for t in _load_registry():
            if t["tool_id"] == tool_id:
                return t
        return None

    def _validate_parameters(self, tool_def: dict, params: Dict[str, Any]) -> str:
        schema = tool_def["parameters"]

        for name, spec in schema.items():
            if spec.get("required", False) and name not in params:
                return f"Missing required parameter: {name}"

        for name in params:
            if name not in schema:
                return f"Unknown parameter: {name}"

        return ""

    async def execute_tool(self, tool_id: str, parameters: Dict[str, Any]) -> ExecuteToolResponse:
        tool_def = self._find_tool(tool_id)
        if tool_def is None:
            return ExecuteToolResponse(
                success=False,
                tool_id=tool_id,
                error=f"Unknown tool: {tool_id}",
            )

        validation_error = self._validate_parameters(tool_def, parameters)
        if validation_error:
            return ExecuteToolResponse(
                success=False,
                tool_id=tool_id,
                error=validation_error,
            )

        # Absolute URLs: call directly without n8n.
        webhook_path = tool_def.get("webhook_path", tool_id)
        if webhook_path.startswith("http://") or webhook_path.startswith("https://"):
            url = webhook_path
        else:
            url = _build_tool_webhook_url(webhook_path)
        logger.info("Executing tool %s: POST %s", tool_id, url)

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(url, json=parameters)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                logger.error("Tool %s returned HTTP %s: %s", tool_id, exc.response.status_code, exc)
                return ExecuteToolResponse(
                    success=False,
                    tool_id=tool_id,
                    error=f"Tool returned HTTP {exc.response.status_code}",
                )
            except (httpx.RequestError, Exception) as exc:
                logger.error("Tool %s call failed: %s", tool_id, exc)
                return ExecuteToolResponse(
                    success=False,
                    tool_id=tool_id,
                    error=f"Tool request failed: {exc}",
                )

        return ExecuteToolResponse(
            success=True,
            tool_id=tool_id,
            result=data,
        )
