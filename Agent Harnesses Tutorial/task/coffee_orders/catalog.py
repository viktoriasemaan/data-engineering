from decimal import Decimal

# price per unit and starting stock
MENU = {
    "espresso": {"price": Decimal("3.00"), "stock": 50},
    "latte": {"price": Decimal("4.75"), "stock": 40},
    "cappuccino": {"price": Decimal("4.50"), "stock": 40},
    "croissant": {"price": Decimal("3.25"), "stock": 20},
    "muffin": {"price": Decimal("2.95"), "stock": 20},
}


def price_of(item: str) -> Decimal:
    if item not in MENU:
        raise KeyError(f"unknown item: {item}")
    return MENU[item]["price"]
