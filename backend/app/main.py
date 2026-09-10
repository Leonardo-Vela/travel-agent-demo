from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.graph import build_agent
from agent.runner import run_task
from agent.tools import REFERENCE_ENABLED, build_toolbox
from backend.app.schemas import ChatRequest, ChatResponse

app = FastAPI(title="Travel Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    enabled = set(req.enabled_tools) if req.enabled_tools else set(REFERENCE_ENABLED)
    tools, meta = build_toolbox(enabled)
    agent = build_agent(tools)
    result = run_task(agent, question, meta)

    return ChatResponse(
        status="ok",
        answer=result.answer,
        trace=result.trace,
        tool_calls=result.tool_calls,
    )
