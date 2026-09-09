"""Tool catalog for the travel-planning tool-design workshop.

The premise: *all the data needed to plan a trip already exists*. The skill the
workshop teaches is choosing the RIGHT tools to extract that data efficiently.

Participants toggle tools on and off in the right-hand rack and edit their
descriptions, reading each tool to decide which one fits the job. The catalog is
seeded with deliberate overlaps and traps:

  * good primitives (small, one job, honest about what they don't know), and
  * decoys that look plausible but consolidate/mislead (a climate average that
    looks like today's weather, and a "plan the whole trip" cost bundle that
    hides its assumptions and skips currency conversion).

THE DATA IS RELATIONAL AND MULTI-KEYED. Not everything hangs off the city:

  * Weather (temperature, conditions, climate) is keyed by CITY.
  * Flights, schedules and legs are keyed by AIRPORT CODE (BCN/LIS/VIE/PRG),
    not city — you must translate city → code via ``get_airport_code`` first.
  * Hotels and activities are keyed by DISTRICT, not city — you must translate
    city → districts via ``list_districts`` first, and district → city (and the
    airport transfer time) via ``get_district``.

So answering a real question means HOPPING across keys: e.g. to price a flight
to the city where "Castle tour" happens you go
``activity → district → city → airport code → flight``. Good tools expose the
join key they need and say which key they return; the god tool hides all the
hops and breaks the moment a question does not match its assumptions.

Nothing here touches the network — every value is fixed mock data, so the app is
deterministic and safe to run live.
"""

from __future__ import annotations

import ast
import operator as op
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple


# ===========================================================================
# The fixed dataset (everything the tools can possibly reveal)
# ===========================================================================
CITIES = ("Barcelona", "Prague", "London", "Zurich", "Istanbul", "Budapest")

# City → its airport code, country and local currency. Bridges a city name to
# its airport code (for flights) and its currency (for converting local prices).
_CITY_INFO: Dict[str, Dict[str, str]] = {
    "barcelona": {"airport": "BCN", "country": "Spain", "currency": "EUR"},
    "prague": {"airport": "PRG", "country": "Czechia", "currency": "CZK"},
    "london": {"airport": "LHR", "country": "United Kingdom", "currency": "GBP"},
    "zurich": {"airport": "ZRH", "country": "Switzerland", "currency": "CHF"},
    "istanbul": {"airport": "IST", "country": "Turkey", "currency": "TRY"},
    "budapest": {"airport": "BUD", "country": "Hungary", "currency": "HUF"},
}
_AIRPORT_TO_CITY = {v["airport"]: c for c, v in _CITY_INFO.items()}

# "How many of this currency = 1 EUR". Home always spends EUR (flights are priced
# in EUR), but a non-euro city quotes its local hotel/activity prices in its own
# currency, so those must be converted to EUR before they can be summed or
# compared against euro prices. Every city here uses a different rate.
_EXCHANGE_PER_EUR: Dict[str, float] = {
    "EUR": 1.0,
    "CZK": 25.0,
    "GBP": 0.85,
    "CHF": 0.95,
    "TRY": 35.0,
    "HUF": 390.0,
}

# ---- Keyed by CITY --------------------------------------------------------
# Current temperature (°C).
_WEATHER = {
    "barcelona": 26, "prague": 20, "london": 16,
    "zurich": 18, "istanbul": 28, "budapest": 22,
}

# Historical monthly *average* temperature (the climate decoy — not today).
_CLIMATE_AVG = {
    "barcelona": 28, "prague": 22, "london": 18,
    "zurich": 20, "istanbul": 30, "budapest": 24,
}

# Extra current conditions per city: chance of rain (%), sunrise, sunset.
_CONDITIONS = {
    "barcelona": {"rain": 10, "sunrise": "07:05", "sunset": "20:30"},
    "prague": {"rain": 55, "sunrise": "06:00", "sunset": "19:40"},
    "london": {"rain": 70, "sunrise": "06:20", "sunset": "19:30"},
    "zurich": {"rain": 35, "sunrise": "06:40", "sunset": "20:10"},
    "istanbul": {"rain": 15, "sunrise": "06:30", "sunset": "19:20"},
    "budapest": {"rain": 45, "sunrise": "05:50", "sunset": "19:35"},
}

# ---- Keyed by AIRPORT CODE ------------------------------------------------
# One-way fare from home and flight duration, per airport code. Round-trip = 2×.
_AIRPORTS: Dict[str, Dict[str, str]] = {
    "BCN": {"oneway": 90, "duration": "2h20"},
    "PRG": {"oneway": 45, "duration": "1h10"},
    "LHR": {"oneway": 70, "duration": "1h50"},
    "ZRH": {"oneway": 55, "duration": "1h20"},
    "IST": {"oneway": 130, "duration": "3h00"},
    "BUD": {"oneway": 60, "duration": "1h40"},
}


# Directional flight legs between any two points (Home + the four airports),
# stored symmetrically and keyed by AIRPORT CODE (or HOME). Price €, duration.
def _leg_key(a: str, b: str) -> frozenset:
    return frozenset({a.strip().upper(), b.strip().upper()})


_LEGS: Dict[frozenset, Tuple[int, str]] = {
    _leg_key("HOME", "BCN"): (90, "2h20"),
    _leg_key("HOME", "PRG"): (45, "1h10"),
    _leg_key("HOME", "LHR"): (70, "1h50"),
    _leg_key("HOME", "ZRH"): (55, "1h20"),
    _leg_key("HOME", "IST"): (130, "3h00"),
    _leg_key("HOME", "BUD"): (60, "1h40"),
    _leg_key("BCN", "LHR"): (85, "2h00"),
    _leg_key("BCN", "ZRH"): (75, "1h40"),
    _leg_key("BCN", "IST"): (140, "3h10"),
    _leg_key("LHR", "ZRH"): (90, "1h30"),
    _leg_key("LHR", "BUD"): (100, "2h20"),
    _leg_key("ZRH", "PRG"): (80, "1h20"),
    _leg_key("ZRH", "BUD"): (85, "1h30"),
    _leg_key("PRG", "BUD"): (55, "1h05"),
    _leg_key("PRG", "IST"): (120, "2h40"),
    _leg_key("BUD", "IST"): (95, "1h50"),
}

# Flight departures Home→airport: (departure, arrival, duration). Several a day.
_SCHEDULE: Dict[str, List[Tuple[str, str, str]]] = {
    "BCN": [
        ("06:30", "08:50", "2h20"),
        ("08:00", "10:20", "2h20"),
        ("11:15", "13:35", "2h20"),
        ("14:30", "16:50", "2h20"),
        ("17:05", "19:25", "2h20"),
        ("19:10", "21:30", "2h20"),
    ],
    "PRG": [
        ("07:25", "08:35", "1h10"),
        ("10:05", "11:15", "1h10"),
        ("12:40", "13:50", "1h10"),
        ("15:30", "16:40", "1h10"),
        ("17:45", "18:55", "1h10"),
        ("20:30", "21:40", "1h10"),
    ],
    "LHR": [
        ("07:10", "09:00", "1h50"),
        ("09:40", "11:30", "1h50"),
        ("13:15", "15:05", "1h50"),
        ("16:50", "18:40", "1h50"),
        ("19:30", "21:20", "1h50"),
    ],
    "ZRH": [
        ("06:45", "08:05", "1h20"),
        ("09:00", "10:20", "1h20"),
        ("12:30", "13:50", "1h20"),
        ("15:10", "16:30", "1h20"),
        ("18:00", "19:20", "1h20"),
        ("20:40", "22:00", "1h20"),
    ],
    "IST": [
        ("07:00", "10:00", "3h00"),
        ("10:30", "13:30", "3h00"),
        ("14:00", "17:00", "3h00"),
        ("18:20", "21:20", "3h00"),
    ],
    "BUD": [
        ("06:55", "08:35", "1h40"),
        ("09:20", "11:00", "1h40"),
        ("12:10", "13:50", "1h40"),
        ("15:40", "17:20", "1h40"),
        ("18:30", "20:10", "1h40"),
        ("21:00", "22:40", "1h40"),
    ],
}

# ---- Keyed by DISTRICT ----------------------------------------------------
# District → the city it belongs to and the airport→district transfer minutes.
# This is the ONLY table that links a district back to its city.
_DISTRICTS: Dict[str, Dict] = {
    "eixample": {"city": "barcelona", "airport_min": 40},
    "gothic quarter": {"city": "barcelona", "airport_min": 30},
    "barceloneta": {"city": "barcelona", "airport_min": 55},
    "old town": {"city": "prague", "airport_min": 35},
    "mala strana": {"city": "prague", "airport_min": 25},
    "south kensington": {"city": "london", "airport_min": 50},
    "soho": {"city": "london", "airport_min": 45},
    "altstadt": {"city": "zurich", "airport_min": 15},
    "enge": {"city": "zurich", "airport_min": 20},
    "sultanahmet": {"city": "istanbul", "airport_min": 55},
    "beyoglu": {"city": "istanbul", "airport_min": 45},
    "district v": {"city": "budapest", "airport_min": 30},
    "buda castle": {"city": "budapest", "airport_min": 35},
}

# Hotels per DISTRICT: (name, price in the city's LOCAL currency, rating).
_HOTELS: Dict[str, List[Tuple[str, int, float]]] = {
    "eixample": [("Hotel Sol", 140, 4.5)],
    "gothic quarter": [("Rambla Rooms", 95, 4.1)],
    "barceloneta": [("Beachside Inn", 120, 4.3)],
    # Prague is in Czechia — prices in CZK.
    "old town": [("Old Town Inn", 1875, 4.3)],
    "mala strana": [("Riverside Prague", 3250, 4.7)],
    # London — prices in GBP.
    "south kensington": [("The Kensington", 210, 4.6),
                         ("Museum Court Hotel", 165, 4.1)],
    "soho": [("Soho Central", 175, 4.2)],
    # Zurich — prices in CHF.
    "altstadt": [("Altstadt Boutique", 260, 4.7)],
    "enge": [("Lake Enge Hotel", 190, 4.3)],
    # Istanbul — prices in TRY.
    "sultanahmet": [("Palace View", 2800, 4.4)],
    "beyoglu": [("Taksim Suites", 1950, 4.1)],
    # Budapest — prices in HUF.
    "district v": [("Danube Grand", 48000, 4.5)],
    "buda castle": [("Castle Hill Inn", 32000, 4.2)],
}

# Activities per DISTRICT: (name, price in the city's LOCAL currency).
_ACTIVITIES: Dict[str, List[Tuple[str, int]]] = {
    "eixample": [("Sagrada Familia tour", 30)],
    "barceloneta": [("Beach day", 0)],
    "gothic quarter": [("Tapas tour", 45)],
    # Prague prices are in CZK.
    "old town": [("River cruise", 550), ("Beer tasting", 450)],
    "mala strana": [("Castle tour", 375)],
    # London prices are in GBP.
    "south kensington": [("Museum pass", 25)],
    "soho": [("West End show", 90)],
    # Zurich prices are in CHF.
    "altstadt": [("Old town walk", 20), ("Chocolate tasting", 45)],
    "enge": [("Lake cruise", 35)],
    # Istanbul prices are in TRY.
    "sultanahmet": [("Hagia Sophia tour", 600)],
    "beyoglu": [("Bosphorus cruise", 850)],
    # Budapest prices are in HUF.
    "district v": [("Parliament tour", 12000)],
    "buda castle": [("Thermal bath", 9000)],
}

_CHECKIN_MINUTES = 90


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _norm(s) -> str:
    return str(s or "").strip().lower()


def _err(msg: str) -> str:
    """Honest, guiding error. Always starts with ERROR: so the trace flags it."""
    return f"ERROR: {msg}"


def _resolve_city(value: str):
    """Return the canonical city key for a (possibly partial) name, or None."""
    v = _norm(value)
    if not v:
        return None
    if v in _CITY_INFO:
        return v
    for city in _CITY_INFO:
        if city in v or v in city:
            return city
    return None


def _resolve_airport(value: str):
    """Return a canonical airport CODE (BCN/LIS/VIE/PRG) or None.

    Only accepts a real code — a city name is rejected on purpose so the agent
    is forced to translate it via get_airport_code first.
    """
    v = str(value or "").strip().upper()
    return v if v in _AIRPORTS else None


def _resolve_district(value: str):
    """Return the canonical district key for a (possibly partial) name, or None."""
    v = _norm(value)
    if not v:
        return None
    if v in _DISTRICTS:
        return v
    for d in _DISTRICTS:
        if d in v or v in d:
            return d
    return None


def _cities_list() -> str:
    return ", ".join(c.title() for c in _CITY_INFO)


def _codes_list() -> str:
    return ", ".join(_AIRPORTS.keys())


def _districts_list() -> str:
    return ", ".join(d.title() for d in _DISTRICTS)


def _districts_of(city_key: str) -> List[str]:
    return [d for d, info in _DISTRICTS.items() if info["city"] == city_key]


def _currency_of_city(city_key: str) -> str:
    return _CITY_INFO[city_key]["currency"]


def _currency_of_district(district_key: str) -> str:
    return _currency_of_city(_DISTRICTS[district_key]["city"])


def _money(amount, currency: str) -> str:
    return f"€{amount}" if currency == "EUR" else f"{amount} {currency}"


# ---------------------------------------------------------------------------
# Read-only views of the dataset (for the "Data" tab in the UI)
# ---------------------------------------------------------------------------
def dataset_tables() -> Dict[str, List[dict]]:
    """Return the whole fixed dataset as plain rows, ready to show as tables.

    The tables are deliberately keyed on DIFFERENT columns (city, airport code,
    district) so the participant can see that linking two facts often needs a
    hop through a bridge table — exactly what the agent must do with tools.
    """
    cities = [
        {
            "City": c.title(),
            "Country": _CITY_INFO[c]["country"],
            "Airport": _CITY_INFO[c]["airport"],
            "Currency": _CITY_INFO[c]["currency"],
        }
        for c in _CITY_INFO
    ]

    temperature = [
        {"City": c.title(), "Now (°C)": _WEATHER[c], "Avg (°C)": _CLIMATE_AVG[c]}
        for c in _WEATHER
    ]

    conditions = [
        {
            "City": c.title(),
            "Rain (%)": _CONDITIONS[c]["rain"],
            "Sunrise": _CONDITIONS[c]["sunrise"],
            "Sunset": _CONDITIONS[c]["sunset"],
        }
        for c in _WEATHER
    ]

    # Keyed by AIRPORT — note there is NO city column here.
    flights = [
        {
            "Airport": code,
            "Round-trip €": info["oneway"] * 2,
            "One-way €": info["oneway"],
            "Flight time": info["duration"],
            "Flights/day": len(_SCHEDULE[code]),
        }
        for code, info in _AIRPORTS.items()
    ]

    points = ["HOME"] + list(_AIRPORTS.keys())
    legs = []
    seen = set()
    for a in points:
        for b in points:
            if a == b:
                continue
            key = _leg_key(a, b)
            if key in seen or key not in _LEGS:
                continue
            seen.add(key)
            price, dur = _LEGS[key]
            legs.append({"From": a, "To": b, "€": price, "Time": dur})

    schedule = [
        {"Airport": code, "Route": f"Home→{code}", "Departs": dep,
         "Arrives": arr, "Time": dur}
        for code, deps in _SCHEDULE.items()
        for dep, arr, dur in deps
    ]

    # The district bridge table — the ONLY link from district back to city.
    districts = [
        {
            "District": d.title(),
            "City": info["city"].title(),
            "Airport→district (min)": info["airport_min"],
        }
        for d, info in _DISTRICTS.items()
    ]

    # Keyed by DISTRICT — note there is NO city column here. Prices are in the
    # city's LOCAL currency, so the currency column matters for any total.
    hotels = [
        {
            "District": d.title(), "Hotel": name,
            "Price/night": price, "Currency": _currency_of_district(d),
            "Rating": rating,
        }
        for d, rows in _HOTELS.items()
        for name, price, rating in rows
    ]

    activities = [
        {
            "District": d.title(), "Activity": name,
            "Price": price, "Currency": _currency_of_district(d),
        }
        for d, rows in _ACTIVITIES.items()
        for name, price in rows
    ]

    exchange = [
        {"Currency": cur, "Per 1 EUR": per, "1 unit in EUR": round(1.0 / per, 4)}
        for cur, per in _EXCHANGE_PER_EUR.items()
    ]

    return {
        "Cities (city → airport, currency)": cities,
        "City temperature": temperature,
        "City conditions": conditions,
        "Flights (by airport, EUR)": flights,
        "Flight legs (by airport, EUR)": legs,
        "Departures (by airport)": schedule,
        "Districts (district → city)": districts,
        "Hotels (by district, local currency)": hotels,
        "Activities (by district, local currency)": activities,
        "Exchange rates": exchange,
    }


# ---------------------------------------------------------------------------
# Tool implementations (each returns a plain string the model reads)
# ---------------------------------------------------------------------------
# ----- Directory / join tools ---------------------------------------------
def _impl_get_airport_code(city=None, **_) -> str:
    key = _resolve_city(city)
    if key is None:
        return _err(
            f"no airport for '{city}'. Covered cities: {_cities_list()}. Do not guess."
        )
    info = _CITY_INFO[key]
    return f"{key.title()} ({info['country']}) uses airport {info['airport']}"


def _impl_list_districts(city=None, **_) -> str:
    key = _resolve_city(city)
    if key is None:
        return _err(f"no districts for '{city}'. Cities: {_cities_list()}.")
    ds = _districts_of(key)
    return f"{key.title()} districts: {', '.join(d.title() for d in ds)}"


def _impl_get_district(district=None, **_) -> str:
    d = _resolve_district(district)
    if d is None:
        return _err(
            f"'{district}' is not a known district. Known districts: {_districts_list()}."
        )
    info = _DISTRICTS[d]
    return (
        f"{d.title()} is in {info['city'].title()}, "
        f"{info['airport_min']} min from the airport"
    )


def _impl_get_currency(city=None, **_) -> str:
    key = _resolve_city(city)
    if key is None:
        return _err(f"no currency for '{city}'. Cities: {_cities_list()}.")
    cur = _CITY_INFO[key]["currency"]
    note = ("same as home" if cur == "EUR"
            else "NOT euros — convert to EUR before comparing or summing")
    return (
        f"{key.title()} ({_CITY_INFO[key]['country']}) prices local hotels and "
        f"activities in {cur} ({note})"
    )


def _impl_get_exchange_rate(from_currency=None, to_currency=None, **_) -> str:
    a = str(from_currency or "").strip().upper()
    b = str(to_currency or "").strip().upper()
    if a not in _EXCHANGE_PER_EUR or b not in _EXCHANGE_PER_EUR:
        return _err(
            f"unknown currency. Known currencies: {', '.join(_EXCHANGE_PER_EUR)}."
        )
    rate = round(_EXCHANGE_PER_EUR[b] / _EXCHANGE_PER_EUR[a], 4)
    return f"1 {a} = {rate} {b} (multiply a {a} amount by {rate} to get {b})"


# ----- Weather (keyed by city) --------------------------------------------
def _impl_get_weather(city=None, **_) -> str:
    key = _resolve_city(city)
    if key is None:
        return _err(
            f"no current weather for '{city}'. Covered cities: {_cities_list()}. "
            "Do not guess."
        )
    return f"{_WEATHER[key]}°C right now in {key.title()}"


def _impl_get_conditions(city=None, **_) -> str:
    key = _resolve_city(city)
    if key is None:
        return _err(
            f"no conditions for '{city}'. Covered cities: {_cities_list()}. "
            "Do not guess."
        )
    c = _CONDITIONS[key]
    return (
        f"{key.title()} today: {c['rain']}% chance of rain, "
        f"sunrise {c['sunrise']}, sunset {c['sunset']} "
        "(does NOT include temperature — use get_weather for that)"
    )


def _impl_get_climate_average(city=None, month=None, **_) -> str:
    key = _resolve_city(city)
    if key is None:
        return _err(
            f"no climate data for '{city}'. Covered cities: {_cities_list()}."
        )
    m = str(month).strip().title() if month else "the year"
    return (
        f"Historical average for {key.title()} in {m}: {_CLIMATE_AVG[key]}°C "
        "(long-term average, NOT today's weather)"
    )


# ----- Flights (keyed by airport code) ------------------------------------
def _impl_get_flight(airport=None, **_) -> str:
    code = _resolve_airport(airport)
    if code is None:
        return _err(
            f"'{airport}' is not an airport code. Flights are keyed by code "
            f"({_codes_list()}), not city names — use get_airport_code(city) "
            "to translate a city first."
        )
    info = _AIRPORTS[code]
    return f"Round-trip Home↔{code}: €{info['oneway'] * 2}, {info['duration']} each way"


def _impl_get_one_way_fare(airport=None, **_) -> str:
    code = _resolve_airport(airport)
    if code is None:
        return _err(
            f"'{airport}' is not an airport code. Fares are keyed by code "
            f"({_codes_list()}) — use get_airport_code(city) first."
        )
    return f"One-way Home→{code}: €{_AIRPORTS[code]['oneway']} (single ticket, no return leg)"


def _impl_get_flight_leg(origin=None, destination=None, **_) -> str:
    a, b = _norm(origin), _norm(destination)
    if not a or not b:
        return _err("provide both 'origin' and 'destination' as airport codes or Home.")
    ra = "HOME" if a == "home" else _resolve_airport(origin)
    rb = "HOME" if b == "home" else _resolve_airport(destination)
    if ra is None or rb is None:
        return _err(
            f"legs are keyed by airport code. Points: Home, {_codes_list()}. "
            "Use get_airport_code(city) to translate a city name."
        )
    leg = _LEGS.get(_leg_key(ra, rb))
    if leg is None:
        return _err(f"no direct flight between {ra} and {rb}.")
    price, dur = leg
    return f"{ra}→{rb}: €{price}, {dur}"


def _impl_get_flight_schedule(airport=None, **_) -> str:
    code = _resolve_airport(airport)
    if code is None:
        return _err(
            f"'{airport}' is not an airport code. Schedules are keyed by code "
            f"({_codes_list()}) — use get_airport_code(city) first."
        )
    deps = "; ".join(f"{dep}→{arr} ({dur})" for dep, arr, dur in _SCHEDULE[code])
    return f"Departures Home→{code}: {deps}"


# ----- Hotels (keyed by district) -----------------------------------------
def _impl_list_hotels(district=None, **_) -> str:
    d = _resolve_district(district)
    if d is None:
        return _err(
            f"'{district}' is not a known district. Hotels are listed by district, "
            "not city — use list_districts(city) to find a city's districts. "
            f"Districts: {_districts_list()}."
        )
    cur = _currency_of_district(d)
    rows = " | ".join(
        f"{name} {_money(price, cur)}/night, {rating}★"
        for name, price, rating in _HOTELS[d]
    )
    return f"{d.title()} hotels: {rows}"


def _impl_get_hotel(hotel=None, **_) -> str:
    want = _norm(hotel)
    if not want:
        return _err("provide a hotel name, e.g. 'Soho Central'.")
    for d, rows in _HOTELS.items():
        for name, price, rating in rows:
            if want in name.lower() or name.lower() in want:
                city = _DISTRICTS[d]["city"]
                return (
                    f"{name} ({d.title()}, {city.title()}): "
                    f"{_money(price, _currency_of_district(d))}/night, "
                    f"rated {rating}/5"
                )
    names = ", ".join(n for rows in _HOTELS.values() for n, *_ in rows)
    return _err(f"no hotel matching '{hotel}'. Hotels: {names}.")


def _impl_find_hotels_in_budget(district=None, max_price=None, **_) -> str:
    d = _resolve_district(district)
    if d is None:
        return _err(
            f"'{district}' is not a known district. Filter by district — use "
            f"list_districts(city) first. Districts: {_districts_list()}."
        )
    try:
        cap = float(str(max_price).replace("€", "").strip())
    except (TypeError, ValueError):
        return _err("provide a numeric 'max_price', e.g. 120.")
    cur = _currency_of_district(d)
    matches = [
        (name, price, rating)
        for name, price, rating in _HOTELS[d]
        if price <= cap
    ]
    if not matches:
        return _err(f"no {d.title()} hotels under {_money(int(cap), cur)}.")
    rows = " | ".join(f"{n} {_money(p, cur)}/night, {r}★" for n, p, r in matches)
    return f"{d.title()} hotels under {_money(int(cap), cur)}: {rows}"


# ----- Activities (keyed by district) -------------------------------------
def _impl_get_activity_price(activity=None, **_) -> str:
    want = _norm(activity)
    if not want:
        return _err("provide an activity name, e.g. 'Castle tour'.")
    for d, items in _ACTIVITIES.items():
        for name, price in items:
            if want in name.lower() or name.lower() in want:
                return f"{name} ({d.title()}) costs {_money(price, _currency_of_district(d))}"
    return _err(f"no activity matching '{activity}'. Try list_activities for a district.")


def _impl_list_activities(district=None, **_) -> str:
    d = _resolve_district(district)
    if d is None:
        return _err(
            f"'{district}' is not a known district. Activities are listed by "
            "district, not city — use list_districts(city) first. "
            f"Districts: {_districts_list()}."
        )
    items = _ACTIVITIES.get(d, [])
    if not items:
        return f"{d.title()} has no listed activities."
    cur = _currency_of_district(d)
    rows = ", ".join(f"{name} {_money(price, cur)}" for name, price in items)
    return f"{d.title()} activities: {rows}"


# ----- Cost / bundling -----------------------------------------------------
def _impl_get_trip_cost(city=None, nights=None, **_) -> str:
    key = _resolve_city(city)
    if key is None:
        return _err(f"no trip data for '{city}'. Cities: {_cities_list()}.")
    try:
        n = int(float(str(nights).strip()))
    except (TypeError, ValueError):
        return _err("provide a numeric number of 'nights', e.g. 4.")
    code = _CITY_INFO[key]["airport"]
    flight = _AIRPORTS[code]["oneway"] * 2
    first_district = _districts_of(key)[0]           # silently picks a district
    hotel_name, hotel_price, _r = _HOTELS[first_district][0]  # and a hotel
    cur = _currency_of_city(key)
    total = flight + hotel_price * n  # BUG: adds EUR flight to local-currency hotel
    return (
        f"{key.title()} {n} nights: €{total} "
        f"(round-trip flight + {hotel_name} at {_money(hotel_price, cur)}/night; "
        "currencies not converted; activities not included)"
    )


# ----- calculator (safe arithmetic, no eval) -------------------------------
_ALLOWED = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow, ast.Mod: op.mod, ast.USub: op.neg, ast.UAdd: op.pos,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED:
        return _ALLOWED[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED:
        return _ALLOWED[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


def _impl_calculator(expression=None, **_) -> str:
    if not str(expression or "").strip():
        return _err("no expression. Pass something like '180 + 4*140 + 30'.")
    try:
        result = _safe_eval(ast.parse(str(expression), mode="eval").body)
    except Exception:
        return _err(
            f"'{expression}' is not valid. Use numbers and + - * / ** % and "
            "parentheses."
        )
    return str(int(result)) if result == int(result) else f"{round(result, 2)}"


def _impl_get_checkin_rule(**_) -> str:
    return (
        f"Be at the airport {_CHECKIN_MINUTES} minutes before departure for "
        "these routes."
    )


def _impl_plan_vacation(city=None, **_) -> str:
    key = _resolve_city(city)
    if key is None:
        return _err(f"no data for '{city}'. Cities: {_cities_list()}.")
    weather = _WEATHER[key]
    code = _CITY_INFO[key]["airport"]
    flight = _AIRPORTS[code]["oneway"] * 2
    dur = _AIRPORTS[code]["duration"]
    dists = _districts_of(key)
    cur = _currency_of_city(key)
    hotels = ", ".join(
        f"{n} {_money(p, cur)} {r}★" for d in dists for n, p, r in _HOTELS.get(d, [])
    )
    acts = ", ".join(
        f"{n} {_money(p, cur)}" for d in dists for n, p in _ACTIVITIES.get(d, [])
    )
    return (
        f"{key.title()}: {weather}°C; flight round-trip €{flight}/{dur}; "
        f"hotels: {hotels}; activities: {acts} "
        f"(hotel/activity prices in {cur}, flight in EUR)"
    )


# ===========================================================================
# The catalog: fixed, self-describing tools the participant toggles
# ===========================================================================
@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    group: str
    quality: str                       # good | decoy | god (internal, not shown)
    description: str                    # what · scope/limits · example → return
    params: Tuple[Tuple[str, str], ...]  # (param_name, param_hint)
    impl: Callable[..., str]


CATALOG: Tuple[ToolSpec, ...] = (
    # ----- Directory (the join / bridge tools) ----------------------------
    ToolSpec(
        "get_airport_code", "get_airport_code", "Directory", "good",
        "Translate a city name into its airport CODE and country. Flights are "
        "keyed by airport code (BCN, PRG, LHR, ZRH, IST, BUD), not by city, so "
        "call this first to turn a city into the code the flight tool needs. "
        "Example: get_airport_code('Barcelona') → 'Barcelona (Spain) uses airport BCN'.",
        (("city", "A single city, e.g. 'Barcelona'."),),
        _impl_get_airport_code,
    ),
    ToolSpec(
        "list_districts", "list_districts", "Directory", "good",
        "List the DISTRICTS that make up a city. Hotels and activities are keyed "
        "by district, not city, so use this to find a city's districts before "
        "looking them up. "
        "Example: list_districts('Barcelona') → 'Barcelona districts: Eixample, Gothic Quarter, Barceloneta'.",
        (("city", "A single city name."),),
        _impl_list_districts,
    ),
    ToolSpec(
        "get_district", "get_district", "Directory", "good",
        "Given a DISTRICT, return which city it belongs to and how many minutes "
        "it is from that city's airport — the bridge from a district back to its "
        "city and its transfer time. "
        "Example: get_district('Soho') → 'Soho is in London, 45 min from the airport'.",
        (("district", "A single district name."),),
        _impl_get_district,
    ),
    ToolSpec(
        "get_currency", "get_currency", "Directory", "good",
        "Which CURRENCY a city quotes its local hotel and activity prices in. "
        "The cities are in different countries, so not every price is in euros — "
        "check this before comparing or adding up local costs. "
        "Example: get_currency('Prague') → 'Prague (Czechia) prices local hotels and activities in CZK ...'.",
        (("city", "A single city name."),),
        _impl_get_currency,
    ),
    # ----- Weather (keyed by city) ----------------------------------------
    ToolSpec(
        "get_weather", "get_weather", "Weather", "good",
        "Current temperature for one destination city, right now. Covers only "
        "Barcelona, Prague, London, Zurich, Istanbul, Budapest. No forecast. "
        "Example: get_weather('Barcelona') → '26°C right now in Barcelona'.",
        (("city", "A single city, e.g. 'Barcelona'."),),
        _impl_get_weather,
    ),
    ToolSpec(
        "get_climate_average", "get_climate_average", "Weather", "decoy",
        "Historical AVERAGE temperature for a city in a given month — long-term "
        "climate, not today's weather. "
        "Example: get_climate_average('Barcelona','July') → 'avg 28°C in July'.",
        (("city", "A city name."), ("month", "A month, e.g. 'July'.")),
        _impl_get_climate_average,
    ),
    # ----- Flights (keyed by airport code) --------------------------------
    ToolSpec(
        "get_flight", "get_flight", "Flights", "good",
        "Round-trip airfare and flight duration from home to one AIRPORT (by "
        "code, e.g. BCN). It rejects city names — get the code from "
        "get_airport_code first. "
        "Example: get_flight('PRG') → 'Round-trip Home↔PRG: €90, 1h10 each way'.",
        (("airport", "An airport code, e.g. BCN, ZRH, LHR."),),
        _impl_get_flight,
    ),
    # ----- Hotels (keyed by district) -------------------------------------
    ToolSpec(
        "list_hotels", "list_hotels", "Hotels", "good",
        "ALL hotels in one DISTRICT with price per night and rating — use it to "
        "compare or pick a hotel. Keyed by district, not city: use "
        "list_districts first. "
        "Example: list_hotels('Soho') → 'Soho Central 175 GBP/night, 4.2★'.",
        (("district", "A single district name."),),
        _impl_list_hotels,
    ),
    # ----- Activities (keyed by district) ---------------------------------
    ToolSpec(
        "list_activities", "list_activities", "Activities", "good",
        "ALL activities in a DISTRICT with prices — use it for 'what can I do' or "
        "'cheapest activity' questions. Keyed by district, not city: use "
        "list_districts first. "
        "Example: list_activities('Old Town') → 'River cruise 550 CZK, Beer tasting 450 CZK'.",
        (("district", "A single district name."),),
        _impl_list_activities,
    ),
    # ----- Cost / bundling ------------------------------------------------
    ToolSpec(
        "get_trip_cost", "get_trip_cost", "Cost", "decoy",
        "Convenience bundle: round-trip flight plus hotel × nights for a city. "
        "It PICKS a district and hotel for you, EXCLUDES activities, and does NOT "
        "convert currencies — so its total is wrong for a city that prices hotels "
        "in a non-euro currency. "
        "Example: get_trip_cost('Prague', 5) → 'Prague 5 nights: €9465'.",
        (("city", "A single city name."), ("nights", "Number of nights, e.g. 5.")),
        _impl_get_trip_cost,
    ),
    ToolSpec(
        "get_exchange_rate", "get_exchange_rate", "Cost", "good",
        "Convert between currencies: how much 1 unit of one currency is worth in "
        "another. Flights are always in EUR, but some cities price hotels and "
        "activities in their own currency (e.g. Prague in CZK), so convert those "
        "to EUR before adding everything up. "
        "Example: get_exchange_rate('CZK','EUR') → '1 CZK = 0.04 EUR ...'.",
        (("from_currency", "Source currency code, e.g. 'CZK'."),
         ("to_currency", "Target currency code, e.g. 'EUR'.")),
        _impl_get_exchange_rate,
    ),
    ToolSpec(
        "calculator", "calculator", "Cost", "good",
        "MANDATORY arithmetic tool: use this for every sum, total, difference, "
        "comparison, percentage, or any numeric calculation. Never do arithmetic "
        "in your head, never produce a numeric answer without calling this tool, "
        "and never reason through raw math when a calculator call would answer it. "
        "Example: calculator('210 + 5*110 + 35') → '795'.",
        (("expression", "Numbers with + - * / ** % and parentheses."),),
        _impl_calculator,
    ),
)

CATALOG_BY_ID: Dict[str, ToolSpec] = {t.id: t for t in CATALOG}

# The groups, in display order.
GROUPS: Tuple[str, ...] = ("Directory", "Weather", "Flights", "Hotels",
                           "Activities", "Cost")

# Starting (broken) selection: only the convenient-but-wrong bundle is on.
BROKEN_ENABLED = frozenset({"get_trip_cost"})

# Presenter's reference selection: the good primitives, no decoys, no god tool.
REFERENCE_ENABLED = frozenset({
    "get_airport_code", "list_districts", "get_district", "get_currency",
    "get_weather", "get_flight", "list_hotels", "list_activities",
    "get_exchange_rate", "calculator",
})


# ---------------------------------------------------------------------------
# Building real tools from the enabled selection
# ---------------------------------------------------------------------------
def build_tool(spec: ToolSpec, description: str = None):
    """Turn one ``ToolSpec`` into a LangChain ``StructuredTool``.

    ``description`` overrides the spec's default text when provided, so the
    workshop UI can let participants rewrite what the agent actually sees.
    """
    from pydantic import Field, create_model
    from langchain_core.tools import StructuredTool

    field_defs = {
        pname: (str, Field(description=phint)) for pname, phint in spec.params
    }
    # Always build an explicit schema (empty for no-arg tools) so a tool with no
    # parameters does not accidentally expose the internal **kwargs slot.
    args_schema = create_model(f"{spec.id}_Args", **field_defs)

    def _run(**kwargs):
        return spec.impl(**kwargs)

    text = description if description is not None else spec.description
    if not str(text).strip():
        text = spec.description

    return StructuredTool.from_function(
        func=_run,
        name=spec.name,
        description=text,
        args_schema=args_schema,
    )


def build_toolbox(enabled_ids, descriptions: Dict[str, str] = None) -> Tuple[list, Dict[str, str]]:
    """Build every enabled tool plus a ``tool name → group`` map for the trace.

    ``descriptions`` optionally maps a tool id to a participant-edited
    description; enabled tools without an entry fall back to their default.
    """
    descriptions = descriptions or {}
    tools, meta = [], {}
    for spec in CATALOG:
        if spec.id in enabled_ids:
            tools.append(build_tool(spec, descriptions.get(spec.id)))
            meta[spec.name] = spec.group
    return tools, meta
