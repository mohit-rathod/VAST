"""Events the agent emits while it works, so a UI can show each step.

An event is a plain dict, so it can go straight to JSON:

    kind    "step" | "model" | "tool" | "note"
    title   one line saying what is happening
    <rest>  the values behind it, passed as keyword arguments

The agent and the tools call `emit` without checking whether anyone is
listening, so tracing costs nothing when `on_event` is None, as it is in the
terminal chat.
"""

# The event kinds, so a typo shows up as an unknown badge in the UI.
STEP = "step"
MODEL = "model"
TOOL = "tool"
NOTE = "note"


def emit(on_event, kind: str, title: str, **data) -> None:
    """Send one event on. A no-op when nothing is listening.

    `on_event` is any callable taking a single dict, which keeps the callers
    free of `if on_event is not None` checks.
    """
    if on_event is not None:
        on_event({"kind": kind, "title": title, **data})
