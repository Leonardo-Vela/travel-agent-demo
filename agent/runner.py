"""Run the workshop agent on a task and collect its answer, trace and metrics.

For a given task this returns the final answer plus everything the tool-quality
scorecard needs: the ordered reasoning/tool trace, how many tool calls were
made, which capability each call exercised, whether any call failed, and whether
the agent hit the step cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from langchain_core.messages import HumanMessage

from config import MAX_STEPS


@dataclass
class RunResult:
    """Everything one agent run produces, for display and scoring."""

    answer: str = ""
    trace: List[dict] = field(default_factory=list)  # reasoning + tool events
    tool_calls: int = 0
    assistant_turns: int = 0
    # Per-call bookkeeping for the tool-quality metrics.
    capabilities_used: List[str] = field(default_factory=list)  # ordered
    error_calls: int = 0

    @property
    def hit_cap(self) -> bool:
        """True if the loop reached the step cap (a robustness failure)."""
        return self.assistant_turns >= MAX_STEPS


def run_task(agent, question: str, capability_of: Dict[str, str]) -> RunResult:
    """Run ``agent`` on ``question``; tag each tool call with its capability.

    ``capability_of`` maps a tool *name* to the capability it wraps (from
    ``build_toolbox``), so the scorer can tell on-target from off-target calls.
    """
    result = RunResult()
    pending_by_id: dict = {}

    try:
        for event in agent.stream(
            {"steps": 0, "messages": [HumanMessage(content=question)]},
            stream_mode="updates",
        ):
            for node_name, node_output in event.items():
                if node_name == "assistant":
                    result.assistant_turns += 1
                    msg = node_output["messages"][-1]
                    if getattr(msg, "tool_calls", None):
                        reasoning = getattr(msg, "content", "") or ""
                        if isinstance(reasoning, str) and reasoning.strip():
                            result.trace.append(
                                {"type": "reasoning", "text": reasoning.strip()}
                            )
                        for tc in msg.tool_calls:
                            result.tool_calls += 1
                            cap = capability_of.get(tc["name"], "unknown")
                            result.capabilities_used.append(cap)
                            entry = {
                                "type": "tool",
                                "order": result.tool_calls,
                                "name": tc["name"],
                                "capability": cap,
                                "args": tc.get("args", {}),
                                "result": None,
                                "is_error": False,
                            }
                            result.trace.append(entry)
                            pending_by_id[tc.get("id")] = entry
                    elif getattr(msg, "content", ""):
                        result.answer = msg.content

                elif node_name == "tools":
                    for tmsg in node_output.get("messages", []):
                        tid = getattr(tmsg, "tool_call_id", None)
                        content = getattr(tmsg, "content", "")
                        is_error = str(content).lstrip().upper().startswith("ERROR")
                        if is_error:
                            result.error_calls += 1
                        if tid in pending_by_id:
                            pending_by_id[tid]["result"] = content
                            pending_by_id[tid]["is_error"] = is_error
    except Exception as exc:  # surfaced to the UI rather than crashing the app
        result.answer = f"Error while running the agent: {exc}"

    if not result.answer:
        result.answer = "(the agent produced no final answer)"
    return result


def evaluate_task(task, result: RunResult) -> dict:
    """Turn a run into the per-task metrics the scorecard consumes.

    Encodes the two lessons:
      - ``made_up``: the agent answered a trap task without ever calling the
        on-target tool (or answered wrongly with no relevant tool call) — i.e.
        it leaned on common sense. Lesson (a).
      - ``off_target_calls`` / ``on_target``: did it pick the right, focused
        tool for the job, or flail with a god/overlapping tool. Lesson (b).
    """
    needs = set(task.needs)
    used = result.capabilities_used
    used_set = set(used)

    on_target = needs.issubset(used_set)
    off_target_calls = sum(
        1 for c in used if c not in needs and c != "unknown"
    )

    correct = bool(task.check(result.answer))

    # "Made up an answer from common sense": for a trap task, giving any answer
    # while NOT correctly deferring means it hallucinated. For a normal task, a
    # wrong answer produced without using the needed capability is a made-up
    # (common-sense) answer rather than a tool failure.
    if getattr(task, "is_trap", False):
        made_up = not correct
    else:
        made_up = (not correct) and not needs.issubset(used_set)

    # Recovery: only meaningful when at least one call errored. Did the agent go
    # on to produce a correct (or, for traps, correctly-deferred) answer?
    recovered = None
    if result.error_calls > 0:
        recovered = correct

    return {
        "id": task.id,
        "question": task.question,
        "teaches": task.teaches,
        "answer": result.answer,
        "trace": result.trace,
        "needs": tuple(task.needs),
        "correct": correct,
        "on_target": on_target,
        "off_target_calls": off_target_calls,
        "made_up": made_up,
        "recovered": recovered,
        "tool_calls": result.tool_calls,
        "error_calls": result.error_calls,
        "hit_cap": result.hit_cap,
    }
