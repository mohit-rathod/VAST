"""Validate patient-supplied contact text after extraction, without LLM retries."""
from dataclasses import dataclass
import re
import unicodedata

from domain.email import validate_email
from domain.phone import normalize_chat_phone


@dataclass(frozen=True)
class ContactRead:
    values: dict
    errors: dict[str, str]


# An obvious literal in the message wins over an LLM's attempted correction.
# Less structured statements are extracted verbatim by IntakeDraft/UpdateDraft.
EMAIL_LITERAL = re.compile(r"[^\s,;<>]*\s*@\s*[^\s,;<>]+")
PHONE_LITERAL = re.compile(r"(?<![\w])\+?\(?\d[\d() .+\-]*\d(?:\s*(?:ext\.?|extension|x)\s*\d+)?", re.I)
EMAIL_LABEL = re.compile(r"\be-?mail(?:\s+address)?\s*(?:is\s+|[:=]\s*)?([^\s,;<>]+)", re.I)
PHONE_LABEL = re.compile(r"\b(?:phone|mobile)(?:\s+number)?\s*(?:is\s+|[:=]\s*)?([^,;\n]+)", re.I)
PLACEHOLDERS = {"and", "or", "address", "number", "phone", "email", "is", "on", "currently", "please", "to"}


def _unquote(value: str) -> str:
    return value.strip().strip('"<>').rstrip(",;")


def observed_contacts(message: str, extracted: dict | None = None) -> dict[str, str]:
    """Read obvious current input without consulting a model or stored record."""
    extracted = extracted or {}
    result = {}
    emails = EMAIL_LITERAL.findall(message)
    if len(emails) == 1:
        value = _unquote(emails[0])
        # A sentence-ending full stop is not part of the address; consecutive
        # trailing dots remain invalid instead of being silently fixed.
        if value.endswith(".") and not value.endswith(".."):
            value = value[:-1]
        result["email"] = value
    elif not emails and (match := EMAIL_LABEL.search(message)):
        value = _unquote(match[1])
        if value.casefold() not in PLACEHOLDERS:
            result["email"] = value

    candidates = [candidate.strip() for candidate in PHONE_LITERAL.findall(message)]
    candidates = [candidate for candidate in candidates
                  if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate)
                  and (sum(c.isdecimal() for c in candidate) >= 7
                       or (extracted.get("phone") and candidate == message.strip()))]
    # Old/new numbers in the same sentence need the model's verbatim selection;
    # never override it with the first number simply because it appears first.
    if len(candidates) > 1:
        return result
    labelled = PHONE_LABEL.search(message)
    if labelled:
        tail = re.split(r"\s+(?:and|my|email|e-mail|address|date|dob)\b", labelled[1], maxsplit=1, flags=re.I)[0].strip()
        if tail and tail.casefold() not in PLACEHOLDERS and not tail.lower().startswith("number"):
            if any(c.isdecimal() for c in tail) or tail.casefold() in {"abc", "invalid", "unknown"}:
                result["phone"] = tail.rstrip(".") if not tail.endswith("..") else tail
    if "phone" not in result and candidates:
        result["phone"] = candidates[0]
    return result


def validate_contact_values(values: dict, message: str = "") -> ContactRead:
    result = dict(values)
    result.update(observed_contacts(message, values))
    errors = {}
    for field, validator in (("email", validate_email), ("phone", normalize_chat_phone)):
        value = result.get(field)
        if value is None:
            continue
        try:
            result[field] = validator(value)
        except ValueError:
            # Keep entered values only in the patient-facing reply, not traces.
            shown = str(value).replace("\n", " ").replace("\r", " ")[:160]
            if field == "phone":
                text = unicodedata.normalize("NFKC", str(value))
                count = sum(c.isdecimal() for c in text)
                errors[field] = (
                    f'You entered "{shown}" for your phone number ({count} digits). '
                    'Please enter a 10-digit phone number, for example 2125550100. '
                    'Spaces, hyphens and parentheses are allowed; do not include a country code or extension.'
                )
            else:
                errors[field] = (
                    f'You entered "{shown}" for your email address. '
                    'Please enter an email in name@example.com format, with one @, '
                    'a domain such as example.com, and no spaces.'
                )
            result.pop(field, None)
    return ContactRead(result, errors)


def error_reply(errors: dict[str, str]) -> str:
    return "\n".join(errors.values())