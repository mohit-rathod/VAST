"""Chat sessions: one NextDim agent per browser tab, held in memory.

The agent is a state machine, so a conversation has to keep its agent between
requests. Sessions live in this dict and are lost on restart, which is fine for
a demo: nothing about a chat is worth persisting, and the patients and bookings
it writes go to SQLite as usual.
"""

import uuid

from agents.nextdim.agent import NextDimAgent

# session id -> agent. Capped so an abandoned tab cannot grow it forever.
MAX_SESSIONS = 200
SESSIONS: dict[str, NextDimAgent] = {}


def new_session(on_event=None) -> tuple[str, NextDimAgent]:
    """Start a conversation and return its id and agent."""
    if len(SESSIONS) >= MAX_SESSIONS:
        SESSIONS.clear()
    session_id = uuid.uuid4().hex
    agent = NextDimAgent(on_event=on_event)
    SESSIONS[session_id] = agent
    return session_id, agent


def get_session(session_id: str) -> NextDimAgent:
    """The agent for this id, or a fresh conversation if the id is unknown.

    Falling back to a new agent rather than raising keeps a reloaded page, whose
    session id is still in the browser but gone from memory, working.
    """
    return SESSIONS.get(session_id) or new_session()[1]


def drop_session(session_id: str) -> None:
    """Forget a conversation, for the New chat button."""
    SESSIONS.pop(session_id, None)
