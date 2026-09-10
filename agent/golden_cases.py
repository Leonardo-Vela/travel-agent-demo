from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass(frozen=True)
class GoldenCase:
    id: str
    question: str
    needs: tuple[str, ...]
    answer_check: Callable[[str], bool]
    required_tool_names: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    expected_order: tuple[str, ...] | None = None
    teaches: str = ""


def _contains_any(text: str, *tokens: str) -> bool:
    lower = text.lower().replace(",", "").replace("€", "eur").replace("£", "gbp")
    return any(token.lower().replace(",", "").replace("€", "eur").replace("£", "gbp") in lower for token in tokens)


def build_golden_suite() -> list[dict]:
    """Return a canonical golden set for this travel-planning agent.

    ``needs`` are capability groups, not raw tool ids, because the runner maps
    each tool name to a group such as "Weather" or "Flights". We keep the exact
    tool call validation in a separate ``required_tool_names`` field so both
    levels are tested.
    """
    cases = [
        GoldenCase(
            id="weather_barcelona",
            question="What's the weather in Barcelona",
            needs=("Weather",),
            required_tool_names=("get_weather",),
            forbidden=("get_climate_average",),
            answer_check=lambda s: _contains_any(s, "barcelona", "26", "°c"),
            teaches="One direct weather lookup should be enough; no climate decoy.",
        ),
        GoldenCase(
            id="flight_prague_round_trip",
            question="How much is the round trip flight to Prague, and how long does it take?",
            needs=("Directory", "Flights"),
            required_tool_names=("get_airport_code", "get_flight"),
            answer_check=lambda s: _contains_any(s, "prague", "90", "1h10", "€"),
            expected_order=("get_airport_code", "get_flight"),
            teaches="Translate city to airport code before reading the flight tool.",
        ),
        GoldenCase(
            id="london_hotel_options",
            question="I want to stay in London. What are my hotel options and how much do they cost?",
            needs=("Directory", "Hotels"),
            required_tool_names=("list_districts", "list_hotels"),
            answer_check=lambda s: _contains_any(s, "london", "the kensington", "museum court hotel", "soho central", "£", "gbp"),
            expected_order=("list_districts", "list_hotels"),
            teaches="Hotels are keyed by district, so locate London districts and then list hotels.",
        ),
        GoldenCase(
            id="prague_old_town_3_night_total_eur",
            question="If I book the cheapest hotel in Prague's Old town for 3-nights, what's that in euros?",
            needs=("Directory", "Hotels", "Cost"),
            required_tool_names=("list_districts", "list_hotels", "get_exchange_rate", "calculator"),
            forbidden=("get_trip_cost",),
            answer_check=lambda s: _contains_any(s, "old town", "old town inn", "1875", "euro", "eur") or "5625" in s.lower(),
            expected_order=("list_districts", "list_hotels", "get_exchange_rate", "calculator"),
            teaches="Hotel prices are per night, local currency must convert to EUR, and the total is hotel price × nights.",
        ),
        GoldenCase(
            id="zurich_vs_istanbul_comparison",
            question="Compare a 4-night trip to Zurich vs Istanbul: round-trip flight, the best rated hotel, and the single cheapest activity, all totalled in euros. What are the options?",
            needs=("Directory", "Flights", "Hotels", "Activities", "Cost"),
            required_tool_names=("get_airport_code", "get_flight", "list_districts", "list_hotels", "list_activities", "get_exchange_rate", "calculator"),
            forbidden=("get_trip_cost",),
            answer_check=lambda s: (
                _contains_any(s, "zurich", "istanbul")
                and _contains_any(s, "4-night", "4 nights")
                and _contains_any(s, "1094.70", "1094.74", "1225.75", "1225.79")
                and _contains_any(s, "320.32", "597.48")
                and _contains_any(s, "eur", "€")
            ),
            teaches="A real comparison must include the 4-night hotel multiplier, local-currency conversion, and explicit arithmetic for each option.",
        ),
        GoldenCase(
            id="eur_gbp_exchange_rate",
            question="What is the exchange rate between Euro and British pound?",
            needs=("Cost",),
            required_tool_names=("get_exchange_rate",),
            forbidden=("calculator",),
            answer_check=lambda s: _contains_any(s, "eur", "gbp", "0.85", "1.1765"),
            teaches="Currency conversion is a direct rate lookup and should not be done by mental math.",
        ),
        GoldenCase(
            id="barcelona_4_night_4_people_total",
            question="How much is a 4-night trip to Barcelona, including flight, the cheapest hotel and the cheapest activity for 4 persons?",
            needs=("Directory", "Flights", "Hotels", "Activities", "Cost"),
            required_tool_names=("get_airport_code", "get_flight", "list_districts", "list_hotels", "list_activities", "calculator"),
            forbidden=("get_trip_cost",),
            answer_check=lambda s: _contains_any(s, "barcelona", "2240", "4", "flight", "hotel", "activity", "eur", "€"),
            expected_order=("get_airport_code", "get_flight", "list_districts", "list_hotels", "list_activities", "calculator"),
            teaches="For multi-person hotel costs, multiply the hotel rate by nights and by the number of people before adding the flight and activity totals.",
        ),
    ]
    return [case.__dict__ for case in cases]


def run_golden_suite(agent, capability_of, suite: Iterable[dict] | None = None):
    """Execute each golden case and return the evaluation records."""
    from agent.runner import evaluate_task, run_task

    suite = list(suite or build_golden_suite())
    records = []
    for case in suite:
        result = run_task(agent, case["question"], capability_of)
        tool_names = [t["name"] for t in result.trace if t.get("type") == "tool"]
        actual_capabilities = set(result.capabilities_used)

        for required in case["required_tool_names"]:
            if required not in tool_names:
                raise AssertionError(f"Case {case['id']} missing required tool: {required}. Actual tools: {tool_names}")

        for forbidden in case["forbidden"]:
            if forbidden in tool_names:
                raise AssertionError(f"Case {case['id']} unexpectedly used forbidden tool: {forbidden}. Actual tools: {tool_names}")

        actual_order = []
        seen = set()
        for name in tool_names:
            if name in case["expected_order"] and name not in seen:
                actual_order.append(name)
                seen.add(name)
        if case["expected_order"] is not None:
            if tuple(actual_order) != tuple(case["expected_order"]):
                raise AssertionError(f"Case {case['id']} wrong order: got {actual_order}, expected {case['expected_order']}")

        task = type(
            "GoldenTask",
            (),
            {
                "id": case["id"],
                "question": case["question"],
                "needs": set(case["needs"]),
                "check": lambda self, answer, check=case["answer_check"]: check(answer),
                "teaches": case["teaches"],
                "is_trap": False,
            },
        )()
        evaluation = evaluate_task(task, result)
        if not evaluation["correct"]:
            raise AssertionError(f"Case {case['id']} failed answer check: {result.answer}")
        if not evaluation["on_target"]:
            raise AssertionError(f"Case {case['id']} used wrong capability set: {actual_capabilities} vs {case['needs']}")
        records.append(evaluation)
    return records
