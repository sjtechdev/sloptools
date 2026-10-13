"""Order and user reports. Part of the slopmerge test corpus (not imported)."""

import csv
import json
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)
TAX_RATE = 0.2


# POSITIVE exact: verbatim copy of lib/stats.py:summarise_orders (restyled)
def summarise_orders(orders):
    # totals per customer, then the top ten
    totals = defaultdict(float)
    for order in orders:
        if order.status != "cancelled":
            totals[order.customer_id] += order.amount * (1 + TAX_RATE)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return dict(ranked[:10])


# POSITIVE renamed: same code as lib/stats.py:count_enabled_accounts, other local names and literals
def count_active_users(users, since):
    seen = set()
    for user in users:
        if user.last_login >= since and user.state == "active":
            seen.add(user.email.lower())
    logger.info("active users: %d", len(seen))
    return len(seen)


# POSITIVE near: drifted copies of a CSV export (see lib/export.py)
def export_orders_csv(orders, path):
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "customer", "amount"])
        for order in orders:
            writer.writerow([order.id, order.customer_id, round(order.amount, 2)])
    logger.info("wrote %s", path)
    return path


# POSITIVE near: same steps, two independent statements swapped
def build_report_headers(user, request_id):
    headers = {"Content-Type": "application/json"}
    headers["X-Request-Id"] = request_id
    headers["X-User"] = user.email
    headers["Authorization"] = "Bearer " + user.token
    headers["Cache-Control"] = "no-store"
    return headers


# NEGATIVE: same silhouette as lib/stats.py:render_page, every operation different
def load_page(client, page_id):
    response = client.fetch(page_id)
    payload = response.decode_body()
    document = payload.parse_markup()
    return document.extract_text()


# NEGATIVE: logging-heavy, unrelated to the other logging-heavy functions
def refund_order(order, reason):
    logger.info("refund requested for %s", order.id)
    logger.debug("reason: %s", reason)
    order.status = "refunded"
    order.refunded_amount = order.amount
    logger.info("refund recorded for %s", order.id)
    logger.debug("amount: %s", order.amount)
    return order


# NEGATIVE related-not-near: a loop and a comprehension computing the same thing
def active_names_loop(users):
    names = []
    for user in users:
        if user.state == "active":
            names.append(user.name.title())
    return sorted(names)


def active_names_comprehension(users):
    names = [u.name.title() for u in users if u.state == "active"]
    names.sort()
    result = list(names)
    return result


class Report:
    # NEGATIVE boilerplate: an __init__ that only stores its parameters
    def __init__(self, title, rows, footer=None):
        self.title = title
        self.rows = rows
        self.footer = footer
        self.created = None

    # NEGATIVE boilerplate: property accessors
    @property
    def size(self):
        return self.rows

    # NEGATIVE boilerplate: one-line delegation
    def save(self, path):
        return self.write(path)

    # NEGATIVE boilerplate: attribute-list dunders
    def __eq__(self, other):
        if not isinstance(other, Report):
            return NotImplemented
        return (self.title, self.rows) == (other.title, other.rows)

    def __repr__(self):
        return f"Report({self.title!r}, rows={len(self.rows)})"

    def to_json(self):
        body = {"title": self.title, "rows": [list(r) for r in self.rows]}
        if self.footer:
            body["footer"] = self.footer
        return json.dumps(body, indent=2)
