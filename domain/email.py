"""Common mailbox syntax, without DNS lookups or claims of mailbox ownership."""
import re

LOCAL_PART = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*\Z")
DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")


def validate_email(value: str) -> str:
    """Accept ordinary dot-atom mailboxes, including aliases and subdomains.

    Deliberately excludes quoted local parts, IP literals and Unicode addresses;
    those need a separate internationalized-email policy, not silent rewriting.
    """
    value = value.strip()
    if len(value) > 254 or value.count("@") != 1:
        raise ValueError("invalid email")
    local, domain = value.split("@")
    labels = domain.split(".")
    if (len(local) > 64 or not LOCAL_PART.fullmatch(local) or len(labels) < 2
            or any(not DOMAIN_LABEL.fullmatch(label) for label in labels)
            or not re.fullmatch(r"(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{2,59})", labels[-1])):
        raise ValueError("invalid email")
    return value