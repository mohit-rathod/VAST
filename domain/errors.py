"""Persistence failures the application can handle without importing SQLite."""


class StorageConflict(Exception):
    """A write failed a storage constraint; preserve the backend's error text."""


class SlotTaken(Exception):
    """A busy booking already occupies the requested slot."""


class AgentRuntimeFailure(Exception):
    """Only a RuntimeError raised while handling an agent message."""


class AgentValueFailure(Exception):
    """Only a ValueError raised while handling an agent message."""
