from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class ToolParameter(BaseModel):
    type: str = Field(..., example="string")
    description: str = Field(..., example="Recipient email address")
    required: bool = Field(default=True)


class PublicToolInfo(BaseModel):
    tool_id: str = Field(..., example="tool_send_email")
    display_name: str = Field(..., example="Send Email")
    description: str = Field(...)
    example: Optional[Dict[str, Any]] = Field(default=None)
    parameters: Dict[str, ToolParameter] = Field(...)


class ToolListResponse(BaseModel):
    tools: List[PublicToolInfo]
    tools_prompt: str = Field(default="")


class ExecuteToolRequest(BaseModel):
    tool_id: str = Field(..., example="tool_send_email")
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ExecuteToolResponse(BaseModel):
    success: bool
    tool_id: str
    result: Any = Field(default=None)
    error: str = Field(default="")
