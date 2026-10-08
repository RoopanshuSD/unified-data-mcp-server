"""Create the demo data sources: data/shop.db (12 tables) and data/hr.db (restricted HR data).

    python scripts/make_demo_data.py [out_dir]
Deterministic (seeded), so benchmarks are reproducible.
"""
import random
import sqlite3
import sys
from pathlib import Path

SHOP = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, country TEXT, created_at TEXT);
CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL,
                       supplier_id INTEGER REFERENCES suppliers(id));
CREATE TABLE inventory (product_id INTEGER PRIMARY KEY REFERENCES products(id), on_hand INTEGER, warehouse TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), status TEXT,
                     total REAL, created_at TEXT);
CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
                          product_id INTEGER REFERENCES products(id), quantity INTEGER, unit_price REAL);
CREATE TABLE payments (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), amount REAL, method TEXT,
                       paid_at TEXT);
CREATE TABLE shipments (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), carrier TEXT,
                        shipped_at TEXT, updated_at TEXT);
CREATE TABLE refunds (id INTEGER PRIMARY KEY, payment_id INTEGER REFERENCES payments(id), amount REAL, reason TEXT);
CREATE TABLE reviews (id INTEGER PRIMARY KEY, product_id INTEGER REFERENCES products(id),
                      customer_id INTEGER REFERENCES customers(id), rating INTEGER, body TEXT);
CREATE TABLE coupons (code TEXT PRIMARY KEY, pct_off INTEGER, expires_at TEXT);
CREATE TABLE support_tickets (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                              subject TEXT, status TEXT, opened_at TEXT);
"""
HR = """
CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, department TEXT, manager_id INTEGER, hired_at TEXT);
CREATE TABLE salaries (employee_id INTEGER PRIMARY KEY REFERENCES employees(id), base REAL, bonus REAL);
"""


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    for f in ("shop.db", "hr.db"):
        (out / f).unlink(missing_ok=True)
    s = sqlite3.connect(out / "shop.db")
    s.executescript(SHOP)
    countries = ["IN", "US", "DE", "GB", "SG"]
    day = lambda: f"2026-{rnd.randint(1, 9):02d}-{rnd.randint(1, 28):02d}"  # noqa: E731
    s.executemany("INSERT INTO customers VALUES (?,?,?,?,?)",
                  [(i, f"Customer {i}", f"c{i}@example.com", rnd.choice(countries), day()) for i in range(1, 501)])
    s.executemany("INSERT INTO suppliers VALUES (?,?,?)", [(i, f"Supplier {i}", rnd.choice(countries)) for i in range(1, 21)])
    cats = ["books", "electronics", "home", "toys", "garden"]
    s.executemany("INSERT INTO products VALUES (?,?,?,?,?)",
                  [(i, f"Product {i}", rnd.choice(cats), round(rnd.uniform(3, 400), 2), rnd.randint(1, 20))
                   for i in range(1, 201)])
    s.executemany("INSERT INTO inventory VALUES (?,?,?)", [(i, rnd.randint(0, 500), rnd.choice("ABC")) for i in range(1, 201)])
    orders, items, pays, ships = [], [], [], []
    for o in range(1, 2001):
        n, total = rnd.randint(1, 4), 0.0
        for _ in range(n):
            pid, q, price = rnd.randint(1, 200), rnd.randint(1, 3), round(rnd.uniform(3, 400), 2)
            items.append((len(items) + 1, o, pid, q, price))
            total += q * price
        d = day()
        orders.append((o, rnd.randint(1, 500), rnd.choice(["placed", "shipped", "delivered", "cancelled"]),
                       round(total, 2), d))
        pays.append((o, o, round(total, 2), rnd.choice(["card", "upi", "paypal"]), d))
        ships.append((o, o, rnd.choice(["DHL", "UPS", "BlueDart"]), d, d))
    s.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", orders)
    s.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", items)
    s.executemany("INSERT INTO payments VALUES (?,?,?,?,?)", pays)
    s.executemany("INSERT INTO shipments VALUES (?,?,?,?,?)", ships)
    s.executemany("INSERT INTO refunds VALUES (?,?,?,?)",
                  [(i, rnd.randint(1, 2000), round(rnd.uniform(5, 100), 2), "damaged") for i in range(1, 101)])
    s.executemany("INSERT INTO reviews VALUES (?,?,?,?,?)",
                  [(i, rnd.randint(1, 200), rnd.randint(1, 500), rnd.randint(1, 5), "ok") for i in range(1, 1001)])
    s.executemany("INSERT INTO coupons VALUES (?,?,?)", [(f"SAVE{i}", i * 5, "2026-12-31") for i in range(1, 6)])
    s.executemany("INSERT INTO support_tickets VALUES (?,?,?,?,?)",
                  [(i, rnd.randint(1, 500), "late delivery", rnd.choice(["open", "closed"]), day()) for i in range(1, 301)])
    s.commit()
    s.close()
    h = sqlite3.connect(out / "hr.db")
    h.executescript(HR)
    h.executemany("INSERT INTO employees VALUES (?,?,?,?,?)",
                  [(i, f"Employee {i}", rnd.choice(["eng", "sales", "ops"]), max(1, i // 10), day()) for i in range(1, 101)])
    h.executemany("INSERT INTO salaries VALUES (?,?,?)",
                  [(i, rnd.randint(20, 90) * 1000, rnd.randint(0, 10) * 1000) for i in range(1, 101)])
    h.commit()
    h.close()
    print(f"wrote {out / 'shop.db'} and {out / 'hr.db'}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data"))
