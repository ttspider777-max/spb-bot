import json
import sqlite3
import time
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

REFERRAL_CREDIT = 500
KOPECKS_PER_STAR = 132
RESERVATION_SECONDS = 900

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT,
    joined INTEGER NOT NULL, seen INTEGER NOT NULL, blocked INTEGER DEFAULT 0,
    referrer INTEGER REFERENCES users(id), state TEXT
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY, category INTEGER NOT NULL REFERENCES categories(id),
    title TEXT NOT NULL, description TEXT NOT NULL, price INTEGER NOT NULL CHECK(price > 0),
    stock INTEGER NOT NULL CHECK(stock >= 0), mode TEXT NOT NULL, target TEXT NOT NULL DEFAULT '',
    photo TEXT, active INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY, payload TEXT NOT NULL UNIQUE, user INTEGER NOT NULL REFERENCES users(id),
    product INTEGER NOT NULL REFERENCES products(id), title TEXT NOT NULL, description TEXT NOT NULL,
    qty INTEGER NOT NULL, unit INTEGER NOT NULL, total INTEGER NOT NULL,
    credit INTEGER NOT NULL, referral_credit INTEGER NOT NULL,
    mode TEXT NOT NULL, target TEXT NOT NULL, revision INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open', charged TEXT UNIQUE, started INTEGER NOT NULL,
    reserved INTEGER, checkout TEXT, reject_reason TEXT, delivery TEXT,
    invite TEXT UNIQUE, invite_name TEXT, invite_until INTEGER,
    joined INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS orders_user ON orders(user, id);
CREATE INDEX IF NOT EXISTS orders_status ON orders(status, reserved);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id),
    bucket TEXT NOT NULL, amount INTEGER NOT NULL, reason TEXT NOT NULL,
    created INTEGER NOT NULL, reference TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ledger_user ON ledger(user, bucket);
CREATE TABLE IF NOT EXISTS promos (
    code TEXT PRIMARY KEY, amount INTEGER NOT NULL CHECK(amount > 0), remaining INTEGER NOT NULL CHECK(remaining >= 0)
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY, user INTEGER NOT NULL REFERENCES users(id), closed INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_messages (
    id INTEGER PRIMARY KEY, ticket INTEGER NOT NULL REFERENCES tickets(id),
    author INTEGER NOT NULL, source INTEGER NOT NULL, body TEXT,
    UNIQUE(author, source)
);
CREATE TABLE IF NOT EXISTS subscriptions (chat TEXT PRIMARY KEY, url TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL, due INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0
);
"""


class ShopError(ValueError):
    pass


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)
        with self.db:
            columns = {row["name"] for row in self.all("PRAGMA table_info(orders)")}
            additions = {
                "method": "TEXT NOT NULL DEFAULT 'stars'",
                "receipt_kind": "TEXT",
                "receipt_file": "TEXT",
                "receipt_unique": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    self.run(f"ALTER TABLE orders ADD COLUMN {name} {definition}")
            products = {row["name"] for row in self.all("PRAGMA table_info(products)")}
            if "rub_price" not in products:
                self.run("ALTER TABLE products ADD COLUMN rub_price INTEGER")
            self.run("CREATE UNIQUE INDEX IF NOT EXISTS orders_receipt ON orders(receipt_unique) WHERE receipt_unique IS NOT NULL")

    def one(self, sql, *args):
        return self.db.execute(sql, args).fetchone()

    def all(self, sql, *args):
        return self.db.execute(sql, args).fetchall()

    def run(self, sql, *args):
        return self.db.execute(sql, args)

    def get(self, key, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", key)
        return json.loads(row["value"]) if row else default

    def put(self, key, value):
        self.run("INSERT OR REPLACE INTO settings VALUES(?,?)", key, json.dumps(value, ensure_ascii=False))

    def touch(self, actor, referrer=None):
        user = actor["id"]
        now = int(time.time())
        name = " ".join(filter(None, [actor.get("first_name"), actor.get("last_name")]))
        if user == referrer or not self.one("SELECT 1 FROM users WHERE id=?", referrer):
            referrer = None
        self.run(
            """INSERT INTO users(id,name,username,joined,seen,referrer) VALUES(?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, username=excluded.username, seen=excluded.seen""",
            user, name, actor.get("username"), now, now, referrer,
        )

    def state(self, user, action=None, *args):
        value = json.dumps([action, *args]) if action else None
        self.run("UPDATE users SET state=? WHERE id=?", value, user)

    def balances(self, user):
        result = {"main": 0, "referral": 0}
        for row in self.all("SELECT bucket,SUM(amount) AS total FROM ledger WHERE user=? GROUP BY bucket", user):
            result[row["bucket"]] = row["total"]
        return result

    def credit(self, user, bucket, amount, reason, reference=None):
        if amount:
            self.run(
                "INSERT INTO ledger(user,bucket,amount,reason,created,reference) VALUES(?,?,?,?,?,?)",
                user, bucket, amount, reason, int(time.time()), reference,
            )

    def enqueue(self, key, kind, **data):
        self.run("INSERT OR IGNORE INTO jobs(key,kind,data) VALUES(?,?,?)", key, kind, json.dumps(data, ensure_ascii=False))

    def expired(self, now=None):
        now = int(time.time()) if now is None else now
        for row in self.all("SELECT * FROM orders WHERE status='reserved' AND reserved <= ?", now - RESERVATION_SECONDS):
            self.release(row)
            self.run("UPDATE orders SET status='expired' WHERE id=?", row["id"])
        self.run("UPDATE orders SET status='expired' WHERE status='open' AND started <= ?", now - 86400)

    def item(self, item):
        return self.one(
            """SELECT p.*, c.active AS category_active FROM products p JOIN categories c ON c.id=p.category
               WHERE p.id=?""", item,
        )

    def order(self, order):
        return self.one("SELECT * FROM orders WHERE id=?", order)

    @staticmethod
    def unit_price(item, method):
        if method == "sbp":
            return item["rub_price"] or item["price"] * KOPECKS_PER_STAR
        return item["price"]

    def checkout_price(self, user, item, qty, method, use_credit):
        unit = self.unit_price(item, method)
        gross = unit * qty
        if gross > (100000000 if method == "sbp" else 1000000):
            raise ShopError("amount_range")
        wallet = self.balances(user) if use_credit else {"main": 0, "referral": 0}
        rate, minimum = (1, 100) if method == "sbp" else (KOPECKS_PER_STAR, 1)
        discount = min(gross - minimum, (wallet["main"] + wallet["referral"]) // rate)
        cost = discount * rate
        main = min(wallet["main"], cost)
        return unit, gross - discount, main, cost - main

    def create_order(self, user, product, qty, use_credit, method="stars"):
        item = self.item(product)
        if not item or not item["active"] or not item["category_active"]:
            raise ShopError("unavailable")
        if not 1 <= qty <= min(10000, item["stock"]) or (item["mode"] == "invite" and qty != 1):
            raise ShopError("stock")
        unit, total, main, referral = self.checkout_price(user, item, qty, method, use_credit)
        cursor = self.run(
            """INSERT INTO orders(payload,user,product,title,description,qty,unit,total,credit,referral_credit,
                                   mode,target,revision,started,invite_name,method)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            token_urlsafe(24), user, product, item["title"], item["description"], qty, unit,
            total, main, referral, item["mode"], item["target"], item["revision"],
            int(time.time()), uuid4().hex, method,
        )
        return self.order(cursor.lastrowid)

    def reserve(self, user, payment):
        row = self.one("SELECT * FROM orders WHERE payload=?", payment["invoice_payload"])
        if not self.payment_matches(row, user, payment) or row["status"] not in {"open", "reserved"}:
            raise ShopError("invalid_invoice")
        if self.one("SELECT blocked FROM users WHERE id=?", user)["blocked"]:
            raise ShopError("banned")
        if row["status"] == "reserved":
            if row["checkout"] != payment["id"]:
                raise ShopError("invalid_invoice")
            return
        self.take_stock(row)
        self.run("UPDATE orders SET status='reserved', reserved=?, checkout=? WHERE id=?",
                 int(time.time()), payment["id"], row["id"])

    def take_stock(self, row):
        user = row["user"]
        item = self.item(row["product"])
        if (not item or not item["active"] or not item["category_active"]
                or item["revision"] != row["revision"] or item["stock"] < row["qty"]):
            raise ShopError("stock")
        balances = self.balances(user)
        if balances["main"] < row["credit"] or balances["referral"] < row["referral_credit"]:
            raise ShopError("balance_changed")
        self.run("UPDATE products SET stock=stock-? WHERE id=?", row["qty"], row["product"])
        self.credit(user, "main", -row["credit"], f"Заказ №{row['id']}")
        self.credit(user, "referral", -row["referral_credit"], f"Заказ №{row['id']}")

    @staticmethod
    def payment_matches(row, user, payment):
        return (row and row["method"] == "stars" and row["user"] == user and payment["currency"] == "XTR"
                and row["total"] == payment["total_amount"])

    def receipt_order(self, user, order):
        row = self.order(order)
        if not row or row["user"] != user or row["method"] != "sbp" or row["status"] not in {"open", "expired"}:
            raise ShopError("already_handled")
        return row

    def add_receipt(self, user, order, kind, media):
        row = self.receipt_order(user, order)
        unique = media["file_unique_id"]
        if self.one("SELECT id FROM orders WHERE receipt_unique=?", unique):
            raise ShopError("receipt_duplicate")
        reserved = None
        try:
            self.take_stock(row)
        except ShopError as error:
            if str(error) not in {"stock", "balance_changed"}:
                raise
        else:
            reserved = int(time.time())
        self.run(
            """UPDATE orders SET status='review', reserved=?, receipt_kind=?, receipt_file=?, receipt_unique=?
               WHERE id=?""", reserved, kind, media["file_id"], unique, order,
        )
        self.state(user)
        self.enqueue(f"receipt:{order}", "receipt", order=order)

    def release(self, row):
        self.run("UPDATE products SET stock=stock+? WHERE id=?", row["qty"], row["product"])
        reason = f"Возврат по заказу №{row['id']}"
        self.credit(row["user"], "main", row["credit"], reason)
        self.credit(row["user"], "referral", row["referral_credit"], reason)

    def paid(self, user, payment):
        charge = payment["telegram_payment_charge_id"]
        if self.one("SELECT 1 FROM orders WHERE charged=?", charge):
            return
        row = self.one("SELECT * FROM orders WHERE payload=?", payment["invoice_payload"])
        if not self.payment_matches(row, user, payment) or row["status"] != "reserved":
            self.enqueue(f"unexpected:{charge}", "unexpected", user=user, charge=charge)
            return
        order = row["id"]
        status = "fulfilling" if row["mode"] != "manual" else "review"
        self.run("UPDATE orders SET status=?, charged=? WHERE id=?", status, charge, order)
        self.enqueue(f"paid:{order}", "paid", order=order)
        if status == "review":
            self.enqueue(f"review:{order}", "review", order=order)
        else:
            self.enqueue(f"deliver:{order}", "deliver", order=order)

    def reject(self, order, reason):
        row = self.order(order)
        if not row or row["status"] != "review":
            raise ShopError("already_handled")
        if row["method"] == "sbp":
            if row["reserved"]:
                self.release(row)
            self.run("UPDATE orders SET status='declined', reject_reason=? WHERE id=?", reason, order)
            self.enqueue(f"declined:{order}", "declined", order=order)
            return
        self.run("UPDATE orders SET status='refunding', reject_reason=? WHERE id=?", reason, order)
        self.enqueue(f"refund:{order}", "refund", order=order)

    def approve(self, order, delivery):
        row = self.order(order)
        if not row or row["status"] != "review":
            raise ShopError("already_handled")
        if row["method"] == "sbp":
            if not row["reserved"]:
                self.take_stock(row)
                self.run("UPDATE orders SET reserved=? WHERE id=?", int(time.time()), order)
            self.enqueue(f"paid:{order}", "paid", order=order)
        self.run("UPDATE orders SET status='fulfilling', delivery=? WHERE id=?", delivery, order)
        self.enqueue(f"deliver:{order}", "deliver", order=order)

    def referred_sale(self, row):
        buyer = self.one("SELECT referrer FROM users WHERE id=?", row["user"])
        key = f"referral:{row['user']}"
        if buyer["referrer"] and not self.one("SELECT 1 FROM ledger WHERE reference=?", key):
            referrer = buyer["referrer"]
            self.credit(referrer, "referral", REFERRAL_CREDIT, f"Первая покупка приглашённого {row['user']}", key)
            self.enqueue(key, "referral", user=referrer)

    def redeem(self, user, code):
        row = self.one("SELECT * FROM promos WHERE code=?", code)
        key = f"promo:{code}:{user}"
        if not row or not row["remaining"] or self.one("SELECT 1 FROM ledger WHERE reference=?", key):
            raise ShopError("promo_invalid")
        self.run("UPDATE promos SET remaining=remaining-1 WHERE code=?", code)
        self.credit(user, "main", row["amount"], f"Промокод {code}", key)
        return row["amount"]
