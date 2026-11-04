-- Synthetic shop data for Missync (deterministic: uses setseed + arithmetic on series values).
SELECT setseed(0.42);

CREATE TABLE customers (
  customer_id integer PRIMARY KEY,
  email text NOT NULL,
  country text,
  segment text,
  signup_date date
);
CREATE TABLE products (product_id integer PRIMARY KEY, name text NOT NULL, category text, unit_price numeric(10,2));
CREATE TABLE orders (
  order_id integer PRIMARY KEY,
  customer_id integer NOT NULL REFERENCES customers,
  order_date date NOT NULL,
  status text NOT NULL,
  amount numeric(10,2),
  discount_code text
);
CREATE TABLE order_items (
  item_id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES orders,
  product_id integer NOT NULL REFERENCES products, quantity integer NOT NULL, unit_price numeric(10,2)
);
CREATE TABLE segment_map (country text PRIMARY KEY, segment text NOT NULL);

INSERT INTO customers
SELECT i, 'user' || i || '@shop-demo.test',
       (ARRAY['US','CA','GB','DE','FR','BR','IN','AU'])[1 + (i * 7) % 8],
       (ARRAY['consumer','smb','enterprise'])[1 + (i * 5) % 3],
       DATE '2023-01-01' + (i * 13) % 700
FROM generate_series(1, 1000) i;

INSERT INTO products
SELECT i, 'Product ' || i, (ARRAY['books','home','toys','garden','sports'])[1 + i % 5], round((5 + (i * 37) % 115)::numeric, 2)
FROM generate_series(1, 60) i;

INSERT INTO orders
SELECT i, 1 + (i * 31) % 1000, DATE '2023-01-01' + (i * 17) % 730,
       CASE WHEN i % 100 < 80 THEN 'completed' WHEN i % 100 < 88 THEN 'cancelled' WHEN i % 100 < 94 THEN 'refunded' ELSE 'pending' END,
       round((10 + (i * 53) % 400)::numeric + (i % 100) / 100.0, 2),
       CASE WHEN i % 10 < 3 THEN (ARRAY['SPRING10','VIP5','WELCOME'])[1 + i % 3] END
FROM generate_series(1, 5000) i;

INSERT INTO order_items
SELECT i, 1 + i % 5000, 1 + (i * 11) % 60, 1 + i % 3, round((5 + (i * 37) % 115)::numeric, 2)
FROM generate_series(1, 12500) i;

INSERT INTO segment_map VALUES ('US','consumer'),('CA','consumer'),('GB','smb'),('DE','enterprise');

CREATE VIEW v_daily_revenue AS
  SELECT order_date, count(*) AS orders, sum(amount) AS revenue FROM orders WHERE status = 'completed' GROUP BY order_date;
CREATE VIEW v_customer_ltv AS
  SELECT c.customer_id, c.country, count(o.order_id) AS order_count, coalesce(sum(o.amount), 0) AS lifetime_value
  FROM customers c LEFT JOIN orders o ON o.customer_id = c.customer_id AND o.status = 'completed' GROUP BY c.customer_id, c.country;
CREATE VIEW v_order_details AS
  SELECT o.order_id, o.order_date, c.email, o.amount FROM orders o JOIN customers c ON c.customer_id = o.customer_id;

-- Read-only role for Missync discovery (use this in the connection form).
CREATE ROLE missync_ro LOGIN PASSWORD 'missync_ro_dev_only';
GRANT CONNECT ON DATABASE shop TO missync_ro;
GRANT USAGE ON SCHEMA public TO missync_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO missync_ro;
