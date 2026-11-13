from .catalog import MENU


class Inventory:
    def __init__(self):
        self.stock = {k: v["stock"] for k, v in MENU.items()}

    def take(self, items: dict[str, int]) -> None:
        for item, qty in items.items():
            if self.stock.get(item, 0) < qty:
                raise ValueError(f"not enough {item}")
        for item, qty in items.items():
            self.stock[item] -= qty

    def put_back(self, items: dict[str, int]) -> None:
        for item, qty in items.items():
            self.stock[item] += qty
