from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Entry:
    kind: str          # "sale" or "refund"
    order_id: int
    amount: Decimal    # positive for sales, negative for refunds


@dataclass
class Ledger:
    entries: list[Entry] = field(default_factory=list)

    def record(self, kind: str, order_id: int, amount: Decimal) -> None:
        self.entries.append(Entry(kind, order_id, amount))

    def balance(self) -> Decimal:
        return sum((e.amount for e in self.entries), Decimal("0"))
