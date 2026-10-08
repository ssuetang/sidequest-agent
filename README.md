# Day as Someone

## A SideQuest Agent for turning a persona into a playable real-world adventure.

**What if you could spend a day living as someone else?**

Day as Someone turns a persona, your available time, location, and real-world constraints into a playable, chapter-based adventure in the real world.

Pick a persona. Step into a story. See where the day takes you.

## How it works

Three specialized tool groups work together to turn an idea into a real-world adventure.

* **Reality** - [search_places](docs/tools/search_places.md) lists local places and [match_theme](docs/tools/match_theme.md) ranks them for your persona.

* **Story** - [find_events](docs/tools/find_events.md) adds timely events, and [build_sidequest](docs/tools/build_sidequest.md) weaves places into a chaptered quest, turning an ordinary day into an adventure.

* **Adaptation** - [get_current_sidequest](docs/tools/get_current_sidequest.md) recalls the active plan, [get_weather](docs/tools/get_weather.md) checks conditions, and [repair_sidequest](docs/tools/repair_sidequest.md) adjusts the route when plans change.

The journey follows a simple flow:

`Reality → Story → Adaptation`

## Sample grader queries

1. Plan a two-hour SideQuest as an urban detective in Chinatown.
2. Will it rain near my next stop?
3. The gallery is closed and it's raining. Keep the novelist theme.

## Run locally

```bash
uv run python -m app.main
```

Open <http://localhost:8000>. This address is only for local development; the
grader needs the public Cloud Run URL.

Run tests with:

```bash
uv run pytest
```

Set `SIDEQUEST_USE_MODEL=0` for the deterministic local fallback. Gemini and
optional live place/event data require the credentials described in
[.env.example](.env.example).

## Deployment

Refer to [this link](submission.json)