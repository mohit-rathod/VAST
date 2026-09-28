"""Pure calendar shortcut policy, independent of the agent and browser."""
from datetime import datetime, time, timedelta


def date_shortcuts(current: datetime, allowed_days, limit: int = 7) -> list[dict[str, str]]:
    """Up to seven allowed days: today before noon, tomorrow from noon onward.

    These are search shortcuts, not promises of availability. Their payloads
    contain absolute dates so a delayed click cannot move to a different day.
    """
    if limit < 1:
        return []
    if current.tzinfo is None:
        raise ValueError("The shortcut clock must include the clinic timezone")
    today = current.date()
    earliest = today + timedelta(days=int(current.time() >= time(12)))
    result = []
    zone_name = getattr(current.tzinfo, "key", str(current.tzinfo))
    for day in sorted(set(allowed_days)):
        if day < earliest:
            continue
        prefix = "Today - " if day == today else "Tomorrow - " if day == today + timedelta(days=1) else ""
        result.append({
            "label": f"{prefix}{day:%A} {day.isoformat()}",
            "message": day.isoformat(),
            "kind": "date",
            "date": day.isoformat(),
            "timezone": zone_name,
            "expires_at": datetime.combine(day, time(12), current.tzinfo).isoformat(),
        })
        if len(result) >= limit:
            break
    return result