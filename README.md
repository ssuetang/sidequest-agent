# Day as Someone

### A SideQuest Agent for turning a personal into a playable real-world adventure.

**What if you could spend a day living as someone else?**

Day as Someone turns a persona, your available time, location, and real-world constraints into a playable, chapter-based adventure in the real world.

Pick a persona. Step into a story. See where the day takes you.

## How it works

Three specialized agents work together to turn an idea into a real-world quest.

Reality Agent — Finds and ranks real-world places that fit your persona, preferences, and constraints.

Story Agent — Weaves those places into a chaptered quest, turning an ordinary day into an adventure.

Adaptation Agent — Keeps the quest playable when plans change, adapting to new constraints and circumstances.

The journey follows a simple flow:

Reality → Story → Adaptation

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

Deployed agent: `https://your-service-xxxxx.run.app`