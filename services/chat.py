"""One chat turn, independent of FastAPI and the session-storage implementation."""

from contextlib import nullcontext

from domain.errors import AgentRuntimeFailure, AgentValueFailure
from domain.ports import SessionStore


class ChatService:
    def __init__(self, sessions: SessionStore) -> None:
        self.sessions = sessions

    def reset(self, session_id: str) -> dict:
        self.sessions.drop_session(session_id)
        session_id, agent = self.sessions.new_session()
        return {"session_id": session_id, "reply": agent.start()}

    def turn(self, session_id: str | None, message: str) -> dict:
        events: list[dict] = []
        agent = self.sessions.get_session(session_id) if session_id else None
        if agent is None:
            session_id, agent = self.sessions.new_session(on_event=events.append)
        # Holding the same reentrant lock across event binding, execution and
        # result capture prevents concurrent requests sharing a session from
        # mixing their trace callbacks or returning a later turn's state.
        with getattr(agent, "turn_lock", nullcontext()):
            agent.on_event = events.append
            try:
                reply = agent.handle(message)
            except RuntimeError as error:
                raise AgentRuntimeFailure(str(error)) from error
            except ValueError as error:
                raise AgentValueFailure(str(error)) from error
            return {
                "session_id": session_id,
                "reply": reply,
                "step": agent.step,
                "done": agent.step == "done",
                "events": events,
                "booking": agent.booking,
                "actions": getattr(agent, "actions", []),
                "bookings": getattr(agent, "booking_history", None),
            }