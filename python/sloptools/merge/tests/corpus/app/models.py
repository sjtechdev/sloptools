"""Models and storage. Part of the slopmerge test corpus (not imported)."""

from dataclasses import dataclass


# POSITIVE class (renamed): the same fields as lib/models.py:PostalAddress, one typed differently
@dataclass
class Address:
    street: str
    city: str
    postcode: str
    country: str = "GB"


# POSITIVE class (methods): lib/models.py:InvoiceRepository, method for method
class OrderRepository:
    def __init__(self, db):
        self.db = db
        self.table = "orders"

    def get(self, key):
        row = self.db.fetch_one(self.table, key)
        if row is None:
            raise KeyError(key)
        return self.db.decode(row)

    def recent(self, limit):
        rows = self.db.fetch_many(self.table, order_by="created", limit=limit)
        decoded = [self.db.decode(r) for r in rows]
        return [d for d in decoded if not d.get("deleted")]

    def delete(self, key):
        row = self.get(key)
        row["deleted"] = True
        self.db.write(self.table, key, row)
        return row


# NEGATIVE class: shares only id and name with lib/models.py:Tag
class Customer:
    def __init__(self, id, name, segment):
        self.id = id
        self.name = name
        self.segment = segment
        self.joined = None
