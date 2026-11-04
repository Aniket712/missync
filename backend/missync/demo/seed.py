"""Deterministic synthetic e-commerce data for the demo and tests (SQLite)."""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SCHEMA = """
create table customers (
  customer_id integer primary key,
  email text not null,
  country text,
  segment text,
  signup_date date
);
create table products (
  product_id integer primary key,
  name text not null,
  category text,
  unit_price decimal(10,2)
);
create table orders (
  order_id integer primary key,
  customer_id integer not null,
  order_date date not null,
  status text not null,
  amount decimal(10,2),
  discount_code text
);
create table order_items (
  item_id integer primary key,
  order_id integer not null,
  product_id integer not null,
  quantity integer not null,
  unit_price decimal(10,2)
);
create table segment_map (
  country text primary key,
  segment text not null
);
create view v_daily_revenue as
  select order_date, count(*) as orders, sum(amount) as revenue
  from orders where status = 'completed' group by order_date;
create view v_customer_ltv as
  select c.customer_id, c.country, count(o.order_id) as order_count, coalesce(sum(o.amount), 0) as lifetime_value
  from customers c left join orders o on o.customer_id = c.customer_id and o.status = 'completed'
  group by c.customer_id, c.country;
create view v_order_details as
  select o.order_id, o.order_date, c.email, o.amount
  from orders o join customers c on c.customer_id = o.customer_id;
"""

COUNTRIES = ["US", "CA", "GB", "DE", "FR", "BR", "IN", "AU"]
SEGMENTS = ["consumer", "smb", "enterprise"]
CATEGORIES = ["books", "home", "toys", "garden", "sports"]

# Registered downstream assets for the demo (name, kind, depends_on)
DEMO_ASSETS = [
    ("Revenue Dashboard", "dashboard", ["v_daily_revenue.revenue", "v_daily_revenue.order_date"]),
    ("Finance Monthly Export", "export", ["orders.amount", "orders.order_date"]),
    ("Churn Model Features", "ml_features", ["v_customer_ltv.lifetime_value", "v_customer_ltv.order_count"]),
    ("Customer Support Console", "application", ["v_order_details"]),
]


def build_demo_db(path: Path, seed: int = 42) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    rnd = random.Random(seed)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    start = date(2023, 1, 1)
    con.executemany(
        "insert into customers values (?,?,?,?,?)",
        [
            (i, f"user{i}@shop-demo.test", rnd.choice(COUNTRIES), rnd.choice(SEGMENTS),
             (start + timedelta(days=rnd.randint(0, 700))).isoformat())
            for i in range(1, 1001)
        ],
    )
    prices = {}
    prods = []
    for i in range(1, 61):
        prices[i] = round(rnd.uniform(5, 120), 2)
        prods.append((i, f"Product {i}", rnd.choice(CATEGORIES), prices[i]))
    con.executemany("insert into products values (?,?,?,?)", prods)
    orders, items = [], []
    item_id = 1
    for oid in range(1, 5001):
        n = rnd.randint(1, 4)
        total = 0.0
        for _ in range(n):
            pid = rnd.randint(1, 60)
            qty = rnd.randint(1, 3)
            items.append((item_id, oid, pid, qty, prices[pid]))
            item_id += 1
            total += qty * prices[pid]
        r = rnd.random()
        status = "completed" if r < 0.80 else "cancelled" if r < 0.88 else "refunded" if r < 0.94 else "pending"
        code = rnd.choice(["SPRING10", "VIP5", "WELCOME"]) if rnd.random() < 0.3 else None
        orders.append((oid, rnd.randint(1, 1000), (start + timedelta(days=rnd.randint(0, 729))).isoformat(),
                       status, round(total, 2), code))
    con.executemany("insert into orders values (?,?,?,?,?,?)", orders)
    con.executemany("insert into order_items values (?,?,?,?,?)", items)
    # Only some countries are mapped: used by the data-quality regression scenario.
    con.executemany("insert into segment_map values (?,?)",
                    [("US", "consumer"), ("CA", "consumer"), ("GB", "smb"), ("DE", "enterprise")])
    con.commit()
    con.close()
    return path
