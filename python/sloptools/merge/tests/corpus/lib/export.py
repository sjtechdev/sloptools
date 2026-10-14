"""Exporters. Part of the slopmerge test corpus (not imported)."""

import csv
import json
import logging

logger = logging.getLogger(__name__)


# POSITIVE near: export_orders_csv with a header option added
def export_rows_csv(rows, path, header=True):
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        if header:
            writer.writerow(["id", "customer", "amount"])
        for row in rows:
            writer.writerow([row.id, row.customer_id, round(row.amount, 2)])
    logger.info("wrote %s", path)
    return path


# POSITIVE near: export_orders_csv with the logging dropped and a count returned
def export_invoices_csv(invoices, path):
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "customer", "amount"])
        for invoice in invoices:
            writer.writerow([invoice.id, invoice.customer_id, round(invoice.amount, 2)])
    return len(invoices)


# POSITIVE near: build_report_headers with two independent statements swapped
def make_headers(user, request_id):
    headers = {"Content-Type": "application/json"}
    headers["X-User"] = user.email
    headers["X-Request-Id"] = request_id
    headers["Authorization"] = "Bearer " + user.token
    headers["Cache-Control"] = "no-store"
    return headers


class Exporter:
    def __init__(self, destination):
        self.destination = destination

    def export(self, records):
        raise NotImplementedError


# POSITIVE near: the same override in several subclasses (a pull-up candidate)
class CsvExporter(Exporter):
    def export(self, records):
        logger.info("exporting %d records", len(records))
        lines = [",".join(str(v) for v in r.values()) for r in records]
        with open(self.destination, "w") as fh:
            fh.write("\n".join(lines))
        self.exported = len(records)
        return self.exported


class TsvExporter(Exporter):
    def export(self, records):
        logger.info("exporting %d records", len(records))
        lines = ["\t".join(str(v) for v in r.values()) for r in records]
        with open(self.destination, "w") as fh:
            fh.write("\n".join(lines))
        self.exported = len(records)
        return self.exported


class JsonLinesExporter(Exporter):
    def export(self, records):
        logger.info("exporting %d records", len(records))
        lines = [json.dumps(r) for r in records]
        with open(self.destination, "w") as fh:
            fh.write("\n".join(lines))
            fh.write("\n")
        self.exported = len(records)
        return self.exported


class Settings:
    def __init__(self, path, strict=False):
        self.path = path
        self.strict = strict
        self.values = {}

    @property
    def loaded(self):
        return self.values

    def get(self, key):
        return self.lookup(key)

    def __hash__(self):
        return hash((self.path, self.strict))

    def reload(self):
        with open(self.path) as fh:
            self.values = json.load(fh)
        if self.strict and not self.values:
            raise ValueError(f"empty settings: {self.path}")
        logger.debug("loaded %d settings", len(self.values))
        return self.values


class Invoice:
    def __init__(self, id, customer_id, amount, status="draft"):
        self.id = id
        self.customer_id = customer_id
        self.amount = amount
        self.status = status
        self.lines = []

    def __eq__(self, other):
        if not isinstance(other, Invoice):
            return NotImplemented
        return (self.id, self.customer_id, self.amount) == (other.id, other.customer_id, other.amount)
