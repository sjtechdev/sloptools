"""Account handling. Part of the slopmerge test corpus (not imported)."""

import hashlib
import logging
import re
import secrets

logger = logging.getLogger(__name__)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")


# NEGATIVE: logging-heavy, unrelated to refund_order and rebuild_index
def suspend_account(account, admin):
    logger.info("suspending %s", account.id)
    logger.debug("requested by %s", admin.email)
    account.active = False
    account.sessions.revoke_all()
    logger.info("suspended %s", account.id)
    logger.debug("sessions revoked: %d", account.sessions.count())
    return account


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${digest.hex()}"


def check_password(password, stored):
    salt, _, expected = stored.partition("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return secrets.compare_digest(digest.hex(), expected)


def normalise_email(raw):
    email = raw.strip().lower()
    if not EMAIL.match(email):
        raise ValueError(f"not an email: {raw!r}")
    local, _, domain = email.partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}"


def merge_accounts(primary, duplicate):
    for order in duplicate.orders:
        order.account_id = primary.id
    primary.credit += duplicate.credit
    primary.tags |= duplicate.tags
    duplicate.active = False
    logger.info("merged %s into %s", duplicate.id, primary.id)
    return primary


def password_strength(password):
    score = 0
    if len(password) >= 12:
        score += 2
    if re.search(r"[A-Z]", password) and re.search(r"[a-z]", password):
        score += 1
    if re.search(r"\d", password):
        score += 1
    if re.search(r"[^\w]", password):
        score += 1
    return min(score, 5)


class Account:
    def __init__(self, id, email, credit=0):
        self.id = id
        self.email = email
        self.credit = credit
        self.tags = set()

    @property
    def domain(self):
        return self.email

    def __repr__(self):
        return f"Account({self.id!r}, {self.email!r})"

    def __eq__(self, other):
        if not isinstance(other, Account):
            return NotImplemented
        return self.id == other.id

    def deactivate(self):
        return self.close()


# NEGATIVE boilerplate: record classes whose __init__/__eq__ are copies of
# lib/export.py:Invoice's. They'd group without the boilerplate rules.
class Order:
    def __init__(self, id, customer_id, amount, status="open"):
        self.id = id
        self.customer_id = customer_id
        self.amount = amount
        self.status = status
        self.lines = []

    def __eq__(self, other):
        if not isinstance(other, Order):
            return NotImplemented
        return (self.id, self.customer_id, self.amount) == (other.id, other.customer_id, other.amount)


# POSITIVE block (renamed): the retry loop pasted into lib/export.py:publish_invoice
def sync_account(account, client):
    if account.deleted:
        client.delete(f"/accounts/{account.id}")
        return None
    payload = account.to_payload()
    payload["source"] = "app"
    payload["tags"] = sorted(account.tags)
    for attempt in range(3):
        try:
            response = client.post("/accounts", payload)
            break
        except TimeoutError:
            logger.warning("timeout, retry %d", attempt)
            client.backoff(2 ** attempt)
    else:
        raise RuntimeError("gave up")
    account.synced_at = response.timestamp
    account.version = response.headers.get("ETag")
    for tag in response.json().get("tags", []):
        account.tags.add(tag.lower())
    return response


# POSITIVE block (exact): the same name validation in two unrelated functions
def create_project(owner, name, private=False):
    if not name:
        raise ValueError("name is required")
    name = name.strip()
    if len(name) > 100:
        raise ValueError("name is too long")
    project = owner.projects.create(name=name, private=private)
    owner.notify("project created", project.id)
    return project


def rename_team(team, name):
    if not name:
        raise ValueError("name is required")
    name = name.strip()
    if len(name) > 100:
        raise ValueError("name is too long")
    team.history.append((team.name, name))
    team.name = name
    team.save()
