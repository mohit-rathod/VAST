"""Structured language decisions for state-derived chat actions."""

from pydantic import BaseModel, ConfigDict


class VisibleActionMatch(BaseModel):
    """A model-selected canonical action payload, or no match.

    The model never invents an action: application code validates ``message``
    against the actions that are currently visible before using it.
    """

    model_config = ConfigDict(extra="forbid")

    message: str | None = None
