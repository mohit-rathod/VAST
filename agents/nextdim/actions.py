"""State-derived patient buttons. The browser does not invent business actions."""
from .conversation import (BOOK, CLINIC, COMPLAINT, CONTACT_CONFIRM, DONE,
                           END_CONFIRM, MENU, REGISTRY, SLOTS, VERIFY)
from services.date_shortcuts import date_shortcuts
from tools import available_slots as calendar


def action(label: str, message: str, kind: str = "action") -> dict[str, str]:
    return {"label": label, "message": message, "kind": kind}


def actions(flow) -> list[dict[str, str]]:
    if flow.step == DONE:
        return []
    if flow.step == END_CONFIRM:
        # Keep this existing public payload unchanged.
        return [{"label": "Yes, end chat", "message": "yes"},
                {"label": "No, continue", "message": "no"}]
    result = []
    if flow.editing and flow.step != MENU:
        if not flow.contact_errors:
            result.append(action("Keep current details", "keep current details"))
    elif not flow.contact_errors or flow.step == MENU:
        if flow.step == VERIFY:
            result.append(action("Resend code", "resend code"))
        elif flow.step == MENU:
            result.extend([action("View all my bookings", "my bookings"),
                           action("Book an appointment", "book appointment"),
                           action("View all clinics", "all clinics")])
        elif flow.step == BOOK and flow.chosen:
            result.extend([action("Confirm booking", "yes", "primary"),
                           action("Choose another slot", "choose another slot"),
                           action("Change date", "change date")])
        elif flow.step == CONTACT_CONFIRM:
            result.extend([action("Confirm contact update", "yes", "primary"),
                           action("Edit contact details", "edit contact details")])
        elif flow.step == REGISTRY:
            if flow.pending:
                result.extend([action("Confirm address", "yes", "primary"),
                               action("Change address", "change address")])
            elif flow.patient:
                result.extend([action("Details are correct", "yes", "primary"),
                               action("Edit details", "edit details")])
        elif flow.step == COMPLAINT and flow.complaint:
            result.extend([action("Yes, that is correct", "yes", "primary"),
                           action("Change details", "change problem details")])
    if flow.step == SLOTS:
        for number, option in enumerate(flow.options, 1):
            result.append(action(
                f"{number}. {option.clinic_name} - {option.date:%A} {option.date.isoformat()}, "
                f"{option.start_time:%H:%M}-{option.end_time:%H:%M} {option.zone or calendar.PORTAL_ZONE.key}",
                str(number), "slot"))
    if flow.step in {CLINIC, SLOTS}:
        zone = calendar.zone_for(flow.patient["zip"] if flow.patient else None)
        result.extend(date_shortcuts(calendar.now(zone), calendar.window(zone)))
        if flow.preference:
            result.extend(action(label, message, "period") for label, message in (
                ("Morning", "morning"), ("Afternoon", "afternoon"), ("Any time", "any time")))
    if flow.step == MENU and flow.account_return_step:
        result.append(action("Continue previous step", "continue"))
    result.append(action("End chat", "end chat"))
    return result