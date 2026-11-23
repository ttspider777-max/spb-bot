import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from urllib.parse import urlsplit

from copybook import rub
from design import Design
from product_wizard import ProductWizard
from store import ShopError
from titles import read_title, title_html

MENU = [
    [("categories", "Категории"), ("products", "Товары")],
    [("users", "Пользователи"), ("orders", "Заказы")],
    [("tickets", "Тикеты"), ("promos", "Промокоды")],
    [("subs", "Обязательная подписка")],
    [("design", "Оформление бота")],
    [("dm", "Написать от имени бота")],
]
PROMPTS = {
    "category": "Отправьте название категории, до 70 символов. Можно добавить премиум-эмодзи. Новая категория сразу видна в каталоге.",
    "product": "Добавьте товар по шагам через раздел «Товары» → «Создать товар».",
    "restock": "Отправьте новый доступный остаток. Зарезервированный товар уже вычтен из него.",
    "rubprice": "Отправьте цену за единицу в рублях, например 1,32. Отправьте - для расчёта по 1,32 ₽ за каждую ⭐ цены.",
    "photo": "Отправьте фото обычным сообщением Telegram.",
    "welcome_photo": "Отправьте фото для приветствия.",
    "userfind": "Введите Telegram ID пользователя.",
    "balance": "Отправьте сумму в рублях со знаком, например +100 или -14,50. Изменяется основной бонусный баланс.",
    "promo": "Отправьте три поля через пробел: КОД СУММА ЧИСЛО_АКТИВАЦИЙ. Пример: START 25 100.",
    "promooff": "Отправьте код, который нужно отключить.",
    "sub": "Отправьте ID или @username канала и ссылку через пробел. Бот должен быть администратором канала.",
    "approve": "Отправьте текст выдачи для покупателя. Он увидит его в заказе и получит уведомление.",
    "reject": "Укажите причину отклонения. Бот вернёт Stars покупателю и восстановит доступный остаток.",
    "reject_sbp": "Укажите причину отклонения чека. Если деньги поступили и их нужно вернуть, оформите возврат в банке. Бот сообщит покупателю об отклонении.",
    "dm": "Отправьте Telegram ID получателя.",
    "dmuser": "Отправьте текст, фото или файл. Бот отправит сообщение от своего имени.",
}


def money(raw):
    if not re.fullmatch(r"[+-]?[0-9]{1,7}(?:[.,][0-9]{1,2})?", raw):
        raise ShopError("invalid")
    try:
        return int(Decimal(raw.replace(",", ".")) * 100)
    except InvalidOperation:
        raise ShopError("invalid") from None


def number(raw, least, most):
    if not re.fullmatch(r"[0-9]{1,18}", raw):
        raise ShopError("invalid")
    value = int(raw)
    if not least <= value <= most:
        raise ShopError("invalid")
    return value


class Admin(ProductWizard, Design):
    @staticmethod
    def design_admin_buttons():
        return {f"a_{key}": label for row in MENU for key, label in row}

    @staticmethod
    def design_admin_texts():
        screens = {
            "main": "Главный экран админки", "design": "Экран оформления", "subscriptions": "Экран подписки",
            "categories": "Список категорий", "products": "Список товаров", "users": "Список пользователей",
            "orders": "Список заказов", "tickets": "Список тикетов", "send_failure": "Ошибка отправки сообщения",
        }
        return {**screens, **{f"prompt_{key}": text.splitlines()[0][:62] for key, text in PROMPTS.items()}}

    def ad_button(self, key, label, action, **options):
        return self.b(self.admin, "a_" + key, action, label=label, **options)

    def ad_text(self, text, rows=(), back="a", key=None):
        if key:
            text = self.s.get(f"admin_text:{key}", text)
        navigation = []
        if back and back != "a":
            navigation.append(self.b(self.admin, "back", back))
        if back:
            navigation.append(self.ad_button("panel", "Админ-панель", "a"))
        if navigation:
            rows = [*rows, navigation]
        self.send(self.admin, text, rows, home=False)

    def ad_prompt(self, action, args=(), back="a"):
        with self.s.db:
            self.s.state(self.admin, f"a:{action}", *args)
        self.ad_text(escape(PROMPTS[action]), back=back, key=f"prompt_{action}")

    def admin_route(self, args):
        user = self.admin
        action = args[0] if args else "main"
        rest = args[1:]
        if action == "main":
            rows = [[self.ad_button(name, label, f"a:{name}") for name, label in row] for row in MENU]
            self.ad_text("Админ-панель", rows, None, "main")
        elif action in {"categories", "products", "users", "orders", "tickets"}:
            self.ad_list(action, int(rest[0]) if rest else 0)
        elif action in {"cat", "product", "user", "order", "ticket"}:
            key = int(rest[0])
            if action == "ticket":
                self.ticket_view(user, key, admin=True)
            else:
                self.ad_card(action, key)
        elif action in {"newprod", "editprod"}:
            self.product_start(int(rest[0]) if action == "editprod" else None)
        elif action == "w":
            self.product_action(rest)
        elif action in {"newcat", "editcat", "restock", "photo", "rubprice"}:
            target = int(rest[0]) if rest else None
            form = {"newcat": "category", "editcat": "category", "newprod": "product", "editprod": "product"}.get(action, action)
            is_category = form == "category"
            back = f"a:{'cat' if is_category else 'product'}:{target}" if target else f"a:{'categories' if is_category else 'products'}"
            self.ad_prompt(form, (target,), back)
        elif action == "publishcat":
            key = int(rest[0])
            with self.s.db:
                self.s.run("UPDATE categories SET active=1 WHERE id=?", key)
            self.ad_list("categories", 0)
        elif action in {"togglecat", "toggleprod", "clearphoto"}:
            key = int(rest[0])
            table = "categories" if action == "togglecat" else "products"
            assignment = "photo=NULL" if action == "clearphoto" else "active=1-active"
            with self.s.db:
                self.s.run(f"UPDATE {table} SET {assignment} WHERE id=?", key)
            self.ad_card("cat" if action == "togglecat" else "product", key)
        elif action == "userfind":
            self.ad_prompt("userfind", back="a:users")
        elif action in {"balance", "dmuser", "ban"}:
            target = int(rest[0])
            if not self.s.one("SELECT 1 FROM users WHERE id=?", target):
                raise ShopError("unavailable")
            if action == "ban":
                if target == user:
                    raise ShopError("invalid")
                with self.s.db:
                    self.s.run("UPDATE users SET blocked=1-blocked WHERE id=?", target)
                self.ad_card("user", target)
            else:
                self.ad_prompt(action, (target,), f"a:user:{target}")
        elif action == "dm":
            self.ad_prompt("dm")
        elif action in {"approve", "reject", "refund_auto"}:
            order = int(rest[0])
            row = self.s.order(order)
            if action == "refund_auto":
                if not row or row["status"] != "fulfilling" or row["mode"] != "invite":
                    raise ShopError("already_handled")
                job = self.s.one("SELECT failures FROM jobs WHERE key=?", f"deliver:{order}")
                if not job or not job["failures"]:
                    raise ShopError("already_handled")
            elif not row or row["status"] != "review":
                raise ShopError("already_handled")
            if action == "approve" and row["method"] == "sbp" and row["mode"] != "manual":
                with self.s.db:
                    self.s.approve(order, None)
                self.ad_card("order", order)
                return
            form = "approve" if action == "approve" else "reject_sbp" if row["method"] == "sbp" else "reject"
            self.ad_prompt(form, (order, action == "refund_auto"), f"a:order:{order}")
        elif action == "receipt":
            row = self.s.order(int(rest[0]))
            if not row or not row["receipt_file"]:
                raise ShopError("unavailable")
            self.ad_receipt(row)
        elif action == "retry":
            order = int(rest[0])
            with self.s.db:
                self.s.run("UPDATE jobs SET due=0 WHERE key IN (?,?,?)", f"deliver:{order}", f"refund:{order}", f"review:{order}")
            self.ad_card("order", order)
        elif action in {"treply", "tclose"}:
            ticket = int(rest[0])
            row = self.s.one("SELECT * FROM tickets WHERE id=?", ticket)
            if not row or row["closed"]:
                raise ShopError("already_handled")
            with self.s.db:
                if action == "treply":
                    self.s.state(user, "a:ticketreply", ticket)
                else:
                    self.s.run("UPDATE tickets SET closed=1 WHERE id=?", ticket)
                    self.s.enqueue(f"close:{ticket}", "ticket_close", user=row["user"], ticket=ticket)
            if action == "treply":
                self.say(user, "message_prompt", back=f"a:ticket:{ticket}")
            else:
                self.ticket_view(user, ticket, admin=True)
        elif action == "promos":
            rows = self.s.all("SELECT * FROM promos ORDER BY code LIMIT 40")
            content = "\n".join(f"{r['code']} · {rub(r['amount'])} · {r['remaining']} активаций" for r in rows)
            self.ad_text("Промокоды\n" + escape(content), [
                [self.ad_button("new", "Создать", "a:promo")],
                [self.ad_button("remove", "Отключить", "a:promooff")],
            ])
        elif action in {"promo", "promooff"}:
            self.ad_prompt(action, back="a:promos")
        elif action == "subs":
            rows = self.s.all("SELECT * FROM subscriptions ORDER BY chat")
            buttons = [[self.ad_button("new", "Добавить", "a:sub")]]
            buttons.extend([[self.ad_button("remove", f"Удалить {r['chat']}", f"a:subdel:{r['chat']}")] for r in rows])
            self.ad_text("Обязательная подписка", buttons, key="subscriptions")
        elif action == "sub":
            self.ad_prompt("sub", back="a:subs")
        elif action == "subdel":
            with self.s.db:
                self.s.run("DELETE FROM subscriptions WHERE chat=?", rest[0])
            self.admin_route(["subs"])
        elif action == "design":
            lang = rest[0] if rest and rest[0] in {"ru", "en"} else self.s.get("design_lang", "ru")
            with self.s.db:
                self.s.put("design_lang", lang)
            button = self.design_button
            base = f"a:d:button:{lang}"
            rows = [
                [button("Приветствие", f"a:d:text:{lang}:shop:home"),
                 button("Фото приветствия", "a:welcome_photo")],
                [button("Каталог", f"{base}:shop:catalog"), button("Профиль", f"{base}:shop:profile")],
                [button("Полезные ссылки", f"{base}:shop:links"), button("Поддержка", f"{base}:shop:support")],
                [button("Все кнопки", f"a:d:button:{lang}"), button("Все тексты", f"a:d:text:{lang}")],
                [button("Язык: Русский ✓" if lang == "ru" else "Русский", "a:design:ru"),
                 button("English ✓" if lang == "en" else "English", "a:design:en")],
            ]
            if self.s.get("welcome_photo"):
                rows.insert(1, [button("Убрать фото приветствия", "a:welcome_clear")])
            self.ad_text("<b>Оформление бота</b>\nВыберите, что изменить.\n"
                         "В редакторе кнопки просто отправьте надпись или эмодзи. Цвета доступны сразу.", rows, key="design")
        elif action in {"text", "button"}:
            self.design_screen([action, self.s.get("design_lang", "ru")])
        elif action == "d":
            self.design_screen(rest)
        elif action == "welcome_photo":
            self.ad_prompt(action, back="a:design")
        elif action == "welcome_clear":
            with self.s.db:
                self.s.put("welcome_photo", None)
            self.admin_route(["design"])

    def ad_list(self, action, page):
        table, callback, title, extra = {
            "categories": ("categories", "cat", "Категории", ("Создать категорию", "newcat")),
            "products": ("products", "product", "Товары", ("Создать товар", "newprod")),
            "users": ("users", "user", "Пользователи", ("Найти по ID", "userfind")),
            "orders": ("orders", "order", "Заказы", None),
            "tickets": ("tickets", "ticket", "Тикеты", None),
        }[action]
        ordering = {
            "orders": "CASE WHEN status IN ('review','fulfilling','refunding') THEN 0 ELSE 1 END, id DESC",
            "tickets": "closed, id DESC",
        }.get(action, "id DESC")
        rows = self.s.all(f"SELECT * FROM {table} ORDER BY {ordering} LIMIT 13 OFFSET ?", page * 12)
        buttons = [[self.ad_button("new", extra[0], f"a:{extra[1]}")]] if extra else []
        for row in rows[:12]:
            key = row["id"]
            if table == "users":
                subtitle = row["username"] or row["name"]
                label = f"{key} · {subtitle}"[:64]
            elif table == "tickets":
                label = f"№{key} · {'Закрыт' if row['closed'] else 'Открыт'}"
            elif table == "orders":
                label = f"№{key} · {unescape(self.t(self.admin, 'status_' + row['status']))}"[:64]
            else:
                label = f"№{key} · {row['title']}"[:64]
            if table in {"categories", "products"}:
                entry = self.copy.named_button(self.admin, "a_card", f"a:{callback}:{key}", row,
                                               prefix=f"№{key} · ")
                line = [entry]
                if table == "categories" and not row["active"]:
                    line.append(self.design_button("Показать", f"a:publishcat:{key}", "success"))
                buttons.append(line)
            else:
                buttons.append([self.ad_button("card", label, f"a:{callback}:{key}")])
        self.pages(self.admin, buttons, f"a:{action}", page, len(rows) > 12)
        self.ad_text(title, buttons, key=action)

    def ad_card(self, kind, key):
        table = {"cat": "categories", "product": "products", "user": "users", "order": "orders"}[kind]
        row = self.s.one(f"SELECT * FROM {table} WHERE id=?", key)
        if not row:
            raise ShopError("unavailable")
        btn = self.ad_button
        if kind == "cat":
            text = f"Категория №{key} · {title_html(row)}\n{'Опубликована' if row['active'] else 'Скрыта'}"
            buttons = [[btn("edit", "Переименовать", f"a:editcat:{key}")],
                       [btn("toggle", "Скрыть" if row["active"] else "Опубликовать", f"a:togglecat:{key}")]]
        elif kind == "product":
            text = (f"Товар №{key} · {title_html(row)}\nКатегория №{row['category']}\n"
                    f"{escape(row['description'])}\nЦена · {row['price']} ⭐ или {rub(self.s.unit_price(row, 'sbp'))} по СБП\nОстаток · {row['stock']}\n"
                    f"Выдача · {row['mode']}\n{'Опубликован' if row['active'] else 'Скрыт'}")
            buttons = [
                [btn("edit", "Изменить", f"a:editprod:{key}"), btn("restock", "Остаток", f"a:restock:{key}")],
                [btn("photo", "Изменить фото", f"a:photo:{key}")],
                [btn("rubprice", "Цена по СБП", f"a:rubprice:{key}")],
                [btn("toggle", "Скрыть" if row["active"] else "Опубликовать", f"a:toggleprod:{key}")],
            ]
            if row["photo"]:
                buttons.append([btn("remove_photo", "Удалить фото", f"a:clearphoto:{key}")])
        elif kind == "user":
            balance = self.s.balances(key)
            handle = "@" + row["username"] if row["username"] else "—"
            joined = datetime.fromtimestamp(row["joined"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            seen = datetime.fromtimestamp(row["seen"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            text = (f"ID · <code>{key}</code>\nИмя · {escape(row['name'])}\nUsername · {escape(handle)}\n"
                    f"Баланс · {rub(balance['main'])}\nРеферальный · {rub(balance['referral'])}\n"
                    f"Пригласил · {row['referrer'] or '—'}\nПервый визит · {joined}\nПоследний визит · {seen}")
            buttons = [
                [btn("balance", "Пополнить или списать", f"a:balance:{key}")],
                [btn("dmuser", "Написать пользователю", f"a:dmuser:{key}")],
                [btn("ban", "Разбанить" if row["blocked"] else "Забанить", f"a:ban:{key}", style="danger")],
            ]
        else:
            sbp = row["method"] == "sbp"
            status = self.t(self.admin, "sbp_status_review" if sbp and row["status"] == "review" else f"status_{row['status']}")
            amount = f"{rub(row['total'])} по СБП" if sbp else f"{row['total']} ⭐"
            text = (f"Заказ №{key}\n{title_html(row)} × {row['qty']}\n"
                    f"Покупатель · <code>{row['user']}</code>\nК оплате · {amount}\nСтатус · {status}")
            buttons = []
            if row["status"] == "review":
                buttons.extend([[btn("approve", "Одобрить и выдать", f"a:approve:{key}", style="success"),
                                 btn("reject", "Отклонить" if sbp else "Отклонить и вернуть", f"a:reject:{key}", style="danger")]])
                if sbp:
                    text += "\nСверьте поступление и сумму в приложении банка перед одобрением."
                    if not row["reserved"]:
                        text += "\nОстаток или бонусы пока не удалось зарезервировать."
            if row["receipt_file"]:
                buttons.append([btn("receipt", "Посмотреть чек", f"a:receipt:{key}")])
            if row["status"] in {"fulfilling", "refunding", "review"}:
                buttons.append([btn("retry", "Повторить обработку", f"a:retry:{key}")])
            if row["status"] == "fulfilling" and row["mode"] == "invite":
                job = self.s.one("SELECT failures FROM jobs WHERE key=?", f"deliver:{key}")
                if job and job["failures"]:
                    buttons.append([btn("refund_auto", "Отклонить заявку" if sbp else "Вернуть оплату", f"a:refund_auto:{key}", style="danger")])
            buttons.append([btn("card", "Профиль покупателя", f"a:user:{row['user']}")])
        self.ad_text(text, buttons, f"a:{table}")

    def ad_receipt(self, row):
        kind = row["receipt_kind"]
        method = "sendPhoto" if kind == "photo" else "sendDocument"
        self.api.call(method, chat_id=self.admin, **{kind: row["receipt_file"]})

    def admin_input(self, action, args, msg):
        user = self.admin
        body = (msg.get("text") or msg.get("caption") or "").strip()
        if action == "product_step":
            self.product_input(args, msg)
            return
        if action in {"design_text", "design_label", "design_emoji", "design_auto"}:
            self.design_input(action, args, msg)
            return
        if action in {"text", "button"}:
            with self.s.db:
                self.s.state(user)
            self.design_screen([action, self.s.get("design_lang", "ru")])
            return
        if action == "ticketreply":
            self.ticket_message(user, msg, args[0], admin=True)
            return
        if action in {"userfind", "dm"}:
            target = number(body, 1, 10**18 - 1)
            if not self.s.one("SELECT 1 FROM users WHERE id=?", target):
                raise ShopError("unavailable")
            if action == "dm":
                self.ad_prompt("dmuser", (target,))
            else:
                with self.s.db:
                    self.s.state(user)
                self.ad_card("user", target)
            return
        if action in {"photo", "welcome_photo"} and not msg.get("photo"):
            raise ShopError("invalid")
        with self.s.db:
            if action == "category":
                title, entities = read_title(msg)
                if args[0]:
                    self.s.run("UPDATE categories SET title=?,title_entities=? WHERE id=?", title, entities, args[0])
                else:
                    cursor = self.s.run("INSERT INTO categories(title,title_entities,active) VALUES(?,?,1)", title, entities)
                    args = (cursor.lastrowid,)
                self.s.state(user)
                self.ad_card("cat", args[0])
                return
            elif action == "product":
                self.save_product(args[0], body)
            elif action == "restock":
                value = number(body, 0, 10**9)
                self.s.run("UPDATE products SET stock=? WHERE id=?", value, args[0])
            elif action == "rubprice":
                value = None if body == "-" else money(body)
                if value is not None and not 100 <= value <= 100000000:
                    raise ShopError("invalid")
                self.s.run("UPDATE products SET rub_price=? WHERE id=?", value, args[0])
            elif action in {"photo", "welcome_photo"}:
                photo = msg["photo"][-1]["file_id"]
                if action == "photo":
                    self.s.run("UPDATE products SET photo=? WHERE id=?", photo, args[0])
                else:
                    self.s.put("welcome_photo", photo)
            elif action == "balance":
                target = args[0]
                value = money(body)
                if not value or self.s.balances(target)["main"] + value < 0:
                    raise ShopError("invalid")
                reference = f"adjust:{msg['message_id']}"
                if not self.s.one("SELECT 1 FROM ledger WHERE reference=?", reference):
                    self.s.credit(target, "main", value, "Изменение администратором", reference)
                    self.s.enqueue(reference, "balance", user=target, amount=value)
            elif action == "promo":
                parts = body.upper().split()
                if len(parts) != 3 or not re.fullmatch(r"[A-Z0-9_-]{2,32}", parts[0]):
                    raise ShopError("invalid")
                code, amount, count = parts
                value = money(amount)
                if value <= 0 or self.s.one("SELECT 1 FROM promos WHERE code=?", code):
                    raise ShopError("invalid")
                self.s.run("INSERT INTO promos VALUES(?,?,?)", code, value, number(count, 1, 10**7))
            elif action == "promooff":
                self.s.run("UPDATE promos SET remaining=0 WHERE code=?", body.upper())
            elif action == "sub":
                self.save_subscription(body)
            elif action in {"approve", "reject", "reject_sbp"}:
                if not 1 <= len(body) <= (2500 if action == "approve" else 250):
                    raise ShopError("invalid")
                order = args[0]
                if action == "approve":
                    self.s.approve(order, body)
                elif args[1]:
                    row = self.s.order(order)
                    if row["status"] != "fulfilling" or row["mode"] != "invite" or row["invite"]:
                        raise ShopError("already_handled")
                    self.s.run("DELETE FROM jobs WHERE key=?", f"deliver:{order}")
                    if row["method"] == "sbp":
                        self.s.run("UPDATE orders SET status='review' WHERE id=?", order)
                        self.s.reject(order, body)
                    else:
                        self.s.run("UPDATE orders SET status='refunding', reject_reason=? WHERE id=?", body, order)
                        self.s.enqueue(f"refund:{order}", "refund", order=order)
                else:
                    self.s.reject(order, body)
            elif action == "dmuser":
                if not self.supported(msg):
                    raise ShopError("invalid")
                target = args[0]
                self.s.enqueue(f"dm:{msg['message_id']}", "copy", user=target, source=user, message=msg["message_id"])
            self.s.state(user)
        self.say(user, "saved", [[self.ad_button("panel", "‹ Админ-панель", "a")]])

    def save_product(self, product, body):
        lines = body.split("\n", 6)
        if len(lines) != 7:
            raise ShopError("invalid")
        cat, title, price, stock, mode, description, target = (s.strip() for s in lines)
        category = number(cat, 1, 10**12)
        if not self.s.one("SELECT 1 FROM categories WHERE id=?", category):
            raise ShopError("unavailable")
        if not 1 <= len(title) <= 70 or not 1 <= len(description) <= 255 or mode not in {"manual", "text", "invite"}:
            raise ShopError("invalid")
        if mode == "invite":
            if not re.fullmatch(r"-[0-9]{4,17}", target):
                raise ShopError("invalid")
            me = self.api.call("getMe")
            member = self.api.call("getChatMember", chat_id=int(target), user_id=me["id"])
            if member["status"] != "administrator" or not member.get("can_invite_users"):
                raise ShopError("invalid")
        elif mode == "text" and not 1 <= len(target) <= 2500:
            raise ShopError("invalid")
        if mode == "manual":
            target = ""
        values = (category, title, description, number(price, 1, 10**6), number(stock, 0, 10**9), mode, target)
        if product:
            self.s.run(
                """UPDATE products SET category=?,title=?,description=?,price=?,stock=?,mode=?,target=?,
                   revision=revision+1,title_entities='[]' WHERE id=?""", *values, product,
            )
        else:
            self.s.run(
                "INSERT INTO products(category,title,description,price,stock,mode,target) VALUES(?,?,?,?,?,?,?)", *values,
            )

    def save_subscription(self, body):
        parts = body.split()
        if len(parts) != 2:
            raise ShopError("invalid")
        chat, link = parts
        uri = urlsplit(link)
        if uri.scheme != "https" or uri.netloc.lower() != "t.me" or not uri.path.strip("/"):
            raise ShopError("invalid")
        if not re.fullmatch(r"(?:-[0-9]{4,17}|@[A-Za-z0-9_]{5,32})", chat):
            raise ShopError("invalid")
        identity = int(chat) if chat.startswith("-") else chat
        info = self.api.call("getChat", chat_id=identity)
        me = self.api.call("getMe")
        member = self.api.call("getChatMember", chat_id=info["id"], user_id=me["id"])
        if member["status"] != "administrator":
            raise ShopError("invalid")
        self.s.run("INSERT OR REPLACE INTO subscriptions VALUES(?,?)", str(info["id"]), link)
