from dataclasses import dataclass, field
from decimal import Decimal
from itertools import count

from .inventory import Inventory
from .ledger import Ledger
from .pricing import total

_ids = count(1)


@dataclass
class Order:
    id: int
    items: dict[str, int]
    tier: str | None
    paid: Decimal
    status: str = "paid"
    refunded: dict[str, int] = field(default_factory=dict)


class Shop:
    def __init__(self):
        self.inventory = Inventory()
        self.ledger = Ledger()
        self.orders: dict[int, Order] = {}

    def place_order(self, items: dict[str, int], tier: str | None = None) -> Order:
        amount = total(items, tier)
        self.inventory.take(items)
        order = Order(next(_ids), dict(items), tier, amount)
        self.orders[order.id] = order
        self.ledger.record("sale", order.id, amount)
        return order
