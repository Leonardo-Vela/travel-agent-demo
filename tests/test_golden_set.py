import os

import pytest

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
