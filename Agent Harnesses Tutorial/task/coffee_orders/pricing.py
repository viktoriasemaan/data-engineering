from decimal import Decimal, ROUND_HALF_UP

from .catalog import price_of

TAX_RATE = Decimal("0.0825")
LOYALTY = {"gold": Decimal("0.10"), "silver": Decimal("0.05"), None: Decimal("0")}
CENT = Decimal("0.01")


def cents(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def subtotal(items: dict[str, int]) -> Decimal:
    return sum((price_of(i) * q for i, q in items.items()), Decimal("0"))


def total(items: dict[str, int], tier: str | None) -> Decimal:
    """Subtotal, minus the loyalty discount, plus tax, rounded to cents."""
    if tier not in LOYALTY:
        raise ValueError(f"unknown tier: {tier}")
    discounted = subtotal(items) * (1 - LOYALTY[tier])
    return cents(discounted * (1 + TAX_RATE))
