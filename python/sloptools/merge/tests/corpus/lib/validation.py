"""Input validation. Part of the slopmerge test corpus (not imported)."""

import re

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")
ALIASES = {"googlemail.com": "gmail.com"}


# POSITIVE near: app/accounts.py:normalise_email, three edits apart
def clean_email(raw):
    email = raw.strip().lower()
    if not EMAIL.match(email):
        return None
    local, _, domain = email.partition("@")
    domain = ALIASES.get(domain, domain)
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}"


def parse_duration(text):
    match = re.fullmatch(r"(\d+)\s*(s|m|h|d)", text.strip())
    if match is None:
        raise ValueError(f"bad duration: {text!r}")
    value, unit = int(match.group(1)), match.group(2)
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def parse_bool(text):
    lowered = text.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"not a boolean: {text!r}")
