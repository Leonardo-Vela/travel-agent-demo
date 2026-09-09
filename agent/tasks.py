"""The two prompt sets the workshop runs against.

There is no automatic scoring. Participants read the agent's answer and its
trace and JUDGE for themselves whether the tools did the job — which is exactly
what building a good tool feels like in real life.

STARTER_PROMPTS  — the five questions shown from the start. They look vanilla,
                   and even a wrong/consolidating tool returns a plausible
                   answer, so participants feel safe. Each quietly plants a trap.

CHALLENGE_PROMPTS — the five checking questions the presenter reveals later.
                   Four are answerable with a well-chosen toolbox; the last one
                   deliberately hits a wall (missing data / no tool for the job),
                   sparking the idea for a brand-new tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Prompt:
    """One workshop question plus a presenter-only hint."""

    text: str
    hint: str = ""          # shown only in the presenter panel, never to solvers


STARTER_PROMPTS: List[Prompt] = [
    Prompt(
        "How warm is it in Barcelona right now?",
        "Lookup. get_weather → 26°C. get_climate_average returns a plausible "
        "historical ~28°C — the current-vs-average trap.",
    ),
    Prompt(
        "What's the round-trip flight to Prague?",
        "Lookup. get_flight → €90. get_one_way_fare → €45 looks cheaper but is "
        "only one way.",
    ),
    Prompt(
        "What does the Ring Hotel in Vienna cost?",
        "Lookup. get_hotel → €150/night. It's a per-night rate — this primes the "
        "rate-vs-total mistake later.",
    ),
    Prompt(
        "I want to do 4 nights in Barcelona with flights, a hotel, and the "
        "Sagrada Familia tour. What's my total?",
        "Planning. get_flight €180 + list_hotels→Hotel Sol 4×140 + "
        "get_activity_price 30 + calculator → €770. get_trip_cost bundles to "
        "~€740 but silently drops the activity.",
    ),
    Prompt(
        "I've got about €900 for 5 nights in Lisbon including flights — is a "
        "mid-range hotel doable, and roughly what's left over?",
        "Planning/judgement. get_flight €210 + list_hotels→Casa Azul 5×110 + "
        "calculator = €760 → yes, ~€140 left. get_trip_cost answers €760 in one "
        "call but hides which hotel it chose.",
    ),
]


CHALLENGE_PROMPTS: List[Prompt] = [
    Prompt(
        "Which of the four cities is currently the warmest, and is it above 25°C?",
        "SOLVABLE. get_weather ×4 → Barcelona 26°C, yes. Detonates "
        "get_climate_average (historical numbers give a different ranking).",
    ),
    Prompt(
        "I want to fly to Barcelona, then on to Lisbon, then home. What do the "
        "flights cost in total?",
        "SOLVABLE with get_flight_leg: 90 + 95 + 105 = €290. get_flight "
        "(round-trip only) can't express a multi-city itinerary — its interface "
        "assumes home→city→home.",
    ),
    Prompt(
        "Is the Ring Hotel in Vienna under my €400 budget for a 3-night stay?",
        "SOLVABLE. get_hotel €150/night × 3 = €450 → no. Detonates the "
        "rate-vs-total trap from starter Q3.",
    ),
    Prompt(
        "Plan 4 nights in Lisbon with flights, a hotel and a Fado night — what's "
        "the total?",
        "SOLVABLE with primitives: get_flight €210 + list_hotels→Casa Azul 4×110 "
        "+ get_activity_price 35 + calculator = €685. get_trip_cost can't include "
        "the activity.",
    ),
    Prompt(
        "I need to be at Hotel Sol in Barcelona by 14:00. Which flight do I take, "
        "and when do I have to leave home?",
        "BREAKER. Flight choice is solvable: get_flight_schedule (08:00→10:20) + "
        "get_hotel airport→hotel 40min → arrive 11:00, the 08:00 works. But "
        "'when to leave home' is UNANSWERABLE: there is no home→airport travel "
        "time in the data and no tool that sums travel legs. Sparks a new tool, "
        "e.g. get_transfer(from, to).",
    ),
]
