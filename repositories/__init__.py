"""SQLite adapters and their shared connection lifetime boundary."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager

ConnectionFactory = Callable[[], sqlite3.Connection]


@contextmanager
def connection(factory: ConnectionFactory) -> Iterator[sqlite3.Connection]:
    """Commit or roll back as before, and explicitly release the connection."""
    conn = factory()
    try:
        with conn:
            yield conn
    finally:
        conn.close()
