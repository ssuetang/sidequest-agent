"""Session state and conversation memory for an active SideQuest.

A session holds:
  - the current SideQuest plus every earlier version (for undo / diffing),
  - the spare PlaceCandidates repairs can draw from,
  - the conversation turns,
  - progress (which steps the user has already completed).

Two stores share one interface: `InMemorySessionStore` (default, tests,
demo) and `JsonFileSessionStore` (survives restarts). Swap in a real DB
later by implementing the same three methods.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tools.adaptation.schemas import (
    PlaceCandidate,
    RepairAction,
    SideQuest,
    place_from_dict,
    sidequest_from_dict,
    sidequest_to_dict,
)


@dataclass
class Turn:
    role: str  # "user" | "assistant" | "system"
    text: str
    ts: float = field(default_factory=time.time)


@dataclass
class SessionState:
    session_id: str
    quest: SideQuest
    candidates: list[PlaceCandidate] = field(default_factory=list)
    history: list[SideQuest] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    completed_step_ids: list[str] = field(default_factory=list)
    # Flat log of every repair action, for explaining "what changed".
    repair_log: list[dict[str, Any]] = field(default_factory=list)

    def add_turn(self, role: str, text: str) -> None:
        self.turns.append(Turn(role, text))

    def commit(self, quest: SideQuest, actions: Sequence[RepairAction] = ()) -> None:
        """Make `quest` current, keeping the previous version in history."""
        self.history.append(self.quest)
        self.quest = quest
        for a in actions:
            self.repair_log.append({**asdict(a), "action": a.action.value, "version": quest.version})

    def revert(self) -> bool:
        """Undo the last repair. Returns False when there is nothing to undo."""
        if not self.history:
            return False
        self.quest = self.history.pop()
        # Forget actions of the undone version, so a later repair that reuses
        # its version number doesn't inherit them.
        self.repair_log = [e for e in self.repair_log if e.get("version", 0) <= self.quest.version]
        return True

    def mark_completed(self, step_id: str) -> None:
        if step_id not in self.completed_step_ids:
            self.completed_step_ids.append(step_id)

    def recent_turns(self, n: int = 10) -> list[Turn]:
        return self.turns[-n:]

    # --- serialization ---

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "quest": sidequest_to_dict(self.quest),
            "candidates": [asdict(c) for c in self.candidates],
            "history": [sidequest_to_dict(q) for q in self.history],
            "turns": [asdict(t) for t in self.turns],
            "completed_step_ids": list(self.completed_step_ids),
            "repair_log": self.repair_log,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        return cls(
            session_id=data["session_id"],
            quest=sidequest_from_dict(data["quest"]),
            candidates=[place_from_dict(c) for c in data.get("candidates", [])],
            history=[sidequest_from_dict(q) for q in data.get("history", [])],
            turns=[Turn(**t) for t in data.get("turns", [])],
            completed_step_ids=list(data.get("completed_step_ids", [])),
            repair_log=list(data.get("repair_log", [])),
        )


class SessionStore(Protocol):
    def get(self, session_id: str) -> SessionState | None: ...
    def save(self, state: SessionState) -> None: ...
    def delete(self, session_id: str) -> None: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def get(self, session_id: str) -> SessionState | None:
        raw = self._data.get(session_id)
        # Round-trip through dicts so callers can't mutate stored state by
        # accident.
        return SessionState.from_dict(raw) if raw else None

    def save(self, state: SessionState) -> None:
        self._data[state.session_id] = state.to_dict()

    def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)


class JsonFileSessionStore:
    """One JSON file per session under `directory`."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
        return self.directory / f"{safe}.json"

    def get(self, session_id: str) -> SessionState | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            return SessionState.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError):
            # Corrupt file: treat as missing rather than crashing the turn.
            return None

    def save(self, state: SessionState) -> None:
        path = self._path(state.session_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)
