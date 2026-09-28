"""Appointment-duration policy, separate from symptom-duration descriptions."""
from dataclasses import dataclass
import re

from services.date_resolver import resolve_time

MAX_MINUTES = 60
SUPPORTED_MINUTES = (30, 60)
LIMIT_REPLY = "We cannot book for more than one hour. You can request a 30-minute or 1-hour appointment."
CHOICE_REPLY = "Appointments can be 30 minutes or 1 hour. Which duration would you like?"
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
           "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
           "twelve": 12, "thirty": 30, "sixty": 60, "ninety": 90}
NUMBER = r"(?:\d+(?:\.\d+)?|" + "|".join(NUMBERS) + r")"
DURATION = re.compile(rf"\b({NUMBER})(?:\s+and\s+(?:a\s+)?half)?[ -]*(hours?|hrs?|minutes?|mins?)\b|\bhalf[ -]+(?:an?\s+)?hour\b")
CLOCK = r"(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2})"


@dataclass(frozen=True)
class DurationRequest:
    minutes: int | None = None
    error: str = ""
    remaining: str = ""


def _amount(value: str) -> float:
    return float(value) if value[0].isdigit() else NUMBERS[value]


def _normalized_words(text: str) -> str:
    text = re.sub(rf"\b({NUMBER})\s+hours?\s+and\s+(?:a\s+)?half\b",
                  lambda m: f"{_amount(m[1]) + 0.5:g} hours", text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)h(?:(\d+)m)?\b",
                  lambda m: f"{m[1]} hours" + (f" and {m[2]} minutes" if m[2] else ""), text)
    return re.sub(r"\b(\d+)m\b", r"\1 minutes", text)


def appointment_duration(message: str, scheduling: bool = False) -> DurationRequest:
    text = _normalized_words(message.casefold())
    group = re.search(r"\b(?:for\s+)?(two|three|four|five|six|[2-9])\s+(?:people|persons|patients|of us)\b|\bboth of us\b|\b(?:me and my|my (?:wife|husband|partner) and (?:me|i))\b|\bfor two(?=[.!?,]|$)", text)
    group_minutes = None
    if group:
        count = _amount(group[1]) if group[1] else 2
        if count > 2:
            return DurationRequest(error=LIMIT_REPLY)
        group_minutes = 60
    if group and re.search(r"\b(not|don't|do not)\b", text):
        return DurationRequest(error=CHOICE_REPLY)
    symptom = bool(re.search(r"\b(pain|hurt|hurting|symptoms?|ache|started|lasted|suffering|sore|cough|fever|headache|unwell)\b", text))
    booking = re.search(r"\b(book|booking|appointment|slot|session|reserve|make it|change it)\b", text)
    booking_context = bool(booking or re.search(r"\b(need|want)\b", text))
    if booking_context and re.search(rf"\bfor ({NUMBER}) (?:days?|weeks?)\b|\b(?:all day|full day)\b", text):
        return DurationRequest(error=LIMIT_REPLY)
    if symptom:
        if booking is None:
            return DurationRequest(remaining=message)
        text = text[booking.start():]
    time_range = re.search(rf"\b({CLOCK})\s*(?:to|until|-)\s*({CLOCK})\b", text)
    if time_range and (scheduling or booking_context):
        start, end = resolve_time(time_range[1]), resolve_time(time_range[2])
        if not start.error and not end.error and start.at and end.at:
            minutes = (int(end.at[:2]) * 60 + int(end.at[3:])) - (int(start.at[:2]) * 60 + int(start.at[3:]))
            if minutes > MAX_MINUTES:
                return DurationRequest(error=LIMIT_REPLY)
            if minutes not in SUPPORTED_MINUTES:
                return DurationRequest(error=CHOICE_REPLY)
            remaining = text[:time_range.start()] + 'at ' + start.at + text[time_range.end():]
            return DurationRequest(max(minutes, group_minutes or 0), remaining=remaining)
    matches = list(DURATION.finditer(text))
    pure = bool(matches) and re.sub(r"[ .,!?:;-]|\b(and|a|please)\b", "", DURATION.sub("", text)) == ""
    if matches and (pure or booking_context or scheduling):
        if len(matches) > 1 and re.search(r"\b(or|either)\b", text):
            return DurationRequest(error=CHOICE_REPLY)
        minutes = 0
        for match in matches:
            if match.group().startswith('half'):
                minutes += 30
            else:
                amount = _amount(match[1]) + (0.5 if 'half' in match.group() else 0)
                minutes += amount * (60 if match[2].startswith(('hour', 'hr')) else 1)
        greater_text = text.replace('no more than', 'up to').replace('not more than', 'up to')
        over = bool(re.search(r"\b(more than|longer than|over)\s+(?:one|1|an?)\s+hour\b", greater_text))
        if minutes > MAX_MINUTES or over:
            return DurationRequest(error=LIMIT_REPLY)
        if minutes not in SUPPORTED_MINUTES:
            return DurationRequest(error=CHOICE_REPLY)
        remaining = DURATION.sub('', text)
        if group:
            remaining = remaining.replace(group.group(), '')
        return DurationRequest(int(max(minutes, group_minutes or 0)), remaining=remaining.strip())
    if group_minutes:
        return DurationRequest(group_minutes, remaining=(text[:group.start()] + text[group.end():]).strip())
    return DurationRequest(remaining=message)