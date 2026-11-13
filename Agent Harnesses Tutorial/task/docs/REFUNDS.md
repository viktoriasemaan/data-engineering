# Refunds

Add refunds to the shop.

- `Shop.refund(order_id, items=None)` returns the refunded amount as a `Decimal`.
  `items=None` refunds everything that has not been refunded yet.
- A refund of an item can never exceed what was bought minus what was already refunded.
  Asking for more, or for an item that is not on the order, raises `ValueError`.
- The refund amount is the item's share of what the customer actually paid
  (after the loyalty discount, with tax), rounded to cents. The total refunded for an
  order must never exceed `order.paid`; when an order becomes fully refunded, the total
  refunded equals `order.paid` exactly.
- Refunded items go back into inventory.
- Each refund is recorded in the ledger as a `"refund"` entry with a negative amount.
- `order.status` becomes `"refunded"` when everything has been refunded, and
  `"partially_refunded"` otherwise. `order.refunded` tracks refunded quantities.
- CLI: `python -m coffee_orders refund <order_id> [item=qty ...]` prints
  `refunded <amount>`.
