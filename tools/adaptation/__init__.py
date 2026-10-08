"""Adaptation / Memory pipeline: keeps an active SideQuest alive.

Public surface:
    tools.TOOL_DECLARATIONS / tools.run_tool - what the Gemini server wires up
    tools.start_session  - store a SideQuest built by the Story pipeline
    repair_sidequest     - the pure repair algorithm behind the tool
"""

from tools.adaptation.memory import InMemorySessionStore, JsonFileSessionStore, SessionState
from tools.adaptation.repair import repair_sidequest
from tools.adaptation.tools import TOOL_DECLARATIONS, TOOL_FUNCTIONS, run_tool, start_session

__all__ = [
    "InMemorySessionStore",
    "JsonFileSessionStore",
    "SessionState",
    "TOOL_DECLARATIONS",
    "TOOL_FUNCTIONS",
    "repair_sidequest",
    "run_tool",
    "start_session",
]
