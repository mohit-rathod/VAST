"""Contact extraction adapter: raw model output -> local validation -> draft state."""
from domain.chat_models import IntakeDraft, UpdateDraft
from domain.models import PatientIntake
from services.contact_input import ContactRead, validate_contact_values


def read_contacts(context, model, system: str, payload: dict, label: str) -> ContactRead:
    draft_type = IntakeDraft if model is PatientIntake else UpdateDraft
    draft = context.ask(draft_type, system, payload, label)
    flow = context.flow
    values = draft.model_dump(exclude_none=True)
    message = payload.get("message", "").strip()
    # A reply to a single outstanding contact question can itself be malformed.
    # Do not let a model hide it by returning null.
    if flow.step == "details":
        missing = flow.intake.missing()
    else:
        missing = [field for field in ("email", "phone") if not flow.contact_update.get(field)]
    if len(missing) == 1 and missing[0] in {"email", "phone"} and not values:
        values[missing[0]] = message
    result = validate_contact_values(values, message)
    # A corrected field clears its own error, not another field's pending error.
    for field in ("email", "phone"):
        if field in result.values:
            flow.contact_errors.pop(field, None)
    flow.contact_errors.update(result.errors)
    return result