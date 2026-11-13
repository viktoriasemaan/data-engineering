from decimal import Decimal

import pytest

from coffee_orders.orders import Shop
from coffee_orders.pricing import total


def test_total_with_gold_discount_and_tax():
    # 2 lattes = 9.50, minus 10% = 8.55, plus 8.25% tax = 9.255... -> 9.26
    assert total({"latte": 2}, "gold") == Decimal("9.26")


def test_place_order_takes_stock_and_records_sale():
    shop = Shop()
    order = shop.place_order({"espresso": 2, "croissant": 1}, None)
    assert shop.inventory.stock["espresso"] == 48
    assert shop.ledger.balance() == order.paid


def test_unknown_tier_rejected():
    with pytest.raises(ValueError):
        total({"latte": 1}, "platinum")
