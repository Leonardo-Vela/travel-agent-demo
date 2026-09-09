"""Shared utilities for the Local GenAI + LangGraph Academy notebooks.

The ``LocalGenAIChatModel`` adapter provides the standard LangChain ``invoke``
interface, but the internal endpoint does not return native ``tool_calls``.
The functions in this module therefore implement portable structured output
through validated JSON.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Any, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

try:
    from .local_genai import (
        DEFAULT_CONFIG_PATH,
        LocalGenAIChatModel,
        bootstrap_local_genai as _bootstrap_local_genai,
        configure_langsmith_from_runtime_config,
        load_runtime_config,
    )
except ImportError:  # pragma: no cover - direct-run fallback
    from local_genai import (
        DEFAULT_CONFIG_PATH,
        LocalGenAIChatModel,
        bootstrap_local_genai as _bootstrap_local_genai,
        configure_langsmith_from_runtime_config,
        load_runtime_config,
    )


SchemaT = TypeVar("SchemaT", bound=BaseModel)


def bootstrap_local_genai(
    *,
    temperature: float = 0.0,
    max_completion_tokens: int = 1200,
    model_name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
):
    """Configure LangSmith and create the model used throughout the lessons."""

    configure_langsmith_from_runtime_config()
    return _bootstrap_local_genai(
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
    )


def safe_runtime_summary() -> dict[str, Any]:
    """Return diagnostics without secrets, tokens, or login credentials."""

    cfg = load_runtime_config()
    return {
        "config_path": str(DEFAULT_CONFIG_PATH),
        "llm_chat_endpoint": cfg.get("llm_chat_endpoint"),
        "completion_token_parameter": cfg.get("completion_token_parameter"),
        "llm_chat_verify_tls": cfg.get("llm_chat_verify_tls"),
        "langsmith_tracing": cfg.get("langsmith_tracing"),
        "langsmith_project": cfg.get("langsmith_project"),
    }


def message_text(message: BaseMessage | str) -> str:
    """Normalize message text across different langchain-core versions."""

    if isinstance(message, str):
        return message
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or part.get("content") or "")
            if isinstance(part, dict)
            else str(part)
            for part in content
        )
    return str(content)


def extract_json_object(text: str) -> dict[str, Any]:
    """Read a JSON object even when the model added Markdown or prose."""

    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"The model did not return a valid JSON object: {text[:500]!r}")


def invoke_json(
    llm: LocalGenAIChatModel,
    *,
    system_prompt: str,
    user_prompt: str,
    schema: type[SchemaT],
    retries: int = 2,
) -> SchemaT:
    """Invoke the local model and validate its response with Pydantic.

    This is the local counterpart of Academy's ``with_structured_output``.
    On failure, the model receives validation feedback and generates JSON again.
    """

    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    messages: list[BaseMessage] = [
        SystemMessage(
            content=(
                f"{system_prompt}\n\n"
                "Return exactly one JSON object matching this JSON Schema: "
                f"{schema_json}"
            )
        ),
        HumanMessage(content=user_prompt),
    ]
    last_error: Exception | None = None

    for _ in range(retries + 1):
        response = llm.invoke(messages)
        raw = message_text(response)
        try:
            return schema.model_validate(extract_json_object(raw))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            messages.extend(
                [
                    response,
                    HumanMessage(
                        content=(
                            "Correct the response. Return valid JSON only; "
                            f"validation error: {exc}"
                        )
                    ),
                ]
            )
    raise RuntimeError("Could not obtain valid structured output") from last_error


def latest_human_text(messages: list[BaseMessage]) -> str:
    """Find the latest user message in the thread history."""

    for message in reversed(messages):
        if message.type == "human":
            return message_text(message)
    return ""


def notebook_package_dir(start: str | Path | None = None) -> Path:
    """Find the installed package directory regardless of the start directory."""

    import genai_core

    return Path(genai_core.__file__).resolve().parent


def show_mermaid(source: str, *, title: str | None = None) -> str:
    """Display Mermaid source in a notebook and return it for reuse.

    JupyterLab 4 renders Mermaid fenced blocks. The raw source remains visible
    in frontends that do not provide Mermaid rendering.
    """

    from IPython.display import Markdown, display

    heading = f"### {title}\n\n" if title else ""
    display(Markdown(f"{heading}```mermaid\n{source.strip()}\n```"))
    return source


def show_graph(graph: Any, *, title: str = "Compiled graph") -> str:
    """Show a compiled LangGraph as Mermaid and as guaranteed ASCII output."""

    drawable = graph.get_graph()
    mermaid = drawable.draw_mermaid()
    show_mermaid(mermaid, title=title)
    print("\nASCII fallback:\n")
    try:
        print(drawable.draw_ascii())
    except Exception as exc:
        print(f"ASCII rendering is unavailable: {exc}")
        print("\nMermaid source:\n", mermaid)
    return mermaid


def show_messages(messages: list[BaseMessage], *, title: str = "Messages") -> None:
    """Render a compact, color-coded message table in a notebook."""

    from IPython.display import HTML, display

    colors = {
        "system": ("#e8eefc", "#233876"),
        "human": ("#e8f7ee", "#1f5f39"),
        "ai": ("#f4eafe", "#5d2f86"),
        "tool": ("#fff3d9", "#714c00"),
    }
    rows = []
    for index, message in enumerate(messages):
        background, foreground = colors.get(message.type, ("#f2f2f2", "#333"))
        rows.append(
            "<tr>"
            f"<td style='padding:8px;border:1px solid #ddd'>{index}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;background:{background};color:{foreground};font-weight:600'>"
            f"{escape(message.type)}</td>"
            f"<td style='padding:8px;border:1px solid #ddd;white-space:pre-wrap'>{escape(message_text(message))}</td>"
            "</tr>"
        )
    table = (
        f"<h3>{escape(title)}</h3>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<thead><tr><th>#</th><th>Role</th><th>Content</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    display(HTML(table))


def show_state(state: dict[str, Any], *, title: str = "State snapshot") -> None:
    """Render state as readable JSON while converting LangChain messages."""

    from IPython.display import HTML, display

    def simplify(value: Any) -> Any:
        if isinstance(value, BaseMessage):
            return {"role": value.type, "content": message_text(value), "id": value.id}
        if isinstance(value, dict):
            return {str(key): simplify(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [simplify(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return repr(value)

    rendered = json.dumps(simplify(state), ensure_ascii=False, indent=2)
    display(
        HTML(
            f"<h3>{escape(title)}</h3>"
            "<pre style='background:#111827;color:#e5e7eb;padding:14px;border-radius:8px;overflow:auto'>"
            f"{escape(rendered)}</pre>"
        )
    )
