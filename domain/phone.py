"""Canonical contact numbers, with explicit country context and no dependencies.

Storage and comparisons use the E.164 representation: '+' and at most 15 digits.
Unprefixed national numbers are supported for US/CA only. Other countries must
supply a country calling code; we never infer it from the patient's location.
This validates structure, NOT number allocation, reachability or ownership.
"""
import os
import re
import unicodedata


class PhoneNumberError(ValueError):
    """A phone cannot be normalized without guessing or losing information."""


def normalize_phone(value: str, region: str | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PhoneNumberError("Please provide a phone number with its country code.")
    text = unicodedata.normalize("NFKC", value.strip())
    text = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text)
    # Reject extensions and vanity strings instead of silently truncating them.
    if not re.fullmatch(r"[+0-9() .\-\s]+", text):
        raise PhoneNumberError("Use a phone number without letters or an extension.")
    if text.count("(") != text.count(")"):
        raise PhoneNumberError("The phone number has unmatched parentheses.")
    compact = re.sub(r"[() .\-\s]", "", text)
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    region = (region or os.getenv("VAST_PHONE_REGION", "US")).upper()
    if region in {"US", "CA"} and compact.startswith("011"):
        compact = "+" + compact[3:]
    if not compact.startswith("+"):
        if region not in {"US", "CA"}:
            raise PhoneNumberError("Please include '+' and your country calling code.")
        if len(compact) == 10 and compact.isascii() and compact.isdigit():
            compact = "+1" + compact
        elif len(compact) == 11 and compact.startswith("1") and compact.isdigit():
            compact = "+" + compact
        else:
            raise PhoneNumberError("Use a 10-digit US/Canada number or include '+' and the country code.")
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", compact):
        raise PhoneNumberError("Use a full international phone number, such as +12125550100.")
    if compact.startswith("+1") and len(compact) != 12:
        raise PhoneNumberError("US/Canada numbers need 10 digits after +1.")
    return compact


def phone_for_sql(value: str) -> str | None:
    """SQL comparison of legacy data; invalid data never becomes an identity."""
    try:
        return normalize_phone(value)
    except PhoneNumberError:
        return None


def normalize_chat_phone(value: str) -> str:
    """Require ten national digits in chat; preserve canonical storage elsewhere."""
    text = unicodedata.normalize("NFKC", value.strip())
    text = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text)
    if (not re.fullmatch(r"[0-9() .\-\s]+", text)
            or text.count("(") != text.count(")")):
        raise PhoneNumberError("Use exactly 10 digits, without a country code, letters or extension.")
    digits = re.sub(r"[() .\-\s]", "", text)
    if not re.fullmatch(r"[0-9]{10}", digits):
        raise PhoneNumberError("Use exactly 10 digits, without a country code or extension.")
    return normalize_phone(digits)