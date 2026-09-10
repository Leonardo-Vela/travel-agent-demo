import os

import pytest
from langchain_core.messages import AIMessage

from agent.prompts import AGENT_PROMPT
from agent.runner import run_task
from agent.tools import _AIRPORTS, _CONDITIONS, _HOTELS, _EXCHANGE_PER_EUR

# These tests are intentionally written before the golden framework code itself,
# so they describe the exact expected answers and tool coverage we want.


def test_dataset_expected_values():
    # Q1
    assert _CONDITIONS["barcelona"]["rain"] == 10
    assert _CONDITIONS["barcelona"]["sunrise"] == "07:05"

    # Q2
    assert _AIRPORTS["PRG"]["oneway"] == 45
    assert _AIRPORTS["PRG"]["duration"] == "1h10"

    # Q3
    london_hotels = _HOTELS["south kensington"] + _HOTELS["soho"]
    assert [name for name, *_ in london_hotels] == ["The Kensington", "Museum Court Hotel", "Soho Central"]

    # Q4
    cheapest_prague_old_town = min(_HOTELS["old town"], key=lambda row: row[1])
    assert cheapest_prague_old_town[0] == "Old Town Inn"
    assert cheapest_prague_old_town[1] == 1875
    assert _EXCHANGE_PER_EUR["CZK"] == 25.0

    # Q5
    assert _AIRPORTS["ZRH"]["oneway"] == 55
    assert _AIRPORTS["IST"]["oneway"] == 130
    assert max(_HOTELS["altstadt"], key=lambda row: row[2])[0] == "Altstadt Boutique"
    assert max(_HOTELS["sultanahmet"], key=lambda row: row[2])[0] == "Palace View"


def test_default_traveler_count_is_one_when_unspecified():
    prompt = AGENT_PROMPT.lower()
    assert "assume exactly one person" in prompt
    assert "if the user does not specify" in prompt
    assert "flight prices are also per person" in prompt
    assert "flight_total = flight_price_per_person * people" in prompt
    assert "hotel_total = hotel_price_per_night_per_person * nights * people" in prompt
    assert "activity_total = activity_price_per_person * people" in prompt
    assert "grand_total = flight_total + hotel_total + activity_total" in prompt


def test_run_task_ignores_initial_overview_before_first_tool_call():
    class FakeAgent:
        def stream(self, *_args, **_kwargs):
            yield {
                "assistant": {
                    "messages": [
                        AIMessage(
                            content="To compare the trip, I need the hotel rate and the flight cost. I will gather those facts next.",
                            tool_calls=[{
                                "id": "call_1",
                                "name": "list_hotels",
                                "args": {"district": "Old Town"},
                            }],
                        )
                    ]
                }
            }
            yield {
                "tools": {"messages": [AIMessage(content="Old Town Inn 1875 CZK/night per person", tool_call_id="call_1")]}
            }

    result = run_task(FakeAgent(), "How much is the hotel in Prague?", {"list_hotels": "Hotels"})

    assert not any("To compare the trip" in entry.get("text", "") for entry in result.trace if entry.get("type") == "reasoning")
    assert [entry["name"] for entry in result.trace if entry.get("type") == "tool"] == ["list_hotels"]


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not configured")
def test_live_agent_golden_cases():
    from agent.golden_cases import build_golden_suite
    from agent.graph import build_agent
    from agent.tools import build_toolbox
    from agent.runner import evaluate_task, run_task

    enabled = {
        "get_weather",
        "get_airport_code",
        "get_flight",
        "list_districts",
        "list_hotels",
        "get_currency",
        "get_exchange_rate",
        "calculator",
        "list_activities",
    }
    tools, capability_of = build_toolbox(enabled)
    agent = build_agent(tools)

    suite = build_golden_suite()
    for case in suite:
        result = run_task(agent, case["question"], capability_of)
        evaluation = evaluate_task(type("TaskStub", (), {
            "needs": case["needs"],
            "check": lambda self, answer: case["answer_check"](answer),
            "id": case["id"],
            "question": case["question"],
            "teaches": case.get("teaches", ""),
            "is_trap": False,
        })(), result)
        assert evaluation["on_target"] is True
        assert evaluation["correct"] is True
