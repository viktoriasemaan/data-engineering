from decimal import Decimal

import pytest

from coffee_orders.orders import Shop


def test_full_refund_returns_what_was_paid():
    shop = Shop()
    order = shop.place_order({"latte": 2}, "gold")
    assert shop.refund(order.id) == order.paid
    assert order.status == "refunded"


def test_partial_refund_restocks_and_records():
    shop = Shop()
    order = shop.place_order({"latte": 2, "muffin": 1}, None)
    amount = shop.refund(order.id, {"muffin": 1})
    assert amount > 0
    assert order.status == "partially_refunded"
    assert shop.inventory.stock["muffin"] == 20
    assert shop.ledger.entries[-1].kind == "refund"
    assert shop.ledger.entries[-1].amount == -amount


def test_cannot_refund_more_than_bought():
    shop = Shop()
    order = shop.place_order({"espresso": 1}, None)
    with pytest.raises(ValueError):
        shop.refund(order.id, {"espresso": 2})
