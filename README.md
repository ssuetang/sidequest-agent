# Day as Someone

Repository: `sidequest-agent`

Day as Someone is an agentic experience that turns a user's available time, location, constraints, and chosen persona or theme into a real-world SideQuest.

> Current stage: Reality, Story, and Adaptation feature slices are implemented; end-to-end integration remains.

## Run the Story starter

The Story / Experience pipeline is available at `/api/events` with a browser
frontend at `/`. It accepts a request, theme, available minutes, and optional
viable places, then returns a validated, ordered SideQuest with chapters,
narrative prompts, micro-tasks, time allocation, and budget estimates. It uses
the Gemini tool-calling loop when configured and falls back to a deterministic
local builder when the model is unavailable. Ticketmaster event enrichment is
optional and only runs when `TICKETMASTER_API_KEY` is configured.

```bash
python -m pip install -e .
SIDEQUEST_USE_MODEL=0 python app.py
```

Open `http://127.0.0.1:8000`. To enable Gemini, authenticate with Application
Default Credentials and omit `SIDEQUEST_USE_MODEL=0`. To enable optional live
events, set `TICKETMASTER_API_KEY` and check the events option in the UI.

For local Ticketmaster configuration:

```bash
cp .env.example .env
```

Add your Ticketmaster developer key to `.env`. The `.gitignore` excludes `.env`
and other secret environment files, while `.env.example` remains safe to commit.

The Reality pipeline supports Morningside Heights, Greenwich Village,
Chinatown, and DUMBO. It works from the curated `data/nyc_places.json` dataset
without credentials. Set `GOOGLE_MAPS_API_KEY` to add live Google Places Text
Search results; failures automatically fall back to the curated dataset.

Reality includes twenty curated personas: struggling novelist, urban detective,
indie filmmaker, architecture apprentice, city naturalist, and independent
magazine editor, plus jazz age drifter, street photographer, hidden history
archivist, thrift fashion scout, neighborhood food chronicler, and waterfront
poet, campus intellectual, avant garde theater actor, urban sketch artist,
community radio producer, romantic city wanderer, industrial design student,
museum time traveler, and midnight mystery writer. Other personas are also accepted: the model translates them
into a controlled place-tag vocabulary, and `match_theme` performs the final
deterministic, explainable scoring. Unknown tags are ignored rather than being
used to invent unsupported place attributes.

## Product Concept

A user asks for a temporary way to experience their city "as someone" — a persona, archetype, fictional lens, mood, or theme.

Example:

"I have 3 hours in NYC. Give me a day as a 90s indie filmmaker."

High-level flow:

User Request
→ Interpret theme + constraints
→ Find viable real-world places
→ Build a connected SideQuest
→ Present itinerary + narrative + micro-tasks
→ Adapt when conditions change

## Three-Person Ownership

| Person | Main files | Original tool |
|---|---|---|
| A — Reality / Places | `tools/reality/match_theme.py`, `tools/reality/tools.py`, `integrations/places.py` | `match_theme` |
| B — Story / Experience | `tools/story/build_sidequest.py`, `api/events.py`, `frontend/sidequest.html` | `build_sidequest` |
| C — Adaptation / Memory | `tools/adaptation/repair_sidequest.py`, `api/weather.py`, `frontend/repair.html` | `repair_sidequest` |

Each person owns one original tool, its API boundary, and a small frontend surface.

## Running Locally

Built on the course's `gemini-web-tool-calling` starter (FastAPI + LiteLLM + Gemini on Vertex AI).

1. A GCP project with billing and the Vertex AI / Agent Platform API enabled
2. `gcloud auth application-default login`
3. From the repo root: `uv run python -m app.main`, then open http://localhost:8000

Tests: `uv run pytest`

To add a pipeline's tools, give it a `tools.py` with `TOOLS`, `TOOL_FUNCTIONS` and
`run_tool(name, args, session_id)` (see `tools/adaptation/tools.py`) and register it in
`app/tools.py`.

## Repository Structure

sidequest-agent/
├── tools/
│   ├── reality/          # A's match_theme + tool registry
│   ├── story/build_sidequest.py
│   └── adaptation/       # C's planned tool
├── api/
│   └── events.py
├── frontend/
│   └── sidequest.html
├── app.py
├── app/                 # future orchestrator modules
├── integrations/       # provider adapters
├── state/               # shared session state
├── data/                # local/demo data
├── tests/
└── docs/

## Architecture

The three feature pipelines remain independently testable and communicate through shared structured data.

User Input
→ App / Orchestrator
→ Reality / Places
→ Story / Experience
→ Shared SideQuest State
→ Adaptation when needed
→ User Experience

## Shared Data Contracts

Before implementing tools, the team should agree on shared objects such as:

- UserRequest
- PlaceCandidate
- SideQuest
- QuestState
- RepairContext

The Story starter currently returns a structured `SideQuest`; the remaining shared schemas can be refined without changing the ownership boundaries.

## Integration Layer

Provider-specific code should live under `integrations/`.

Possible integrations:

- Places / Maps API
- Weather
- Routing / Transit
- LLM provider
- Persistence / session storage

## Development Phases

### Phase 1 — Structure

- [x] Create repository
- [x] Define project concept
- [x] Define three feature pipelines
- [x] Create repository structure
- [x] Define feature ownership files
- [ ] Define integration interfaces

### Phase 2 — Feature Pipelines

- [x] Reality / Places implementation (A)
- [x] Story / Experience implementation
- [ ] Adaptation / Memory implementation (C)
- [x] Story / Experience unit and API tests

### Phase 3 — Integration

- [ ] Build orchestrator
- [ ] Connect shared state
- [ ] Test end-to-end SideQuest creation
- [ ] Test SideQuest repair

### Phase 4 — Demo

- [ ] Add user-facing interface
- [ ] Add demo scenarios
- [ ] Add fallbacks
- [ ] Prepare final demo
