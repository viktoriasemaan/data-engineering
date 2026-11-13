import argparse

from .orders import Shop


def parse_items(pairs: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in pairs:
        name, _, qty = p.partition("=")
        out[name] = out.get(name, 0) + int(qty or 1)
    return out


def main(argv=None, shop=None):
    shop = shop or Shop()
    ap = argparse.ArgumentParser(prog="coffee_orders")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("order"); o.add_argument("items", nargs="+"); o.add_argument("--tier")
    args = ap.parse_args(argv)
    if args.cmd == "order":
        order = shop.place_order(parse_items(args.items), args.tier)
        print(f"order {order.id} paid {order.paid}")
    return shop


if __name__ == "__main__":
    main()
