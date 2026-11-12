"""Build data/bean_byte.db: a small, deterministic point-of-sale database for the Bean & Byte coffee chain.

The data has the kind of trap real business data has: gift-card loads and refunds sit in the same
transactions table as sales, under cryptic one-letter codes. The team's definition of "weekly sales"
excludes both, but nothing in the schema says so. An agent has to be told once, and then remember.

    python data/make_data.py
"""
import datetime as dt
import pathlib
import random
import sqlite3

DB = pathlib.Path(__file__).resolve().parent / "bean_byte.db"
START, END = dt.date(2026, 9, 28), dt.date(2026, 11, 10)   # Monday Sep 28 .. Tuesday Nov 10

LOCATIONS = [  # loc_code, name, borough, opened, base daily sales count
    ("MH-SOHO", "SoHo", "Manhattan", "2019-04-02", 310),
    ("MH-MID", "Midtown", "Manhattan", "2020-09-14", 360),
    ("MH-UWS", "Upper West Side", "Manhattan", "2021-03-01", 240),
    ("BK-PS", "Park Slope", "Brooklyn", "2021-06-12", 220),
    ("BK-WB", "Williamsburg", "Brooklyn", "2022-02-20", 280),
    ("BK-DUM", "DUMBO", "Brooklyn", "2023-05-08", 190),
    ("QN-AST", "Astoria", "Queens", "2024-10-01", 150),
]

MENU = [  # item_id, name, category, price
    (1, "Latte", "espresso", 5.25), (2, "Oat Latte", "espresso", 5.95), (3, "Cappuccino", "espresso", 4.95),
    (4, "Americano", "espresso", 3.95), (5, "Cold Brew", "cold", 4.75), (6, "Iced Oat Latte", "cold", 6.25),
    (7, "Drip Coffee", "brewed", 2.95), (8, "Chai Latte", "tea", 5.15), (9, "Matcha Latte", "tea", 5.75),
    (10, "Croissant", "bakery", 3.75), (11, "Banana Bread", "bakery", 3.95), (12, "Breakfast Sandwich", "food", 7.50),
]
WEIGHTS = [16, 14, 8, 9, 10, 9, 12, 5, 6, 9, 5, 7]
DOW = [1.00, 0.97, 1.00, 1.03, 1.10, 1.22, 1.15]           # Mon..Sun traffic


def main() -> None:
    rnd = random.Random(42)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE locations (loc_code TEXT PRIMARY KEY, name TEXT, borough TEXT, opened DATE);
        CREATE TABLE menu (item_id INTEGER PRIMARY KEY, name TEXT, category TEXT, price_usd REAL);
        CREATE TABLE pos_txn (txn_id INTEGER PRIMARY KEY, loc_code TEXT, ts TEXT, txn_type TEXT,
                              amount_usd REAL, channel TEXT);
        CREATE TABLE txn_lines (txn_id INTEGER, item_id INTEGER, qty INTEGER);
        """
    )
    con.executemany("INSERT INTO locations VALUES (?,?,?,?)", [l[:4] for l in LOCATIONS])
    con.executemany("INSERT INTO menu VALUES (?,?,?,?)", MENU)
    txn, lines = [], []
    tid = 100000
    day = START
    while day <= END:
        week = (day - START).days // 7
        for code, _, _, _, base in LOCATIONS:
            growth = 1 + 0.015 * week + (0.05 if code == "BK-PS" and week == 5 else 0)   # Park Slope: a good week Nov 2-8
            n = int(base * DOW[day.weekday()] * growth * rnd.uniform(0.94, 1.06))
            for _ in range(n):
                tid += 1
                ts = dt.datetime.combine(day, dt.time(6, 30)) + dt.timedelta(minutes=rnd.randint(0, 13 * 60))
                k = rnd.choices([1, 2, 3], [70, 24, 6])[0]
                items = rnd.choices(MENU, WEIGHTS, k=k)
                amount = round(sum(i[3] for i in items), 2)
                txn.append((tid, code, ts.isoformat(sep=" "), "S", amount, rnd.choices(["counter", "app", "delivery"], [62, 30, 8])[0]))
                lines.extend((tid, i[0], 1) for i in items)
            for _ in range(int(n * rnd.uniform(0.035, 0.05))):          # gift-card loads: money in, not sales
                tid += 1
                ts = dt.datetime.combine(day, dt.time(7, 0)) + dt.timedelta(minutes=rnd.randint(0, 12 * 60))
                txn.append((tid, code, ts.isoformat(sep=" "), "G", float(rnd.choice([25, 25, 50, 50, 100])), rnd.choice(["counter", "app"])))
            for _ in range(int(n * rnd.uniform(0.006, 0.012))):         # refunds: negative amounts
                tid += 1
                ts = dt.datetime.combine(day, dt.time(7, 0)) + dt.timedelta(minutes=rnd.randint(0, 12 * 60))
                txn.append((tid, code, ts.isoformat(sep=" "), "R", -round(rnd.choice(MENU)[3] * rnd.choice([1, 1, 2]), 2), "counter"))
        day += dt.timedelta(days=1)
    con.executemany("INSERT INTO pos_txn VALUES (?,?,?,?,?,?)", txn)
    con.executemany("INSERT INTO txn_lines VALUES (?,?,?)", lines)
    con.commit()
    stores = len(LOCATIONS)
    kinds = dict(con.execute("SELECT txn_type, COUNT(*) FROM pos_txn GROUP BY 1").fetchall())
    print(f"built {DB.relative_to(DB.parent.parent)}: {stores} stores, {len(txn):,} transactions, {START:%b %d} to {END:%b %d, %Y}")
    print(f"  S sales {kinds['S']:,} · G gift-card loads {kinds['G']:,} · R refunds {kinds['R']:,}")


if __name__ == "__main__":
    main()
