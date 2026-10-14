"""Models and storage. Part of the slopmerge test corpus (not imported)."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PostalAddress:
    street: str
    city: str
    postcode: str
    country: Optional[str] = None


class InvoiceRepository:
    def __init__(self, db):
        self.db = db
        self.table = "invoices"

    def get(self, invoice_id):
        row = self.db.fetch_one(self.table, invoice_id)
        if row is None:
            raise KeyError(invoice_id)
        return self.db.decode(row)

    def recent(self, n):
        rows = self.db.fetch_many(self.table, order_by="issued", limit=n)
        decoded = [self.db.decode(r) for r in rows]
        return [d for d in decoded if not d.get("deleted")]

    def delete(self, invoice_id):
        row = self.get(invoice_id)
        row["deleted"] = True
        self.db.write(self.table, invoice_id, row)
        return row


class Tag:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.colour = "grey"
