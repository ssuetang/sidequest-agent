"""Google Places adapter with a deterministic local NYC fallback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from tools.adaptation.schemas import PlaceCandidate

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "nyc_places.json"
SUPPORTED_NEIGHBORHOODS = {
    "morningside heights": "Morningside Heights", "morningside": "Morningside Heights",
    "greenwich village": "Greenwich Village", "the village": "Greenwich Village",
    "village": "Greenwich Village", "chinatown": "Chinatown", "dumbo": "DUMBO",
}


@dataclass
class PlaceRecord:
    candidate: PlaceCandidate
    neighborhood: str
    category: str
    address: str = ""
    source: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        p = self.candidate
        return {"place_id": p.place_id, "name": p.name, "address": self.address,
                "neighborhood": self.neighborhood, "category": self.category,
                "tags": p.tags, "indoor": p.indoor, "latitude": p.lat,
                "longitude": p.lng, "estimated_cost": p.est_cost, "rating": p.rating,
                "open_now": p.open_now, "source": self.source}


@dataclass
class PlaceSearchResult:
    ok: bool
    places: list[PlaceRecord] = field(default_factory=list)
    source: str = "local"
    error: str = ""
    fix: str = ""


def normalize_neighborhood(value: str) -> str | None:
    return SUPPORTED_NEIGHBORHOODS.get(" ".join(str(value).lower().split()))


def load_local_places(path: Path = DATA_FILE) -> list[PlaceRecord]:
    return [_record_from_local(row) for row in json.loads(path.read_text(encoding="utf-8"))]


def search_places(neighborhood: str, categories: list[str] | None = None,
                  max_results: int = 12, *, use_live: bool = True,
                  api_key: str | None = None,
                  http_post: Callable[..., Any] = requests.post) -> PlaceSearchResult:
    canonical = normalize_neighborhood(neighborhood)
    if canonical is None:
        supported = ", ".join(sorted(set(SUPPORTED_NEIGHBORHOODS.values())))
        return PlaceSearchResult(False, error=f"Unsupported NYC neighborhood: {neighborhood!r}.",
                                 fix=f"Choose one of: {supported}.")
    wanted = {str(c).strip().lower() for c in (categories or []) if str(c).strip()}
    local = [p for p in load_local_places() if p.neighborhood == canonical]
    if wanted:
        local = [p for p in local if p.category.lower() in wanted or wanted & set(p.candidate.tags)]
    key = api_key or os.getenv("GOOGLE_MAPS_API_KEY")
    live: list[PlaceRecord] = []
    live_error = ""
    if use_live and key:
        try:
            for query in (sorted(wanted) or ["interesting places"])[:3]:
                live.extend(_google_text_search(query, canonical, key, http_post))
        except (requests.RequestException, ValueError, KeyError) as exc:
            live_error = f"Google Places was unavailable: {exc}"
    merged: dict[str, PlaceRecord] = {}
    for place in live + local:
        merged.setdefault(place.candidate.place_id, place)
    results = list(merged.values())[:max(1, min(int(max_results), 20))]
    if not results:
        return PlaceSearchResult(False, error=f"No places matched the requested categories in {canonical}.",
                                 fix="Remove a category filter or choose another supported neighborhood.")
    return PlaceSearchResult(True, results, "google+local" if live else "local",
                             fix=live_error + ("; used curated fallback." if live_error else ""))


def _record_from_local(row: dict[str, Any]) -> PlaceRecord:
    return PlaceRecord(PlaceCandidate(row["place_id"], row["name"], list(row.get("tags", [])),
        bool(row.get("indoor", True)), row.get("lat"), row.get("lng"), row.get("rating"),
        bool(row.get("open_now", True)), float(row.get("est_cost", 0))), row["neighborhood"],
        row.get("category", "place"), row.get("address", ""))


def _google_text_search(query: str, neighborhood: str, api_key: str,
                        http_post: Callable[..., Any]) -> list[PlaceRecord]:
    response = http_post(PLACES_URL, headers={"Content-Type": "application/json",
        "X-Goog-Api-Key": api_key, "X-Goog-FieldMask":
        "places.id,places.displayName,places.formattedAddress,places.location,places.primaryType,"
        "places.types,places.rating,places.priceLevel,places.currentOpeningHours.openNow"},
        json={"textQuery": f"{query} in {neighborhood}, New York City", "pageSize": 8}, timeout=8)
    response.raise_for_status()
    return [_record_from_google(p, neighborhood, query) for p in response.json().get("places", [])]


def _record_from_google(row: dict[str, Any], neighborhood: str, query: str) -> PlaceRecord:
    types = [str(t).replace("_", "-") for t in row.get("types", [])]
    category = str(row.get("primaryType") or (types[0] if types else "place")).replace("_", "-")
    name = row.get("displayName", {}).get("text") or "Unnamed place"
    loc = row.get("location", {})
    price = {"PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 8,
             "PRICE_LEVEL_MODERATE": 18, "PRICE_LEVEL_EXPENSIVE": 35,
             "PRICE_LEVEL_VERY_EXPENSIVE": 50}.get(row.get("priceLevel"), 0)
    tags = sorted(set(types + [category, query.lower().replace(" ", "-")]))
    outdoor = {"park", "garden", "plaza", "hiking-area", "tourist-attraction"}
    candidate = PlaceCandidate(row.get("id") or f"google-{name.lower().replace(' ', '-')}", name,
        tags, not bool(outdoor & set(tags)), loc.get("latitude"), loc.get("longitude"),
        row.get("rating"), row.get("currentOpeningHours", {}).get("openNow", True), float(price))
    return PlaceRecord(candidate, neighborhood, category, row.get("formattedAddress", ""), "google")
