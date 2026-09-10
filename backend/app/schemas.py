from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The user's travel question")
    enabled_tools: list[str] | None = Field(
        default=None,
        description="Optional list of tool ids, otherwise the reference tool set is used.",
    )


class ChatResponse(BaseModel):
    status: Literal["ok", "error"] = "ok"
    answer: str
    trace: list[dict[str, Any]] = []
    tool_calls: int = 0
    error: str | None = None
