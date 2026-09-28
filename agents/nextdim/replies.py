"""What the patient is told, and nothing else.

Presentation helpers: each one takes what is known and returns the words, so
the wording of a step can be read without following the step. No model, no
database, no clock, which also means a test can assert on a reply without setting
up a conversation.
"""

from app.geo import DEFAULT_ZONE
from domain.models import Complaint, Location

from tools.available_slots import window

# The field names the portal asks for, said the way a person would.
ASKED_AS = {
    "first_name": "your first name",
    "last_name": "your last name",
    "email": "your email address",
    "phone": "your phone number",
    "date_of_birth": "your date of birth",
}


def welcome() -> str:
    """The greeting, which is also the first question."""
    return (
        "Welcome to the NextDim Health portal. I am your care coordinator and I will"
        " get you in front of the right doctor."
        " To start, could you give me your full name, email address and phone number?"
        " You can say 'end chat' at any time."
    )


def ask_details() -> str:
    """Said when the greeting was lost, for instance on a reloaded page."""
    return "Could you give me your full name, your email address and a phone number?"


def need_details(missing: list[str]) -> str:
    """What is still needed before the patient can be looked up."""
    return (
        f"Thank you. I still need {' and '.join(ASKED_AS[name] for name in missing)}."
        " You can give me all of it in one message."
    )


def on_file(patient: dict) -> str:
    """The record of a patient we already know, read back for them to check."""
    return (
        f"Hello {patient['first_name']}, you are already registered with us."
        " This is what I have on file:\n" + record_of(patient) + closing()
    )


def registered(patient: dict) -> str:
    """The record just created, read back for them to check."""
    return (
        f"Thank you, {patient['first_name']}, you are now registered with us."
        " This is what I have on file:\n" + record_of(patient) + closing()
    )


def record_of(patient: dict) -> str:
    """The lines of a record, one field each, as they are held."""
    lines = [
        f"  Name: {patient['first_name']} {patient['last_name']}",
        f"  Email: {patient['email']}",
        f"  Phone: {patient['phone'] or 'Needs an updated full number'}",
    ]
    if patient.get("date_of_birth"):
        lines.append(f"  Date of birth: {patient['date_of_birth']}")
    lines.append(f"  Address: {address_of(patient)}")
    return "\n".join(lines)


def closing() -> str:
    """The question that follows a record read back to the patient."""
    return "\nIs all of that right? Reply yes, or tell me what to change."


def need_address(name: str) -> str:
    """The one thing a patient who is not registered cannot be booked without."""
    return (
        f"Thank you, {name}. I could not find you on the system, so I will set up"
        " your record. What is your address and ZIP code? I need it to find a clinic"
        " near you. If you are already registered, say 'recover account' instead."
    )


def confirm_address(place: Location) -> str:
    """A new address read back, so "yes" can never mean "take a new address"."""
    return f"Let me confirm: {address_of(place)}. Is that correct?"


def unregistered_address() -> str:
    """A ZIP we cannot place, which means no clinic can be matched to it."""
    return (
        "I do not have a location for that ZIP. Could you give me a New York ZIP code,"
        " for example 10001 or 11215?"
    )


def need_the_rest_of_the_address() -> str:
    """Not enough of an address to place a patient on a map."""
    return (
        "I need the street, the city or borough, the state and a five digit ZIP code"
        " to set that up."
    )


def nothing_to_change() -> str:
    """A correction we could not read, said without blaming the patient."""
    return (
        "I could not tell what you would like changed. You can tell me the new name,"
        " email, phone number or address, or reply that it is all correct."
    )


def ask_problem(name: str) -> str:
    """The question the whole conversation turns on."""
    return (
        f"Thank you, {name}. Now, what is the problem you would like treated?"
        " Tell me in your own words, as much or as little as you like."
    )


def understood(complaint: Complaint) -> str:
    """The problem restated, for the patient to agree with or correct."""
    return (
        f'Here is what I understood: "{complaint.understood_as}"\n'
        "Is that exactly your problem, or would you like to add something?"
        " Whatever you tell me here goes to the doctor you see."
    )


def more_detail(round_number: int) -> str:
    """Asked while the patient has not yet agreed what their problem is."""
    if round_number < 3:
        return (
            "Tell me more. When did it start, where exactly does it hurt, and how bad"
            " is it? Anything you add goes into what I put in front of the doctor."
        )
    return (
        "Let us take it more slowly. In a sentence or two, what is troubling you,"
        " from when it started to how it feels now?"
    )


def settled() -> str:
    """Said when the patient agreed the problem had been understood."""
    return "Thank you, I have that down. "


def not_settled() -> str:
    """Said when the patient never agreed, and the best reading is used anyway."""
    return (
        "I will go with what you have told me and you can add the rest to the doctor"
        " when you arrive. "
    )


def say_day(day) -> str:
    """A date the way it is said out loud: the weekday and the date together.

    Every date a patient is shown carries its weekday, so "you said Friday" is
    answered with "Friday 2026-10-02" and neither side has to trust the other to
    have picked the same day.
    """
    return f"{day:%A} {day.isoformat()}"


def needs_clinic(speciality: str, clinics: list[dict], zone=None) -> str:
    """Which speciality treats the problem, and how many of them there are."""
    how_many = (
        "we have one nearby" if len(clinics) == 1 else f"we have {len(clinics)} nearby"
    )
    return (
        f"That is treated by our {speciality} clinics, and {how_many}. When would you"
        f" like to come in? Appointments are open {open_days()}, 09:00 to 17:00"
        f" {clock(zone)}. A day or a weekday, and a morning, afternoon or evening, or"
        " a time of day, is enough."
    )


def ask_time(zone=None) -> str:
    """Asked again when the day or the time of day was not one we can book."""
    return (
        f"Which of those days works for you? Appointments are open {open_days()},"
        f" 09:00 to 17:00 {clock(zone)}, and I can do morning, afternoon, or a time of"
        " day."
    )


def beyond_window(zone=None) -> str:
    """Said when the patient asked for a day past the end of the booking window.

    The limit is named rather than glossed over, because "next Tuesday" when the
    portal stops on Sunday is a day the portal genuinely cannot see, and saying
    so is better than answering with a day the patient did not ask for.
    """
    return (
        f"I cannot provide any information beyond {say_day(window()[-1])}. Appointments"
        f" are open {open_days()}, 09:00 to 17:00 {clock(zone)}. Which of those days"
        " would you like?"
    )


def slot_choices(options: list, header: str) -> str:
    """The numbered list of slots under `header`, and the question after it."""
    return (
        header
        + "\n"
        + options_of(options)
        + "\nWhich one would you like? Reply with the number, or tell me the clinic"
        " or the time you would prefer."
    )


def options_of(options: list) -> str:
    """The list as the patient sees it, one numbered option per line.

    Also what the model is given to read a reply against, so the numbers a patient
    sees and the numbers the model may answer with are the same ones. Each line
    carries the weekday as well as the date, in the clinic's own zone.
    """
    return "\n".join(
        f"{number}. {option.clinic_name} - {option.speciality},"
        f" {option.distance_km} km away, {say_day(option.date)},"
        f" {option.start_time:%H:%M} to {option.end_time:%H:%M}"
        f" {clock(option.zone)}"
        + (f". {option.reason}" if option.reason else "")
        for number, option in enumerate(options, start=1)
    )


def clock(zone=None) -> str:
    """How a time is qualified with the zone it is in, for a patient to read.

    New York time is the normal case here, and naming it stops a patient reading
    09:00 as UTC. A clinic in a different zone from the patient has its own time
    said outright instead.
    """
    if zone is None:
        return f"{DEFAULT_ZONE} time"
    name = getattr(zone, "key", zone) or DEFAULT_ZONE
    return f"{name} time"


def widened() -> str:
    """Said when the day the patient asked for has nothing free in that period."""
    return (
        "Everything in that period on the day you asked for is already booked."
        " Here is the closest I can get:"
    )


def pick_one(options: list) -> str:
    """Asked when the reply was neither an option nor a time we could use."""
    return (
        f"I did not catch which one you mean. Reply with a number between 1 and"
        f" {len(options)}, or tell me the clinic, the day or the time you would"
        " prefer."
    )


def read_back(option) -> str:
    """The agreed slot, said back before it is written down.

    The day is given as a weekday and a date and the time is qualified with the
    clinic's zone, so what the patient agrees to is the appointment they will
    actually turn up for.
    """
    return (
        f"To confirm: {option.clinic_name} ({option.speciality},"
        f" {option.distance_km} km away) on {say_day(option.date)},"
        f" {option.start_time:%H:%M} to {option.end_time:%H:%M}"
        f" {clock(option.zone)}. Shall I book it?"
        " Reply yes to go ahead, or tell me what to change."
    )


def booked(patient: dict, option, booking: dict) -> str:
    """What the patient is told once the booking is safely in the database."""
    return (
        f"You are booked, {patient['first_name']}. {option.clinic_name}"
        f" ({option.speciality}) on {say_day(option.date)} from"
        f" {option.start_time:%H:%M} to {option.end_time:%H:%M} {clock(option.zone)}."
        f" Your booking id is {booking['booking_id']}."
        " This chat is now closed. Start a new chat to view your bookings or make another appointment."
    )


def nothing_free() -> str:
    """Said when the whole booking window is gone."""
    return (
        f"I am sorry, every appointment between {say_day(window()[0])} and"
        f" {say_day(window()[-1])} is already booked. Please try again later."
    )


def slot_taken() -> str:
    """Said when the slot went to somebody else between being offered and booked."""
    return (
        "That slot was taken by another patient while we were talking, so I have"
        " not booked it. Here is what I can offer you instead:"
    )


def after_booking() -> str:
    """Said to a patient who has already been booked and keeps talking."""
    return "Your booking is complete and this chat is closed. Start a new chat to continue."


def address_of(place) -> str:
    """Readable one line address from a Location or a patient row."""
    row = place if hasattr(place, "get") else dict(place)
    return f'{row["address"]}, {row["city"]}, {row["state"]} {row["zip"]}'


def open_days() -> str:
    """The days that can be booked, named by weekday as well as by date."""
    days = [say_day(day) for day in window()]
    return ", ".join(days[:-1]) + f" or {days[-1]}"


def contact_mismatch() -> str:
    return ("There may be an existing registration, but the email and phone do not match it together. "
            "Please provide both your updated email address and phone number. "
            "I will show both details for your confirmation before saving them. No email will be sent.")


def account_menu(name: str) -> str:
    return (f"{name}, you can choose: 1. View all my bookings across all clinics; "
            "2. Book a new appointment; 3. View all clinics. You can also say 'end chat'.")


def booking_history(rows: list[dict]) -> str:
    if not rows:
        return "You have no bookings on record at any clinic."
    lines, previous = [f"All {len(rows)} of your bookings across all clinics (including past and cancelled appointments):"], None
    for row in rows:
        if row["clinic_id"] != previous:
            lines.append(f"\n{row['clinic_name']} - {row['speciality']}, {address_of(row)}:")
            previous = row["clinic_id"]
        lines.append(f"  Booking {row['booking_id']}: {row['weekday']} {row['slot_date']}, "
                     f"{row['start_time']} to {row['end_time']} {clock(row['zone'])}; status: {row['status']}.")
    return "\n".join(lines)


def clinic_directory(rows: list[dict]) -> str:
    if not rows:
        return "No clinics are currently listed."
    return "All clinics:\n" + "\n".join(f"{r['name']} - {r['speciality']}, {address_of(r)}; {clock(r['zone'])}." for r in rows)


def confirm_end() -> str:
    return "No appointment has been booked in this chat. End the chat without booking? Reply yes to end, or no to continue."


def ended() -> str:
    return "This chat has ended without creating an appointment. Existing bookings are unchanged. Start a new chat to continue."