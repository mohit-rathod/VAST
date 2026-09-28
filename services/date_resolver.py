"""Deterministic English calendar resolution; the model never chooses dates.

Weeks are Monday-Sunday. 'Friday' is the next occurrence (including today),
' this Friday' belongs to the current week, and 'next Friday' to next week.
Numeric slash dates and inconsistent weekday/date combinations require clarity.
All arithmetic starts from the clinic-local aware datetime supplied by the caller.
"""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_WORDS = {name: i for i, name in enumerate(WEEKDAYS)}
for _name, _index in list(DAY_WORDS.items()):
    DAY_WORDS[_name[:3]] = _index
MONTHS = {name.lower(): i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}
for _name, _index in list(MONTHS.items()):
    MONTHS[_name[:3]] = _index
MONTHS["sept"] = 9
MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
DAY_PATTERN = "|".join(sorted(DAY_WORDS, key=len, reverse=True))
SMALL_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                 "twelve": 12, "fourteen": 14}


def say_date(day: date) -> str:
    return f"{day:%A} {day.isoformat()}"


@dataclass(frozen=True)
class DateResolution:
    start: date | None = None
    end: date | None = None
    recognized: bool = False
    error: str = ""

    @property
    def dates(self) -> list[date]:
        if self.start is None:
            return []
        return [self.start + timedelta(days=i) for i in range(((self.end or self.start) - self.start).days + 1)]

    @property
    def description(self) -> str:
        if self.start is None:
            return ""
        return say_date(self.start) if self.end in (None, self.start) else f"{say_date(self.start)} through {say_date(self.end)}"


class DateResolver:
    @staticmethod
    def _relative_days(text: str, today: date) -> list[tuple[str, date]]:
        offsets = {"day after tomorrow": 2, "day before yesterday": -2,
                   "today": 0, "tomorrow": 1, "yesterday": -1}
        return [(m[0], today + timedelta(days=offsets[m[0]])) for m in
                re.finditer(r"\b(?:day after tomorrow|day before yesterday|today|tomorrow|yesterday)\b", text)]

    def resolve(self, message: str, now: datetime) -> DateResolution:
        if now.tzinfo is None:
            raise ValueError("An aware clinic-local clock is required")
        text, today = message.casefold(), now.date()
        monday = today - timedelta(days=today.weekday())
        if re.search(r"\b(not|except|excluding|instead of|but not)\b", text):
            return DateResolution(recognized=True, error="Please state the date you do want, rather than a date to exclude, so I do not book the wrong day.")
        if "this week" in text and "next week" in text:
            if re.search(r"\b(through|until|to)\b", text):
                return DateResolution(today, monday + timedelta(days=13), True)
            return DateResolution(recognized=True, error="Please choose this week or next week, or give an explicit start and end date.")
        if re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", text):
            return DateResolution(recognized=True, error="Please write the date as YYYY-MM-DD or name the month, so day and month cannot be confused.")
        if re.search(r"(?<!day )\b(?:before|after|earlier than|later than)\s+(?:today|tomorrow|yesterday|(?:this |next )?(?:" + DAY_PATTERN + r")|\d{4}-\d{1,2}-\d{1,2})\b", text):
            return DateResolution(recognized=True, error="Please give the first and last dates you want searched, rather than a before/after boundary, so the appointment stays within your intended dates.")
        explicit = []
        try:
            for m in re.finditer(r"\b\d{4}-\d{1,2}-\d{1,2}\b", text):
                year, month, day = map(int, m.group().split("-"))
                explicit.append((m.start(), date(year, month, day)))
            patterns = (
                rf"\b(?P<month>{MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{{4}}))?\b",
                rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{MONTH_PATTERN})\.?(?:,?\s+(?P<year>\d{{4}}))?\b",
            )
            for pattern in patterns:
                for m in re.finditer(pattern, text):
                    explicit.append((m.start(), date(int(m['year'] or today.year), MONTHS[m['month']], int(m['day']))))
        except ValueError:
            return DateResolution(recognized=True, error="That calendar date does not exist. Please provide a valid date including its month and year.")
        if explicit:
            days = [d for _, d in sorted(set(explicit))]
            if len(days) > 2 or (len(days) == 2 and not re.search(r"\b(to|through|until|between)\b", text)):
                return DateResolution(recognized=True, error="Please choose one date or give a start date and an end date for the search.")
            start, end = days[0], days[-1]
            if end < start:
                return DateResolution(recognized=True, error=f"The end date {say_date(end)} is before {say_date(start)}. Please check the range.")
            weekday = re.search(rf"\b({DAY_PATTERN})\b", text)
            if len(days) == 1 and weekday and DAY_WORDS[weekday[1]] != start.weekday():
                return DateResolution(recognized=True, error=f"{start.isoformat()} is {start:%A}, not {weekday[1].title()}. Which date did you intend?")
            # A relative label must agree with an explicit date, including
            # multi-word labels such as 'day after tomorrow'.
            relative = self._relative_days(text, today)
            if len(relative) > 1 or (relative and relative[0][1] != start):
                return DateResolution(recognized=True, error=f"The relative day and explicit date do not agree. Please choose one date; today is {say_date(today)}.")
            return DateResolution(start, end, True)
        relative = self._relative_days(text, today)
        if len(relative) > 1:
            if len(relative) == 2 and re.search(r"\b(to|through|until)\b", text):
                start, end = relative[0][1], relative[1][1]
                if end >= start:
                    return DateResolution(start, end, True)
                return DateResolution(recognized=True, error=f"The end date {say_date(end)} is before {say_date(start)}. Please check the range.")
            return DateResolution(recognized=True, error="Please choose one day or specify a continuous date range.")
        if relative:
            label, resolved = relative[0]
            weekday = re.search(rf"\b({DAY_PATTERN})\b", text)
            if weekday and DAY_WORDS[weekday[1]] != resolved.weekday():
                return DateResolution(recognized=True, error=f"{label.title()} is {say_date(resolved)}, not {weekday[1].title()}. Which date did you intend?")
            return DateResolution(resolved, recognized=True)
        m = re.search(r"\bin (\d+|" + "|".join(SMALL_NUMBERS) + r") days?\b", text)
        if m:
            count = int(m[1]) if m[1].isdigit() else SMALL_NUMBERS[m[1]]
            if count > 3660:
                return DateResolution(recognized=True, error="That day is outside the supported search range. Please provide a nearer date.")
            return DateResolution(today + timedelta(days=count), recognized=True)
        weekdays = list(re.finditer(rf"\b(?:(this|next)\s+)?({DAY_PATTERN})\b", text))
        if weekdays:
            days = []
            for m in weekdays:
                number = DAY_WORDS[m[2]]
                prefix = m[1] or ("next" if "next week" in text else "this" if "this week" in text else "")
                resolved = monday + timedelta(days=number + (7 if prefix == "next" else 0)) if prefix else today + timedelta(days=(number - today.weekday()) % 7)
                days.append(resolved)
            if len(days) == 1:
                return DateResolution(days[0], recognized=True)
            if len(days) == 2 and days[1] >= days[0] and re.search(r"\b(to|through|until)\b", text):
                return DateResolution(days[0], days[1], True)
            return DateResolution(recognized=True, error="Please choose one weekday or an ordered start and end date.")
        for phrase, start, end in (
            ("next weekend", monday + timedelta(days=12), monday + timedelta(days=13)),
            ("this weekend", max(today, monday + timedelta(days=5)), monday + timedelta(days=6)),
            ("next week", monday + timedelta(days=7), monday + timedelta(days=13)),
            ("this week", today, monday + timedelta(days=6)),
        ):
            if phrase in text:
                return DateResolution(start, end, True)
        if re.search(r"\bweekend\b", text):
            return DateResolution(max(today, monday + timedelta(days=5)), monday + timedelta(days=6), True)
        if "this month" in text:
            return DateResolution(today, today.replace(day=monthrange(today.year, today.month)[1]), True)
        if "next month" in text:
            start = today.replace(day=28) + timedelta(days=4)
            start = start.replace(day=1)
            return DateResolution(start, start.replace(day=monthrange(start.year, start.month)[1]), True)
        if re.search(r"\b(any day|anytime|any time|earliest|as soon as possible)\b", text):
            return DateResolution(today, today + timedelta(days=366), True)
        return DateResolution()


@dataclass(frozen=True)
class TimePreference:
    period: str = "any"
    at: str | None = None
    mentioned: bool = False
    error: str = ""


def resolve_time(message: str) -> TimePreference:
    text = message.casefold().replace("a.m.", "am").replace("p.m.", "pm")
    if re.search(r"\b(not|except|excluding|instead of)\b", text):
        return TimePreference(error="Please state the date or time you do want, so I do not reverse an exclusion.")
    # Bounded time ranges are not silently interpreted as an exact start time.
    if re.search(r"\b(after|before|between|until|by)\s+(?:\d|noon|midnight)", text):
        return TimePreference(error="Please give a specific start time, or choose morning or afternoon. I will show the exact available times for confirmation.")
    periods = [p for p in ("morning", "afternoon", "evening") if re.search(rf"\b{p}\b", text)]
    if len(periods) > 1:
        return TimePreference(error="Please choose a single time of day, or say any time.")
    period = periods[0] if periods else "any"
    matches = list(re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b", text))
    if len(matches) > 1:
        return TimePreference(error="Please provide one start time; appointment durations can be 30 minutes or 1 hour.")
    if matches:
        m = matches[0]
        hour, minute = int(m[1] or m[4]), int(m[2] or m[5] or 0)
        if minute > 59 or (m[3] and not 1 <= hour <= 12) or (not m[3] and hour > 23):
            return TimePreference(error="Please provide a valid time, such as 2 pm or 14:00.")
        if m[3]:
            hour = hour % 12 + (12 if m[3] == "pm" else 0)
        period = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
        return TimePreference(period, f"{hour:02d}:{minute:02d}", True)
    if re.search(r"\bnoon\b", text):
        return TimePreference("afternoon", "12:00", True)
    if re.search(r"\bmidnight\b", text):
        return TimePreference("morning", "00:00", True)
    if re.search(r"\bat\s+\d{1,2}\b", text):
        return TimePreference(error="Please include am or pm, or use HH:MM in 24-hour time.")
    if "first thing" in text:
        return TimePreference("morning", "09:00", True)
    return TimePreference(period, mentioned=bool(periods) or "any time" in text or "anytime" in text)