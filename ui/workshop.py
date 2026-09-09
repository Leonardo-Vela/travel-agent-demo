"""Workshop-specific UI: the reasoning/tool trace and the scorecard."""

from __future__ import annotations

import html
from typing import List

import streamlit as st


# Friendly "what is being done" phrases for the trace, keyed by tool name.
_TOOL_ACTIONS = {
    "calculator": "Doing the math",
    "get_weather": "Checking current weather",
    "get_climate_average": "Checking historical climate",
    "get_flight": "Looking up a round-trip flight",
    "get_one_way_fare": "Looking up a one-way fare",
    "get_flight_leg": "Looking up a flight leg",
    "get_flight_schedule": "Checking flight times",
    "list_hotels": "Listing hotels",
    "get_hotel": "Looking up a hotel",
    "find_hotels_in_budget": "Filtering hotels by budget",
    "get_activity_price": "Looking up an activity price",
    "list_activities": "Listing activities",
    "get_trip_cost": "Bundling a trip cost",
    "get_checkin_rule": "Checking the check-in rule",
    "plan_vacation": "Dumping everything about a city",
}


def tool_label(name: str) -> str:
    """Return a friendly phrase for a tool name."""
    return _TOOL_ACTIONS.get(name, name.replace("_", " ").capitalize())


def render_trace(trace: List[dict], *, open_by_default: bool = True) -> None:
    """Render the agent's reasoning + tool trace as an expandable tree.

    This is the heart of the workshop — it makes the otherwise invisible
    decide -> act -> observe loop visible so participants can see exactly why
    their agent succeeded or failed.
    """
    if not trace:
        st.markdown(
            '<div class="trace-empty">Run a task to see the agent think, '
            "call tools, and answer — step by step.</div>",
            unsafe_allow_html=True,
        )
        return

    n_tools = sum(1 for e in trace if e.get("type") == "tool")
    parts = [
        f'<details class="reasoning-trace"{" open" if open_by_default else ""}>',
        '<summary><span class="reasoning-icon">◆</span> Agent trace'
        f'<span class="reasoning-count">{n_tools} tool call'
        f'{"" if n_tools == 1 else "s"}</span></summary>',
        '<div class="trace-body">',
    ]

    for entry in trace:
        if entry.get("type") == "reasoning":
            parts.append(
                f'<div class="trace-reason">{html.escape(entry["text"])}</div>'
            )
        elif entry.get("type") == "tool":
            order = entry.get("order", "")
            label = html.escape(tool_label(entry["name"]))
            args = entry.get("args") or {}
            body = ""
            if args:
                arg_rows = "".join(
                    f'<div class="trace-arg"><span class="trace-arg-k">'
                    f"{html.escape(str(k))}</span>"
                    f'<span class="trace-arg-v">{html.escape(str(v))}</span></div>'
                    for k, v in args.items()
                )
                body += f'<div class="trace-args">{arg_rows}</div>'
            gen_result = entry.get("result")
            if gen_result:
                body += (
                    f'<pre class="trace-result">{html.escape(str(gen_result))}</pre>'
                )
            parts.append(
                '<details class="trace-tool">'
                f'<summary><span class="trace-order">{order}</span>'
                f'<span class="trace-tool-name">{label} '
                f'<code>{html.escape(entry["name"])}</code></span></summary>'
                f'<div class="trace-tool-body">{body or "<em>No details.</em>"}</div>'
                "</details>"
            )

    parts.append("</div></details>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _metric_row(icon: str, label: str, value: str) -> str:
    return (
        '<div class="wk-metric">'
        f'<span class="wk-metric-icon">{icon}</span>'
        f'<span class="wk-metric-label">{label}</span>'
        f'<span class="wk-metric-value">{value}</span>'
        "</div>"
    )


def render_checklist(items: List[dict]) -> None:
    """Render the live Tool Design Checklist, computed from the toolbox specs.

    This updates instantly as participants edit their tools — watching items
    turn green is the "I now know how to build a good tool" feedback loop.
    """
    passed = sum(1 for i in items if i["ok"])
    total = len(items)
    rows = []
    for it in items:
        mark = "✅" if it["ok"] else "⬜"
        cls = "ok" if it["ok"] else "todo"
        hint = ""
        if not it["ok"]:
            hint = f'<div class="wk-check-hint">{html.escape(it["hint"])}</div>'
        rows.append(
            f'<div class="wk-check-row {cls}">'
            f'<span class="wk-check-mark">{mark}</span>'
            f'<div class="wk-check-body"><span class="wk-check-label">'
            f'{html.escape(it["label"])}</span>{hint}</div>'
            "</div>"
        )
    st.markdown(
        '<div class="wk-card">'
        f'<div class="wk-card-head">🧩 Tool Design Checklist '
        f'<span class="wk-badge {"ok" if passed == total else "bad"}">'
        f'{passed}/{total}</span></div>'
        + "".join(rows)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_scorecard(summary: dict, per_task: List[dict]) -> None:
    """Full tool-quality scorecard across the task set.

    The two headline metrics ARE the two lessons made measurable:
      - 🧠 Made-up answers -> the model leaning on common sense (lesson a)
      - 🔀 Wrong-tool calls -> god/overlapping tool confusion (lesson b)
    """
    rows = []
    for t in per_task:
        if t["correct"]:
            mark = "✅"
        elif t["made_up"]:
            mark = "🧠"  # answered from common sense instead of a tool
        else:
            mark = "❌"
        tag = ""
        if t["off_target_calls"]:
            tag = '<span class="wk-task-tag">wrong tool</span>'
        elif t["made_up"]:
            tag = '<span class="wk-task-tag">made up</span>'
        rows.append(
            '<div class="wk-task-row">'
            f'<span class="wk-task-status">{mark}</span>'
            f'<span class="wk-task-q">{html.escape(t["question"])}{tag}</span>'
            f'<span class="wk-task-calls">{t["tool_calls"]} calls'
            f'{" · cap" if t["hit_cap"] else ""}</span>'
            "</div>"
        )

    recov = ""
    if summary["recovery_cases"]:
        recov = _metric_row(
            "🔁", "Recovered after a failed lookup",
            f'{summary["recovered"]} / {summary["recovery_cases"]}',
        )

    html_block = (
        '<div class="wk-card">'
        f'<div class="wk-score">🛠️ Tool quality: <b>{summary["quality"]}</b>/100</div>'
        + _metric_row(
            "✅", "Correct answers",
            f'{summary["correct"]} / {summary["total"]}',
        )
        + _metric_row(
            "🧠", "Made-up (common-sense) answers", str(summary["made_up"]),
        )
        + _metric_row(
            "🔀", "Wrong-tool calls", str(summary["off_target_calls"]),
        )
        + _metric_row(
            "🎯", "On-target tool choice",
            f'{summary["on_target"]} / {summary["total"]}',
        )
        + recov
        + _metric_row("⚡", "Total tool calls", str(summary["tool_calls"]))
        + '<div class="wk-task-list">' + "".join(rows) + "</div>"
        + "</div>"
    )
    st.markdown(html_block, unsafe_allow_html=True)
