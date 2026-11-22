import json
import logging
import re
import time
from html import unescape

from admin import Admin
from copybook import Copybook, rub
from store import KOPECKS_PER_STAR, REFERRAL_CREDIT, ShopError
from telegram import TelegramError

LOG = logging.getLogger("shop")
REVIEWS = "https://t.me/heliysrep/18"
CHANNEL = "https://t.me/heliys_funpay"
SBP_PHONE = "79161893553"
SBP_BANK = "Т‑Банк"


class Bot(Admin):
    def __init__(self, api, store, admin):
        self.api = api
        self.s = store
        self.admin = admin
        self.copy = Copybook(store)
        self.username = None

    def b(self, user, key, action=None, **options):
        return self.copy.button(user, key, action, **options)

    def t(self, user, key, **values):
        return self.copy.text(user, key, **values)

    def keyboard(self, user, rows=(), back=None, home=True):
        result = list(rows)
        if back and back != "home":
            result.append([self.b(user, "back", back)])
        if home:
            result.append([self.b(user, "home", "home")])
        return {"inline_keyboard": result}

    def send(self, user, text, rows=(), back=None, photo=None, home=True, preview=False):
        markup = self.keyboard(user, rows, back, home)
        method = "sendPhoto" if photo else "sendMessage"
        if photo and len(text) > 1000:
            self.api.call("sendPhoto", chat_id=user, photo=photo)
            return self.send(user, text, rows, back, home=home, preview=preview)
        params = {"chat_id": user, "parse_mode": "HTML", "reply_markup": markup}
        if photo:
            params.update(photo=photo, caption=text)
        else:
            params.update(text=text, link_preview_options={"is_disabled": True})
        try:
            return self.api.call(method, **params)
        except TelegramError as error:
            details = error.description.lower()
            if preview or error.code != 400 or not any(x in details for x in (
                "entity", "entities", "emoji", "button_text_invalid",
            )):
                raise
            for row in markup["inline_keyboard"]:
                for button in row:
                    button.pop("icon_custom_emoji_id", None)
            field = "caption" if photo else "text"
            params[field] = unescape(re.sub(r"<[^>]+>", "", text))
            params.pop("parse_mode")
            return self.api.call(method, **params)

    def say(self, user, key, rows=(), back=None, photo=None, home=True, **values):
        return self.send(user, self.t(user, key, **values), rows, back, photo, home)

    def gate(self, user):
        if user == self.admin:
            return True
        if self.s.one("SELECT blocked FROM users WHERE id=?", user)["blocked"]:
            self.say(user, "banned", [[self.b(user, "support", "support")]], home=False)
            return False
        rules = self.s.all("SELECT * FROM subscriptions ORDER BY chat")
        missing = []
        try:
            for rule in rules:
                chat = rule["chat"]
                member = self.api.call("getChatMember", chat_id=int(chat) if chat.lstrip("-").isdigit() else chat, user_id=user)
                if member["status"] in {"left", "kicked"} or (
                    member["status"] == "restricted" and not member.get("is_member")
                ):
                    missing.append(rule)
        except TelegramError:
            self.say(user, "subscription_error", [[self.b(user, "support", "support")]])
            return False
        if missing:
            rows = [[self.b(user, "subscription_link", url=rule["url"], n=i)]
                    for i, rule in enumerate(missing, 1)]
            rows += [[self.b(user, "subscribe", "home")], [self.b(user, "support", "support")]]
            self.say(user, "subscription", rows, home=False)
        return not missing

    def home(self, user):
        rows = [
            [self.b(user, "catalog", "catalog"), self.b(user, "links", "links")],
            [self.b(user, "profile", "profile")],
        ]
        name = self.s.one("SELECT name FROM users WHERE id=?", user)["name"]
        self.say(user, "home", rows, photo=self.s.get("welcome_photo"), home=False, name=name)

    def catalog(self, user, section=None, page=0):
        size = 12
        if section is None:
            rows = self.s.all("SELECT * FROM categories WHERE active=1 ORDER BY id LIMIT ? OFFSET ?", size + 1, page * size)
            buttons = [[self.b(user, "category_entry", f"cat:{r['id']}:0", label=r["title"])] for r in rows[:size]]
            self.pages(user, buttons, "catalog", page, len(rows) > size)
            self.say(user, "catalog" if rows else "empty", buttons)
            return
        category = self.s.one("SELECT * FROM categories WHERE id=? AND active=1", section)
        if not category:
            raise ShopError("unavailable")
        rows = self.s.all(
            "SELECT * FROM products WHERE category=? AND active=1 ORDER BY id LIMIT ? OFFSET ?",
            section, size + 1, page * size,
        )
        buttons = [[self.b(user, "product_entry", f"item:{r['id']}", label=f"{r['title']} · {rub(self.s.unit_price(r, 'sbp'))}")]
                   for r in rows[:size]]
        self.pages(user, buttons, f"cat:{section}", page, len(rows) > size)
        self.say(user, "category" if rows else "empty", buttons, "catalog", title=category["title"])

    def pages(self, user, rows, prefix, page, more):
        controls = []
        if page:
            controls.append(self.b(user, "prev", f"{prefix}:{page - 1}"))
        if more:
            controls.append(self.b(user, "next", f"{prefix}:{page + 1}"))
        if controls:
            rows.append(controls)

    def item(self, product):
        item = self.s.item(product)
        if not item or not item["active"] or not item["category_active"]:
            raise ShopError("unavailable")
        return item

    def show_item(self, user, product):
        item = self.item(product)
        rows = [[self.b(user, "buy", f"qty:{product}", style="primary")]] if item["stock"] else []
        self.say(user, "product", rows, f"cat:{item['category']}:0", photo=item["photo"],
                 title=item["title"], description=item["description"], price=item["price"],
                 rubles=rub(self.s.unit_price(item, "sbp")), stock=item["stock"])

    def quantity(self, user, product):
        item = self.item(product)
        limit = min(1 if item["mode"] == "invite" else 10000, item["stock"])
        if not limit:
            raise ShopError("stock")
        with self.s.db:
            self.s.state(user, "quantity", product)
        options = [n for n in (1, 2, 5, 10) if n <= limit]
        buttons = [self.b(user, "quantity_entry", f"quote:{product}:{n}", label=str(n)) for n in options]
        rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
        self.say(user, "quantity", rows, f"item:{product}", max=limit)

    def quote(self, user, product, qty):
        item = self.item(product)
        limit = min(1 if item["mode"] == "invite" else 10000, item["stock"])
        if not 1 <= qty <= limit:
            raise ShopError("stock")
        gross = item["price"] * qty
        discount = min(gross - 1, sum(self.s.balances(user).values()) // KOPECKS_PER_STAR)
        rows = []
        sbp_total = self.s.unit_price(item, "sbp") * qty
        if sbp_total <= 100000000:
            rows.append([self.b(user, "sbp", f"buy_sbp:{product}:{qty}:0", style="primary", amount=rub(sbp_total))])
            _, sbp_with_credit, _, _ = self.s.checkout_price(user, item, qty, "sbp", True)
            if sbp_with_credit < sbp_total:
                rows.append([self.b(user, "sbp_discount", f"buy_sbp:{product}:{qty}:1", amount=rub(sbp_with_credit))])
        if gross <= 1000000:
            rows.append([self.b(user, "pay", f"buy:{product}:{qty}:0", amount=gross)])
            if discount:
                rows.append([self.b(user, "discount", f"buy:{product}:{qty}:1", style="success", amount=gross - discount)])
        if not rows:
            raise ShopError("amount_range")
        self.say(user, "quote", rows, f"item:{product}", title=item["title"], qty=qty, gross=gross, discount=discount)

    def sbp_details(self, user, row):
        number = row["id"]
        rows = [[self.b(user, "sbp_paid", f"receipt:{number}", style="success")]]
        self.say(user, "sbp_details", rows, f"order:{number}", order=number, amount=rub(row["total"]),
                 phone=SBP_PHONE, bank=SBP_BANK)

    def receipt_message(self, user, order, msg):
        if msg.get("photo"):
            kind, media = "photo", msg["photo"][-1]
        elif msg.get("document", {}).get("mime_type") in {"application/pdf", "image/jpeg", "image/png", "image/webp"}:
            kind, media = "document", msg["document"]
        else:
            self.say(user, "sbp_prompt", back=f"order:{order}", order=order)
            return
        with self.s.db:
            self.s.add_receipt(user, order, kind, media)
        self.say(user, "sbp_received", [[self.b(user, "see_order", f"order:{order}")]], order=order)

    def invoice(self, user, row):
        title = row["title"][:32]
        description = row["description"][:255] or title
        label = unescape(self.t(user, "invoice_line", order=row["id"], qty=row["qty"]))
        label = re.sub(r"<[^>]+>", "", label)[:32] or title
        self.api.call("sendInvoice", chat_id=user, title=title, description=description, payload=row["payload"],
                      currency="XTR", provider_token="", prices=[{"label": label, "amount": row["total"]}],
                      start_parameter=f"order_{row['id']}")
        self.say(user, "invoice", [[self.b(user, "see_order", f"order:{row['id']}")]], "pending")

    def profile(self, user):
        balance = self.s.balances(user)
        counts = self.s.one(
            """SELECT COUNT(*) AS orders, COALESCE(SUM(CASE WHEN status='delivered' THEN qty END),0) AS units
               FROM orders WHERE user=?""", user,
        )
        groups = [("topup", "purchases"), ("stats",), ("referral",), ("promo", "transactions"), ("language",), ("pending",)]
        rows = [[self.b(user, key, key) for key in group] for group in groups]
        self.say(user, "profile", rows, id=user, main=rub(balance["main"]), referral=rub(balance["referral"]), **dict(counts))

    def orders(self, user, pending, page):
        where = "AND status IN ('open','reserved')" if pending else "AND status NOT IN ('open','reserved')"
        rows = self.s.all(
            f"SELECT * FROM orders WHERE user=? {where} ORDER BY id DESC LIMIT 13 OFFSET ?", user, page * 12,
        )
        buttons = [[self.b(user, "order_entry", f"order:{r['id']}", label=f"№{r['id']} · {r['title']}")] for r in rows[:12]]
        self.pages(user, buttons, "pending" if pending else "purchases", page, len(rows) > 12)
        key = ("pending" if pending else "orders") if rows else "empty"
        self.say(user, key, buttons, "profile")

    def order_view(self, user, number):
        row = self.s.order(number)
        if not row or row["user"] != user:
            raise ShopError("unavailable")
        pending = row["status"] in {"open", "reserved"}
        buttons = []
        is_sbp = row["method"] == "sbp"
        if is_sbp and row["status"] in {"open", "expired"}:
            if row["status"] == "open":
                buttons.append([self.b(user, "sbp", f"invoice:{number}", amount=rub(row["total"]))])
            buttons.append([self.b(user, "sbp_paid", f"receipt:{number}")])
        elif pending:
            buttons.append([self.b(user, "pay", f"invoice:{number}", amount=row["total"])])
        if row["status"] in {"delivered", "refunded", "review", "declined"}:
            buttons.append([self.b(user, "support", "support")])
        status = self.t(user, "sbp_status_review" if is_sbp and row["status"] == "review" else f"status_{row['status']}")
        self.say(user, "sbp_order" if is_sbp else "order", buttons, "pending" if pending else "purchases",
                 id=number, title=row["title"], qty=row["qty"],
                 total=rub(row["total"]) if is_sbp else row["total"], status=unescape(status))
        if row["status"] == "delivered":
            self.show_delivery(row)

    def show_delivery(self, row):
        user = row["user"]
        if row["mode"] != "invite":
            self.say(user, "delivered", order=row["id"], delivery=row["delivery"] or row["target"])
        elif row["joined"]:
            self.say(user, "invite_used")
        elif row["invite_until"] <= int(time.time()):
            self.say(user, "invite_expired", [[self.b(user, "support", "support")]])
        else:
            link = row["invite"]
            self.say(user, "welcome_invite", [[self.b(user, "open_link", url=link)]], link=link)

    def ticket_list(self, user, page=0):
        rows = self.s.all("SELECT * FROM tickets WHERE user=? ORDER BY id DESC LIMIT 13 OFFSET ?", user, page * 12)
        buttons = [[self.b(user, "new_ticket", "ticket_new")]]
        buttons.extend([[self.b(user, "ticket_entry", f"ticket:{r['id']}", label=f"№{r['id']}")] for r in rows[:12]])
        self.pages(user, buttons, "support", page, len(rows) > 12)
        self.say(user, "support", buttons)

    def ticket_view(self, user, ticket, admin=False):
        row = self.s.one("SELECT * FROM tickets WHERE id=?", ticket)
        if not row or (not admin and row["user"] != user):
            raise ShopError("unavailable")
        history = self.s.all("SELECT * FROM ticket_messages WHERE ticket=? ORDER BY id DESC LIMIT 6", ticket)
        lines = [f"{r['author']} · {(r['body'] or self.t(user, 'media'))[:280]}" for r in reversed(history)]
        buttons = []
        if not row["closed"]:
            buttons.append([self.b(user, "reply", f"{'a:treply' if admin else 'ticket_reply'}:{ticket}")])
            if admin:
                buttons.append([self.b(user, "a_close", f"a:tclose:{ticket}", label="Закрыть тикет", style="danger")])
        self.say(user, "ticket", buttons, "a:tickets:0" if admin else "support",
                 id=ticket, status=unescape(self.t(user, "ticket_closed" if row["closed"] else "ticket_open")),
                 history="\n".join(lines))

    def ticket_message(self, user, message, ticket=None, admin=False):
        if not self.supported(message):
            self.say(user, "message_prompt", back="a:tickets:0" if admin else "support")
            return
        with self.s.db:
            exists = self.s.one("SELECT ticket FROM ticket_messages WHERE author=? AND source=?",
                                user, message["message_id"])
            if exists:
                return
            if ticket is None:
                ticket = self.s.run("INSERT INTO tickets(user,created) VALUES(?,?)", user, int(time.time())).lastrowid
            row = self.s.one("SELECT * FROM tickets WHERE id=?", ticket)
            if not row or row["closed"] or (not admin and row["user"] != user):
                raise ShopError("already_handled")
            body = message.get("text") or message.get("caption")
            self.s.run("INSERT INTO ticket_messages(ticket,author,source,body) VALUES(?,?,?,?)",
                       ticket, user, message["message_id"], body)
            self.s.state(user)
            job = f"ticket:{user}:{message['message_id']}"
            self.s.enqueue(job, "ticket", ticket=ticket, source=user, message=message["message_id"],
                           receiver=row["user"] if admin else self.admin, admin=admin)
        self.say(user, "ticket_sent", back="a:tickets:0" if admin else "support", id=ticket)

    def route(self, user, action):
        key, *args = action.split(":")
        if key == "a":
            if user == self.admin:
                self.admin_route(args)
            return
        if key == "receipt":
            order = int(args[0])
            with self.s.db:
                self.s.receipt_order(user, order)
                self.s.state(user, "receipt", order)
            self.say(user, "sbp_prompt", back=f"order:{order}", order=order)
            return
        if key in {"support", "ticket", "ticket_new", "ticket_reply"}:
            if key == "support":
                self.ticket_list(user, int(args[0]) if args else 0)
            elif key == "ticket":
                self.ticket_view(user, int(args[0]))
            else:
                ticket = int(args[0]) if args else None
                if ticket:
                    row = self.s.one("SELECT * FROM tickets WHERE id=? AND user=? AND closed=0", ticket, user)
                    if not row:
                        raise ShopError("unavailable")
                with self.s.db:
                    self.s.state(user, "ticket", ticket)
                self.say(user, "ticket_prompt", back="support")
            return
        if not self.gate(user):
            return
        if key == "home":
            self.home(user)
        elif key == "catalog":
            self.catalog(user, page=int(args[0]) if args else 0)
        elif key == "cat":
            self.catalog(user, int(args[0]), int(args[1]))
        elif key in {"item", "qty"}:
            (self.show_item if key == "item" else self.quantity)(user, int(args[0]))
        elif key == "quote":
            self.quote(user, *map(int, args))
        elif key in {"buy", "buy_sbp"}:
            product, qty, discount = map(int, args)
            with self.s.db:
                row = self.s.create_order(user, product, qty, bool(discount), "sbp" if key == "buy_sbp" else "stars")
            (self.sbp_details if key == "buy_sbp" else self.invoice)(user, row)
        elif key in {"order", "invoice"}:
            order = int(args[0])
            if key == "order":
                self.order_view(user, order)
            else:
                row = self.s.order(order)
                if not row or row["user"] != user or row["status"] not in {"open", "reserved"}:
                    raise ShopError("invalid_invoice")
                (self.sbp_details if row["method"] == "sbp" else self.invoice)(user, row)
        elif key == "links":
            rows = [[self.b(user, "support", "support")],
                    [self.b(user, "reviews", url=REVIEWS), self.b(user, "rules", "rules")],
                    [self.b(user, "channel", url=CHANNEL)]]
            self.say(user, "links", rows)
        elif key == "rules":
            self.say(user, "rules", back="links")
        elif key == "profile":
            self.profile(user)
        elif key in {"purchases", "pending"}:
            self.orders(user, key == "pending", int(args[0]) if args else 0)
        elif key == "topup":
            self.say(user, "topup", [[self.b(user, "premium_bot", url="https://t.me/PremiumBot")]], "profile")
        elif key == "stats":
            stats = self.s.one(
                """SELECT COUNT(*) AS orders, COALESCE(SUM(qty),0) AS units,
                   COALESCE(SUM(CASE WHEN method='stars' THEN total END),0) AS stars,
                   COALESCE(SUM(CASE WHEN method='sbp' THEN total END),0) AS kopecks
                   FROM orders WHERE user=? AND status='delivered'""", user,
            )
            self.say(user, "stats", back="profile", rubles=rub(stats["kopecks"]), **dict(stats))
        elif key == "referral":
            invited = self.s.one("SELECT COUNT(*) AS n FROM users WHERE referrer=?", user)["n"]
            buyers = self.s.one(
                """SELECT COUNT(DISTINCT o.user) AS n FROM orders o JOIN users u ON u.id=o.user
                   WHERE u.referrer=? AND o.status='delivered'""", user,
            )["n"]
            self.say(user, "referral", back="profile", invited=invited, buyers=buyers, reward=rub(REFERRAL_CREDIT),
                     link=f"https://t.me/{self.username}?start=ref_{user}")
        elif key == "transactions":
            rows = self.s.all("SELECT * FROM ledger WHERE user=? ORDER BY id DESC LIMIT 12", user)
            labels = [f"{rub(r['amount'])} · {r['reason']}" for r in rows]
            self.say(user, "transactions", back="profile", items="\n".join(labels) or self.t(user, "empty"))
        elif key == "promo":
            with self.s.db:
                self.s.state(user, "promo")
            self.say(user, "promo_prompt", back="profile")
        elif key == "language":
            if args and args[0] in {"ru", "en"}:
                with self.s.db:
                    self.s.put(f"lang:{user}", args[0])
                self.profile(user)
            else:
                self.say(user, "language", [[self.b(user, "ru", "language:ru", label="Русский"),
                                             self.b(user, "en", "language:en", label="English")]], "profile")

    @staticmethod
    def supported(message):
        return any(key in message for key in ("text", "photo", "document"))

    def message(self, msg):
        if msg["chat"]["type"] != "private" or not msg.get("from"):
            return
        actor = msg["from"]
        user = actor["id"]
        raw = (msg.get("text") or "").strip()
        command, _, arg = raw.partition(" ")
        command = command.split("@", 1)[0]
        match = re.fullmatch(r"ref_(\d{1,18})", arg) if command == "/start" else None
        with self.s.db:
            self.s.touch(actor, int(match[1]) if match else None)
            if "successful_payment" in msg:
                self.s.paid(user, msg["successful_payment"])
                return
        if command in {"/start", "/admin", "/paysupport", "/support"}:
            with self.s.db:
                self.s.state(user)
            if command == "/admin":
                if user == self.admin:
                    self.admin_route([])
            elif command in {"/paysupport", "/support"}:
                self.ticket_list(user)
            elif self.gate(user):
                self.home(user)
            return
        state = self.s.one("SELECT state FROM users WHERE id=?", user)["state"]
        if not state:
            return
        key, *args = json.loads(state)
        if key == "ticket":
            self.ticket_message(user, msg, args[0])
        elif key == "receipt":
            self.receipt_message(user, args[0], msg)
        elif key.startswith("a:") and user == self.admin:
            self.admin_input(key[2:], args, msg)
        elif self.gate(user):
            if key == "quantity":
                if not re.fullmatch(r"[0-9]{1,5}", raw):
                    raise ShopError("invalid")
                self.quote(user, args[0], int(raw))
                with self.s.db:
                    self.s.state(user)
            elif key == "promo":
                with self.s.db:
                    amount = self.s.redeem(user, raw.upper())
                    self.s.state(user)
                self.say(user, "promo_done", back="profile", amount=rub(amount))

    def callback(self, callback):
        message = callback.get("message", {})
        if message.get("chat", {}).get("type") != "private":
            self.api.call("answerCallbackQuery", callback_query_id=callback["id"])
            return
        user = callback["from"]["id"]
        try:
            self.api.call("answerCallbackQuery", callback_query_id=callback["id"])
        except TelegramError:
            pass
        action = callback.get("data", "")
        with self.s.db:
            self.s.touch(callback["from"])
            self.s.state(user)
        self.route(user, action)

    def checkout(self, query):
        user = query["from"]["id"]
        try:
            with self.s.db:
                self.s.touch(query["from"])
                self.s.expired()
                self.s.reserve(user, query)
        except ShopError as error:
            self.api.call("answerPreCheckoutQuery", pre_checkout_query_id=query["id"], ok=False,
                          error_message=unescape(self.t(user, str(error)))[:200])
            return
        self.api.call("answerPreCheckoutQuery", pre_checkout_query_id=query["id"], ok=True)

    def join(self, request):
        link = request.get("invite_link")
        if not link:
            return
        row = self.s.one("SELECT * FROM orders WHERE invite=?", link["invite_link"])
        if not row or str(request["chat"]["id"]) != row["target"]:
            return
        chat, user = request["chat"]["id"], request["from"]["id"]
        if row["user"] != user or row["status"] != "delivered" or row["invite_until"] <= int(time.time()):
            self.api.call("declineChatJoinRequest", chat_id=chat, user_id=user)
            return
        try:
            self.api.call("approveChatJoinRequest", chat_id=chat, user_id=user)
        except TelegramError as error:
            if "USER_ALREADY_PARTICIPANT" not in error.description:
                raise
        with self.s.db:
            self.s.run("UPDATE orders SET joined=1 WHERE id=?", row["id"])
            self.s.enqueue(f"revoke:{row['id']}", "revoke", order=row["id"])

    def update(self, update):
        try:
            if "pre_checkout_query" in update:
                self.checkout(update["pre_checkout_query"])
            elif "chat_join_request" in update:
                self.join(update["chat_join_request"])
            elif "callback_query" in update:
                self.callback(update["callback_query"])
            elif "message" in update:
                self.message(update["message"])
        except ShopError as error:
            actor = update.get("callback_query") or update.get("message")
            self.say(actor["from"]["id"], str(error))
        except TelegramError as error:
            if not any(k in update for k in ("pre_checkout_query", "chat_join_request")):
                LOG.warning("Telegram action error %s on update %s", error.code, update["update_id"])
                actor = update.get("callback_query") or update.get("message")
                if actor and actor.get("from"):
                    try:
                        self.say(actor["from"]["id"], "invalid")
                    except TelegramError:
                        pass
            elif error.code >= 500 or error.code == 429:
                raise
            else:
                LOG.warning("Telegram declined update %s (%s)", update["update_id"], error.code)
