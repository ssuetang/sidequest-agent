# Day as Someone — Architecture

## Main Components

### App / Orchestrator

Coordinates the feature pipelines and passes structured state between them.

Location:

`app/`

### Reality / Places

Responsible for place discovery, real-world constraints, and feasibility.

Planned files: `tools/reality/match_theme.py`, `api/places.py`, `frontend/places.html`

### Story / Experience

Responsible for transforming viable places into a coherent SideQuest experience.

Owned files: `tools/story/build_sidequest.py`, `api/events.py`, `frontend/sidequest.html`

### Adaptation / Memory

Responsible for session state and repairing an active SideQuest when conditions change.

Planned files: `tools/adaptation/repair_sidequest.py`, `api/weather.py`, `frontend/repair.html`

## Shared Contracts

Proposed flow:

UserRequest
→ PlaceCandidate[]
→ SideQuest
→ QuestState
→ Repaired SideQuest

The Story pipeline returns a validated `SideQuest`; the other contracts can evolve while these ownership boundaries stay stable.

## Integration Boundary

External services should be isolated under:

`integrations/`

The three feature pipelines should not directly depend on provider SDKs.

## Orchestration

Preferred structure:

app/orchestrator
├── Reality pipeline
├── Story pipeline
└── Adaptation pipeline

The three original tools do not need to call each other directly.

## Open Decisions

- Shared schemas
- State persistence
- Places provider
- Weather integration
- Routing strategy
- LLM boundary
- Frontend
- Error / fallback contract
