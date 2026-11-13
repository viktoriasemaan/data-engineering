"""Hidden checks: never shown to the agents. Run after each attempt."""
from decimal import Decimal

import pytest

from coffee_orders.__main__ import main
from coffee_orders.orders import Shop


def test_piecewise_refunds_sum_to_paid_exactly():
    shop = Shop()
    order = shop.place_order({"croissant": 3}, "silver")
    parts = [shop.refund(order.id, {"croissant": 1}) for _ in range(3)]
    assert sum(parts) == order.paid
    assert order.status == "refunded"


def test_partial_then_rest_balances_ledger_to_zero():
    shop = Shop()
    order = shop.place_order({"latte": 3, "muffin": 2}, "gold")
    shop.refund(order.id, {"latte": 1})
    shop.refund(order.id, {"muffin": 1})
    shop.refund(order.id)
    assert shop.ledger.balance() == Decimal("0")
    assert order.refunded == {"latte": 3, "muffin": 2}


def test_refund_share_of_paid_amount():
    shop = Shop()
    order = shop.place_order({"latte": 1, "espresso": 1}, None)
    assert shop.refund(order.id, {"espresso": 1}) == Decimal("3.25")


def test_unknown_item_rejected():
    shop = Shop()
    order = shop.place_order({"latte": 1}, None)
    with pytest.raises(ValueError):
        shop.refund(order.id, {"muffin": 1})


def test_already_refunded_item_rejected():
    shop = Shop()
    order = shop.place_order({"latte": 1}, None)
    shop.refund(order.id)
    with pytest.raises(ValueError):
        shop.refund(order.id, {"latte": 1})


def test_full_refund_restocks_everything():
    shop = Shop()
    order = shop.place_order({"cappuccino": 4, "muffin": 2}, "gold")
    shop.refund(order.id)
    assert shop.inventory.stock["cappuccino"] == 40
    assert shop.inventory.stock["muffin"] == 20


def test_cli_refund(capsys):
    shop = Shop()
    order = shop.place_order({"latte": 2}, None)
    main(["refund", str(order.id), "latte=1"], shop)
    out = capsys.readouterr().out.strip()
    assert out.startswith("refunded ")
    assert Decimal(out.split()[1]) == shop.ledger.entries[-1].amount * -1
