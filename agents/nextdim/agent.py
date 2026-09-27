"""NextDim portal agent.

A small step machine: the model only does the language work (understanding the
complaint, reading details out of a message, reading a date and time of day).
Lookups, maths, the registry and the booking are plain code, done by the tools.

    agent = NextDimAgent()
    print(agent.start())
    while True:
        print(agent.handle(input("> ")))

Pass `on_event` to see what happens while it works, which is how the web UI
shows the steps. See app/trace.py for the event shape.
"""

import re
import sqlite3
from typing import get_args

from app.db import connect
from app.geo import coordinates_of
from app.trace import MODEL, NOTE, STEP, TOOL, emit
from domain.models import (
    Availability,
    Complaint,
    Location,
    PatientIntake,
    SlotOption,
    Speciality,
)
from tools.available_slots import available_slots, window
from tools.book import book_appointment
from tools.match_clinics import nearest_clinics, suggest_clinics

from .llm import ask

SPECIALITIES = ", ".join(get_args(Speciality))
PERIOD_HOURS = {"morning": (0, 12), "afternoon": (12, 17), "evening": (17, 24), "any": (0, 24)}
# The periods a patient can actually be offered, as opposed to "any", which is
# a request rather than a time of day.
PERIODS = ("morning", "afternoon", "evening")
YES = {"yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure", "correct", "right", "same", "confirmed", "no change"}
CHOICE = re.compile(r"\b([1-9])\b")

# What each step of the machine is called in the UI trace.
STEP_LABELS = {
    "welcome": "Start the conversation",
    "triage": "Understand the complaint",
    "details": "Collect the patient details",
    "location": "Settle on an address",
    "availability": "Find a day and time",
    "options": "Offer clinics and slots",
    "confirm": "Confirm and book",
    "done": "Finished",
}

WELCOME = (
    "Welcome to the NextDim Health portal. I am your care coordinator."
    " Tell me what is troubling you and I will get you to the right doctor."
)

TRIAGE_PROMPT = (
    "You are the intake assistant of the NextDim Health portal. A patient describes a"
    " problem in their own words. Reply with JSON only, shaped as"
    ' {"description": str, "speciality": str, "understood_as": str}.'
    " description: the complaint, cleaned up but kept in the patient's own words."
    f" speciality: exactly one of: {SPECIALITIES}."
    " understood_as: one sentence that restates the problem back to the patient, so"
    " they can check that you understood it."
)

DETAILS_PROMPT = (
    "Pull the patient's details out of the message. Reply with JSON only, shaped as"
    ' {"first_name": str|null, "last_name": str|null, "date_of_birth": "YYYY-MM-DD"|null,'
    ' "email": str|null, "phone": str|null}. Use null for anything the message does not'
    " mention, and never guess or invent a value. Copy the values exactly as written."
)

LOCATION_PROMPT = (
    "Pull the patient's address out of the message. Reply with JSON only, shaped as"
    ' {"address": str, "city": str, "state": str, "zip": str}.'
    " address: street and neighbourhood if given. city: the city or borough."
    " state: the two letter code. zip: five digits, digits only, from New York. Never"
    " invent a zip code; if the message has none, put an empty string."
)

AVAILABILITY_PROMPT = (
    "Work out when the patient can come in. Reply with JSON only, shaped as"
    ' {"date": "YYYY-MM-DD", "period": "morning"|"afternoon"|"evening"|"any"}.'
    " date: the day the patient asked for, as one of the open days given to you."
    " period: morning for before 12:00, afternoon for 12:00 to 17:00, any if they did"
    " not say. Never invent a date outside the open days."
)


def is_yes(message: str) -> bool:
    """True when the patient is agreeing with what the agent just said."""
    text = message.strip().lower()
    return any(word == text or text.startswith(word + " ") for word in YES)


def first_number(message: str) -> int | None:
    """The number the patient picked out of a numbered list."""
    match = CHOICE.search(message)
    return int(match.group(1)) if match else None


def in_period(start_time: str, period: str) -> bool:
    """Does a HH:MM slot start inside the period the patient asked for?"""
    low, high = PERIOD_HOURS[period]
    return low <= int(start_time[:2]) < high


def alternatives(day, period: str) -> list[tuple]:
    """Other (day, period) pairs to offer, closest first.

    Another time on the same day comes before another day, because moving an
    appointment within a day is easier for a patient than moving it to a
    different one. Among the other days, the nearest come first and a later day
    wins a tie, so a request for the middle of the window is never answered with
    the far end of it.
    """
    nearest_days = sorted(
        (other for other in window() if other != day),
        key=lambda other: (abs((other - day).days), -other.toordinal()),
    )
    return [(day, other) for other in PERIODS if other != period] + [
        (other, period) for other in nearest_days
    ]


def address_of(place) -> str:
    """Readable one line address from a Location or a patient row."""
    row = dict(place) if not hasattr(place, "get") else place
    return f'{row["address"]}, {row["city"]}, {row["state"]} {row["zip"]}'


def find_patient(email: str, phone: str):
    """The patient registered with this email and phone number together."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM patients WHERE email = ? AND phone = ?", (email, phone)
        ).fetchone()


class NextDimAgent:
    """The portal conversation. Call start() once, then handle() for every message.

    `client` is anything with `chat.completions.create`, so a test can pass a
    stub. `on_event` is any callable taking one event dict, which the web UI uses
    to show each step; see app/trace.py.
    """

    def __init__(self, client=None, on_event=None):
        self.client = client
        self.on_event = on_event
        self.step = "welcome"
        self.complaint = None
        self.intake = PatientIntake()
        self.patient = None
        self.pending = None
        self.availability = None
        self.options = []
        self.chosen = None
        self.booking = None

    def _emit(self, kind: str, title: str, **data) -> None:
        """Report one thing that just happened, if anyone is listening."""
        emit(self.on_event, kind, title, **data)

    @property
    def patient_id(self) -> int | None:
        """Id of the patient on file, or None before they are registered."""
        return self.patient["id"] if self.patient else None

    def start(self) -> str:
        """The opening message. Called once, before any handle()."""
        return WELCOME

    def handle(self, message: str) -> str:
        """Send one patient message through the current step and get the reply.

        Dispatches to the handler for self.step and moves to the next step. A
        ValueError from the model is caught here and turned into a "say that
        again", so a bad reply never escapes to the caller.
        """
        self._emit(
            STEP,
            STEP_LABELS.get(self.step, self.step),
            step=self.step,
            said=message,
        )
        steps = {
            "welcome": self._triage,
            "triage": self._triage_confirmed,
            "details": self._details,
            "location": self._location,
            "availability": self._availability,
            "options": self._choose,
            "confirm": self._book,
            "done": lambda message: "You are all booked. Anything else I can help with?",
        }
        try:
            return steps[self.step](message.strip())
        except ValueError:
            return "Sorry, I did not quite catch that. Could you say it another way?"

    # 1 + 2. welcome, then understand the complaint and check with the patient
    def _triage(self, message: str) -> str:
        """Read the complaint out of free text and restate it for confirmation."""
        self.complaint = ask(
            Complaint,
            TRIAGE_PROMPT,
            {"message": message},
            self.client,
            self.on_event,
            "Ask the model to name the speciality behind the complaint",
        )
        self.step = "triage"
        return (
            f'Here is what I understood: "{self.complaint.understood_as}"\n'
            f"That means you need a doctor who specialises in {self.complaint.speciality}.\n"
            "Is that clear, or would you like to explain it again?"
        )

    def _triage_confirmed(self, message: str) -> str:
        """Move on when the patient agrees, otherwise let them explain again."""
        if not is_yes(message):
            return self._triage(message)
        self.step = "details"
        return (
            "Good. To find the right doctor and clinic I need a few details:"
            " your full name, date of birth, email and phone number."
        )

    # 3. details, registration check, location
    def _details(self, message: str) -> str:
        """Pull the patient details out of free text, then look them up.

        Only fields the model actually found are applied, and anything still
        missing is asked for again. Email and phone have to match together
        before an existing record is reused.
        """
        found = ask(
            PatientIntake,
            DETAILS_PROMPT,
            {"message": message, "already_known": self.intake.model_dump(mode="json")},
            self.client,
            self.on_event,
            "Ask the model to pull the details out of the message",
        )
        for field, value in found.model_dump().items():
            if value is not None:
                setattr(self.intake, field, value)

        if self.intake.missing():
            return f"Thank you. I still need your {', '.join(self.intake.missing())}."

        self._emit(
            TOOL,
            "Look the patient up by email and phone together",
            email=self.intake.email,
            phone=self.intake.phone,
        )
        self.patient = find_patient(self.intake.email, self.intake.phone)
        self.step = "location"
        if self.patient is not None:
            self._emit(NOTE, "Already registered, reusing the record", patient_id=self.patient["id"])
            return (
                f"Welcome back, {self.patient['first_name']}, you are already registered"
                f" with us. The address we have is {address_of(self.patient)}."
                " Is that still where you are, or shall I update it?"
            )
        self._emit(NOTE, "Not registered yet, this address will create the record")
        return (
            f"Thank you, {self.intake.first_name}. You are not registered yet."
            " Please share your address and ZIP code so I can find a clinic near you."
        )

    def _location(self, message: str) -> str:
        """Settle on an address, always read back before it is saved.

        A returning patient can confirm the address on file, and a just-parsed
        address can be confirmed, so "yes" never means "take a new address".
        A ZIP with no coordinates is rejected here, before anything is written.
        """
        if self.pending is None and self.patient is not None and is_yes(message):
            place = Location(
                **{field: self.patient[field] for field in ("address", "city", "state", "zip")}
            )
        elif self.pending is not None and is_yes(message):
            place, self.pending = self.pending, None
        else:
            place = ask(
                Location,
                LOCATION_PROMPT,
                {"message": message},
                self.client,
                self.on_event,
                "Ask the model to pull the address out of the message",
            )
            point = coordinates_of(place.zip)
            if point is None:
                self._emit(
                    TOOL,
                    "No coordinates for that ZIP, asking the patient again",
                    zip=place.zip,
                )
                return (
                    f"I do not have a location for ZIP {place.zip or '(none given)'}."
                    " Could you give me a New York ZIP code, for example 10001 or 11215?"
                )
            self._emit(
                TOOL,
                "Turned the ZIP into coordinates",
                zip=place.zip,
                latitude=point[0],
                longitude=point[1],
            )
            self.pending = place
            return f"Let me confirm: {address_of(place)}. Is that correct?"

        problem = self._save(place)
        if problem:
            return problem
        self.step = "availability"
        return f"Location saved as {address_of(place)}. " + self._ask_availability()

    def _save(self, place: Location) -> str | None:
        """Register a new patient, or update the location and complaint of an existing one."""
        latitude, longitude = coordinates_of(place.zip)
        place_values = {**place.model_dump(mode="json"), "latitude": latitude, "longitude": longitude}
        self._emit(
            TOOL,
            "Create the patient record" if self.patient is None else "Update the patient record",
            **place_values,
            complaints=self.complaint.description,
        )
        with connect() as conn:
            try:
                if self.patient is None:
                    values = {
                        **self.intake.model_dump(mode="json"),
                        **place_values,
                        "complaints": self.complaint.description,
                    }
                    names = ", ".join(values)
                    marks = ", ".join("?" * len(values))
                    cursor = conn.execute(
                        f"INSERT INTO patients ({names}) VALUES ({marks})",
                        list(values.values()),
                    )
                    patient_id = cursor.lastrowid
                else:
                    values = {**place_values, "complaints": self.complaint.description}
                    sets = ", ".join(f"{name} = ?" for name in values)
                    patient_id = self.patient["id"]
                    conn.execute(
                        f"UPDATE patients SET {sets} WHERE id = ?",
                        [*values.values(), patient_id],
                    )
                self.patient = conn.execute(
                    "SELECT * FROM patients WHERE id = ?", (patient_id,)
                ).fetchone()
            except sqlite3.IntegrityError:
                return (
                    "That email is already registered with a different phone number."
                    " Could you confirm the phone number?"
                )
        return None

    def _ask_availability(self) -> str:
        """Ask when the patient can come in, naming the days that are open."""
        days = ", ".join(day.isoformat() for day in window())
        return (
            f"When can you come in? Appointments are open {days},"
            " 09:00 to 17:00. Morning, afternoon, or anytime?"
        )

    # 4. availability, then the tools suggest clinics and slots
    def _availability(self, message: str) -> str:
        """Read the wanted day and time of day, then offer clinics.

        A date outside the open window is refused rather than guessed at, so the
        tools are only ever asked about days that can actually be booked.
        """
        want = ask(
            Availability,
            AVAILABILITY_PROMPT,
            {"message": message, "open_days": [str(day) for day in window()]},
            self.client,
            self.on_event,
            "Ask the model for the day and the time of day",
        )
        if want.date not in window():
            self._emit(
                NOTE,
                "That day is outside the booking window, asking again",
                asked=str(want.date),
                open_days=[str(day) for day in window()],
            )
            return (
                f"We only have appointments between {window()[0]} and {window()[-1]}."
                " Which of those days works for you?"
            )
        self.availability = want
        return self._offer()

    def _offer(self) -> str:
        """Build the numbered choices and show them, or fall back to nearby times.

        Each of the clinics the matcher ranked is paired with its first free slot
        inside the period the patient asked for. If that period is full, the
        search widens to nearby times rather than making the patient ask again.
        """
        day, period = self.availability.date, self.availability.period
        self._emit(
            TOOL,
            "Ask the matcher for the best clinics",
            patient_id=self.patient_id,
            day=str(day),
            period=period,
        )
        suggestions = suggest_clinics(
            self.patient_id, day, client=self.client, on_event=self.on_event
        )
        self.options = []
        for clinic in suggestions[:3]:
            slots = available_slots(clinic["clinic_id"], day)
            slot = next(
                (slot for slot in slots if in_period(slot["start_time"], period)),
                None,
            )
            if slot:
                self._emit(
                    TOOL,
                    f'{clinic["name"]} is free at {slot["start_time"]} that day',
                    clinic_id=clinic["clinic_id"],
                    free_slots=[f'{s["start_time"]}-{s["end_time"]}' for s in slots],
                )
                self.options.append(
                    SlotOption(
                        clinic_id=clinic["clinic_id"],
                        clinic_name=clinic["name"],
                        speciality=clinic["speciality"],
                        distance_km=clinic["distance_km"],
                        date=day,
                        start_time=slot["start_time"],
                        end_time=slot["end_time"],
                        reason=clinic.get("reason", ""),
                    )
                )
        if not self.options:
            return self._offer_nearby(day, period)
        self.step = "options"
        return self._choices(f"For {day} in the {period} I can offer you:")

    def _offer_nearby(self, day, period: str) -> str:
        """Every slot in that period is gone: say so, then offer the closest ones.

        The clinics are ranked once by distance and reused for every nearby day
        and period, so widening the search costs one pass over the database
        rather than another ranking call. Days and periods are tried in
        `alternatives` order, and the first three hits are offered as the usual
        numbered choices, so the patient picks a number exactly as before.
        """
        self._emit(
            TOOL,
            f"Everything in the {period} on {day} is booked, looking for the closest other times",
            day=str(day),
            period=period,
        )
        clinics = nearest_clinics(self.patient_id, count=None)
        # One call per clinic covers the whole window, so the search below does
        # no extra database work.
        free = {clinic["clinic_id"]: available_slots(clinic["clinic_id"]) for clinic in clinics}

        self.options = []
        for other_day, other_period in alternatives(day, period):
            for clinic in clinics:
                slot = next(
                    (
                        slot
                        for slot in free[clinic["clinic_id"]]
                        if slot["date"] == other_day.isoformat()
                        and in_period(slot["start_time"], other_period)
                    ),
                    None,
                )
                if slot:
                    self.options.append(
                        SlotOption(
                            clinic_id=clinic["clinic_id"],
                            clinic_name=clinic["name"],
                            speciality=clinic["speciality"],
                            distance_km=clinic["distance_km"],
                            date=other_day,
                            start_time=slot["start_time"],
                            end_time=slot["end_time"],
                        )
                    )
            if len(self.options) >= 3:
                break

        if not self.options:
            self._emit(
                NOTE,
                "No slot free anywhere in the booking window either",
                open_days=[str(open_day) for open_day in window()],
            )
            self.step = "availability"
            return (
                f"I am sorry, every appointment between {window()[0]} and {window()[-1]}"
                " is already booked. Please try again later."
            )

        self._emit(
            TOOL,
            f"Found {len(self.options)} nearby alternatives, offering the closest 3",
            options=[
                f"{o.clinic_name} {o.date} {o.start_time:%H:%M}-{o.end_time:%H:%M}"
                for o in self.options[:3]
            ],
        )
        # Keep only what is shown, so the number the patient replies with always
        # lines up with the list they were given.
        self.options = self.options[:3]
        self.step = "options"
        return self._choices(
            f"Everything in the {period} on {day} is already booked."
            " The closest I can get is:"
        )

    def _choices(self, header: str) -> str:
        """The numbered list of options under `header`, and the question after it."""
        lines = [
            f"{number}. {option.clinic_name} - {option.speciality}, {option.distance_km} km away,"
            f" {option.date} {option.start_time:%H:%M} to {option.end_time:%H:%M}"
            + (f". {option.reason}" if option.reason else "")
            for number, option in enumerate(self.options[:3], start=1)
        ]
        return (
            header
            + "\n"
            + "\n".join(lines)
            + "\nWhich one would you like? Reply with the number."
        )

    # 5. confirm, then book
    def _choose(self, message: str) -> str:
        """Read the number the patient picked and read the choice back."""
        number = first_number(message)
        if number is None or not 1 <= number <= len(self.options):
            return f"Please reply with a number between 1 and {len(self.options)}."
        self.chosen = self.options[number - 1]
        self.step = "confirm"
        self._emit(
            TOOL,
            f'The patient picked option {number}',
            clinic_id=self.chosen.clinic_id,
            clinic_name=self.chosen.clinic_name,
            start_time=f"{self.chosen.start_time:%H:%M}",
        )
        return (
            f"To confirm: {self.chosen.clinic_name} ({self.chosen.speciality},"
            f" {self.chosen.distance_km} km away) on {self.chosen.date},"
            f" {self.chosen.start_time:%H:%M} to {self.chosen.end_time:%H:%M}."
            " Shall I book it?"
        )

    def _book(self, message: str) -> str:
        """Book the chosen slot once the patient says yes.

        If the slot was taken in the meantime the booking fails, and the step
        falls back to a fresh set of options rather than claiming success.
        """
        if not is_yes(message):
            self.step = "options"
            return "No problem. Which of the options would you like? Reply with the number."
        self._emit(
            TOOL,
            "Book the slot",
            clinic_id=self.chosen.clinic_id,
            patient_id=self.patient_id,
            slot_date=self.chosen.date.isoformat(),
            start_time=f"{self.chosen.start_time:%H:%M}",
        )
        result = book_appointment(
            self.chosen.clinic_id,
            self.patient_id,
            self.chosen.date.isoformat(),
            f"{self.chosen.start_time:%H:%M}",
        )
        if not result["ok"]:
            self._emit(NOTE, "The slot was taken, offering other times", error=result["error"])
            return self._offer()
        self.booking = result
        self.step = "done"
        return (
            f"You are booked, {self.patient['first_name']}. {self.chosen.clinic_name}"
            f" ({self.chosen.speciality}) on {self.chosen.date} from"
            f" {self.chosen.start_time:%H:%M} to {self.chosen.end_time:%H:%M}."
            f" Your booking id is {self.booking['booking_id']}."
            " We will see you then, take care."
        )


if __name__ == "__main__":
    chat = NextDimAgent()
    print(chat.start())
    while chat.step != "done":
        try:
            print(chat.handle(input("> ")))
        except (EOFError, KeyboardInterrupt):
            break
