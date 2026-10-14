"""Shared statistics helpers. Part of the slopmerge test corpus (not imported)."""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)
TAX_RATE = 0.2
REPORT_COLUMNS = ("order_id", "customer_name", "total", "status", "placed_at")


def summarise_orders(orders):
    """Top ten customers by taxed spend."""
    totals = defaultdict(float)
    for order in orders:
        if order.status != "cancelled":
            totals[order.customer_id] += order.amount * (1 + TAX_RATE)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return dict(ranked[:10])


def count_enabled_accounts(accounts, cutoff):
    found = set()
    for acct in accounts:
        if acct.last_login >= cutoff and acct.state == "enabled":
            found.add(acct.email.lower())
    logger.info("enabled accounts: %d", len(found))
    return len(found)


def render_page(template, context):
    compiled = template.compile(context)
    rendered = compiled.render_html()
    minified = rendered.strip_whitespace()
    return minified.encode_utf8()


def rebuild_index(store, batch_size):
    logger.info("rebuilding index in batches of %d", batch_size)
    logger.debug("store: %s", store.name)
    store.clear_index()
    store.reindex(batch_size=batch_size)
    logger.info("index rebuilt")
    logger.debug("documents: %d", store.count())
    return store.count()


def percentile(values, p):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("no values")
    k = (len(ordered) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def moving_average(values, window):
    if window <= 0:
        raise ValueError("window must be positive")
    out = []
    acc = sum(values[:window])
    out.append(acc / window)
    for i in range(window, len(values)):
        acc += values[i] - values[i - window]
        out.append(acc / window)
    return out


def histogram(values, buckets):
    lo, hi = min(values), max(values)
    width = (hi - lo) / buckets or 1
    counts = [0] * buckets
    for v in values:
        counts[min(int((v - lo) / width), buckets - 1)] += 1
    return counts
