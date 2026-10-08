"""Ticketmaster Discovery API adapter: live events near a supported NYC neighborhood.

Needs TICKETMASTER_API_KEY (see .env.example). Every failure comes back as
ok=False with a `fix` the model can act on; nothing here raises.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Callable

import requests

from integrations.places import SUPPORTED_NEIGHBORHOODS, load_local_places, normalize_neighborhood

EVENTS_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


def _center(neighborhood: str) -> tuple[float, float] | None:
    """Middle of the curated places in that neighborhood."""
    points = [(r.candidate.lat, r.candidate.lng) for r in load_local_places()
              if r.neighborhood == neighborhood and r.candidate.lat is not None]
    if not points:
        return None
    return mean(p[0] for p in points), mean(p[1] for p in points)


def _event_view(e: dict[str, Any]) -> dict[str, Any]:
    start = e.get("dates", {}).get("start", {})
    venue = (e.get("_embedded", {}).get("venues") or [{}])[0]
    prices = e.get("priceRanges") or []
    genres = {c.get(k, {}).get("name") for c in e.get("classifications", [])
              for k in ("segment", "genre")}
    return {
        "name": e.get("name", ""),
        "date": start.get("localDate"),
        "time": start.get("localTime"),
        "venue": venue.get("name"),
        "address": (venue.get("address") or {}).get("line1"),
        "distance_miles": e.get("distance"),
        "category": ", ".join(sorted(g for g in genres if g and g != "Undefined")),
        "min_price": prices[0].get("min") if prices else None,
        "url": e.get("url"),
    }


def search_events(neighborhood: str, keyword: str | None = None, hours_ahead: int = 12,
                  max_results: int = 5, *, api_key: str | None = None,
                  http_get: Callable[..., Any] | None = None) -> dict[str, Any]:
    key = api_key or os.getenv("TICKETMASTER_API_KEY")
    if not key:
        return {"ok": False, "error": "Live events are not configured (no TICKETMASTER_API_KEY).",
                "fix": "Build the SideQuest without events and tell the user live events are off."}
    canonical = normalize_neighborhood(neighborhood)
    if canonical is None:
        supported = ", ".join(sorted(set(SUPPORTED_NEIGHBORHOODS.values())))
        return {"ok": False, "error": f"Unsupported NYC neighborhood: {neighborhood!r}.",
                "fix": f"Use one of: {supported}."}
    center = _center(canonical)
    hours = max(1, min(int(hours_ahead), 72))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    params: dict[str, Any] = {
        "apikey": key,
        "size": max(1, min(int(max_results), 10)),
        "sort": "date,asc",
        "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if center:
        params.update(latlong=f"{center[0]:.4f},{center[1]:.4f}", radius=1, unit="miles")
    else:
        params.update(city="New York", countryCode="US")
    if keyword and keyword.strip():
        params["keyword"] = keyword.strip()

    try:
        response = (http_get or requests.get)(EVENTS_URL, params=params, timeout=8)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Couldn't reach Ticketmaster: {type(exc).__name__}.",
                "fix": "Try once more; if it fails again, build the SideQuest without events."}
    if response.status_code in (401, 403):
        return {"ok": False, "error": "Ticketmaster rejected the API key.",
                "fix": "Build the SideQuest without events and tell the user live events are unavailable."}
    if response.status_code == 429:
        return {"ok": False, "error": "Ticketmaster rate limit reached.",
                "fix": "Build the SideQuest without events for now."}
    try:
        response.raise_for_status()
        events = response.json().get("_embedded", {}).get("events", [])
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": f"Ticketmaster returned an unexpected response: {exc}",
                "fix": "Build the SideQuest without events."}

    out: dict[str, Any] = {"ok": True, "neighborhood": canonical, "hours_ahead": hours,
                           "events": [_event_view(e) for e in events]}
    if not events:
        out["note"] = (f"No events in the next {hours} hours within a mile of {canonical}"
                       + (f" matching {keyword!r}" if keyword else "") + ". "
                       "Try without a keyword or with more hours_ahead, or skip events.")
    return out
