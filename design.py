import re
from html import escape
from string import Formatter
from unicodedata import category

from copybook import BUTTON
from store import ShopError


TEXT_GROUPS = {
    "shop": ("Магазин и каталог", {
        "home": "Текст приветствия", "links": "Экран полезных ссылок", "rules": "Правила магазина",
        "catalog": "Выбор категории", "empty": "Пустой раздел", "category": "Выбор товара",
        "product": "Карточка товара", "quantity": "Ввод количества", "quote": "Выбор способа оплаты",
    }),
    "pay": ("Оплата и выдача", {
        "invoice": "Инструкция к счёту Stars", "invoice_line": "Подпись счёта Stars",
        "sbp_details": "Реквизиты и инструкция по СБП", "sbp_prompt": "Запрос чека",
        "sbp_received": "Чек принят", "receipt_duplicate": "Чек уже использован",
        "sbp_declined": "Чек отклонён", "paid": "Подтверждение оплаты", "delivered": "Заказ выдан",
        "refund": "Возврат Stars", "unexpected": "Возврат по старому счёту",
        "welcome_invite": "Приглашение в закрытый чат", "invite_used": "Приглашение использовано",
        "invite_expired": "Приглашение истекло",
    }),
    "profile": ("Профиль и бонусы", {
        "profile": "Экран профиля", "stats": "Статистика покупок", "topup": "Пополнение",
        "referral": "Реферальная программа", "referral_paid": "Начисление за приглашённого",
        "promo_prompt": "Запрос промокода", "promo_done": "Промокод активирован",
        "promo_invalid": "Промокод недействителен", "language": "Выбор языка",
        "transactions": "Транзакции", "notify_balance": "Изменение баланса",
    }),
    "orders": ("Заказы и статусы", {
        "orders": "Список покупок", "pending": "Список неоплаченных заказов", "order": "Карточка заказа Stars",
        "sbp_order": "Карточка заказа СБП", "status_open": "Статус нового заказа",
        "status_reserved": "Статус заказа в резерве", "status_expired": "Статус просроченного заказа",
        "status_review": "Статус ручной выдачи", "sbp_status_review": "Статус проверки чека",
        "status_fulfilling": "Статус выдачи", "status_delivered": "Статус выданного заказа",
        "status_refunding": "Статус возврата", "status_refunded": "Статус завершённого возврата",
        "status_declined": "Статус отклонения",
    }),
    "help": ("Поддержка и подписка", {
        "support": "Экран поддержки", "ticket_prompt": "Создание тикета", "ticket_sent": "Тикет отправлен",
        "ticket": "Карточка тикета", "ticket_open": "Статус открытого тикета",
        "ticket_closed": "Статус закрытого тикета", "ticket_reply": "Ответ поддержки",
        "ticket_closed_notice": "Тикет закрыт", "media": "Подпись вложения", "message_prompt": "Запрос сообщения",
        "subscription": "Запрос подписки", "subscription_error": "Ошибка проверки подписки",
        "banned": "Доступ ограничен",
    }),
    "errors": ("Системные сообщения", {
        "unavailable": "Товар или раздел недоступен", "stock": "Недостаточно товара",
        "amount_range": "Слишком большая сумма", "balance_changed": "Баланс изменился",
        "invalid_invoice": "Счёт недействителен", "already_handled": "Действие уже выполнено",
        "invalid": "Некорректное сообщение", "saved": "Настройки сохранены",
    }),
}

BUTTON_GROUPS = {
    "shop": ("Главное меню и ссылки", {
        "catalog": "Каталог", "links": "Полезные ссылки", "profile": "Профиль", "support": "Поддержка",
        "reviews": "Отзывы", "channel": "Канал", "rules": "Правила",
        "home": "В главное меню", "back": "Назад", "prev": "Предыдущая страница", "next": "Следующая страница",
    }),
    "catalog": ("Каталог и оплата", {
        "category_entry": "Категория в списке", "product_entry": "Товар в списке", "buy": "Выбрать количество",
        "quantity_entry": "Вариант количества", "pay": "Оплата Stars", "discount": "Оплата Stars с бонусами",
        "sbp": "Оплата по СБП", "sbp_discount": "Оплата по СБП с бонусами", "sbp_paid": "Я оплатил",
        "order_entry": "Заказ в списке", "see_order": "Посмотреть заказ", "open_link": "Открыть приглашение",
    }),
    "profile": ("Профиль и поддержка", {
        "topup": "Пополнить баланс", "purchases": "Мои покупки", "stats": "Статистика покупок",
        "referral": "Реферальная программа", "promo": "Промокод", "transactions": "Транзакции",
        "language": "Язык", "pending": "Ожидают оплаты", "premium_bot": "Открыть PremiumBot",
        "ru": "Русский язык", "en": "Английский язык", "new_ticket": "Создать тикет", "reply": "Ответить",
        "ticket_entry": "Тикет в списке", "subscribe": "Проверить подписку", "subscription_link": "Подписаться",
    }),
    "admin": ("Действия администратора", {
        "a_panel": "Админ-панель", "a_close": "Закрыть тикет", "a_approve": "Одобрить и выдать",
        "a_reject": "Отклонить заказ", "a_retry": "Повторить обработку", "a_refund_auto": "Отменить автовыдачу",
        "a_new": "Добавить или создать", "a_edit": "Изменить", "a_toggle": "Опубликовать или скрыть",
        "a_photo": "Изменить фото товара", "a_remove_photo": "Удалить фото товара",
        "a_card": "Карточка в списке", "a_balance": "Изменить баланс", "a_ban": "Бан или разбан",
        "a_dmuser": "Написать пользователю", "a_text": "Тексты бота", "a_button": "Кнопки бота",
        "a_welcome_photo": "Фото приветствия", "a_welcome_clear": "Удалить фото приветствия",
        "a_remove": "Удалить или отключить", "a_restock": "Остаток товара", "a_rubprice": "Цена по СБП",
        "a_receipt": "Посмотреть чек",
    }),
}

COLORS = {
    "success": ("🟢 Зелёный", "success", None),
    "danger": ("🔴 Красный", "danger", None),
    "primary": ("🔵 Синий", "primary", None),
    "purple": ("🟣 Фиолетовый значок", None, "🟣"),
    "theme": ("Цвет темы", None, None),
}

# Keep the information required to complete a purchase or use delivered access.
AUTO_DETAILS = {
    "category": "{title}",
    "product": "{title}\n{description}\n{rubles} по СБП или {price} ⭐\nВ наличии: {stock}",
    "profile": "ID: {id}\nБаланс: {main}\nРеферальный баланс: {referral}\nЗаказов: {orders}\nТоваров получено: {units}",
    "quantity": "Количество: от 1 до {max}",
    "quote": "{title} × {qty}",
    "sbp_details": "Заказ №{order}\nСумма: <b>{amount}</b>\nНомер: <code>{phone}</code>\nБанк: <b>{bank}</b>",
    "sbp_order": "№{id} · {title} × {qty}\n{total} · {status}",
    "order": "№{id} · {title} × {qty}\n{total} ⭐ · {status}",
    "delivered": "№{order}\n{delivery}",
    "welcome_invite": "{link}",
    "referral": "{link}",
    "transactions": "{items}",
    "ticket": "№{id} · {status}\n{history}",
    "stats": "Заказов: {orders} · Товаров: {units}\nОплачено: {stars} ⭐ · СБП: {rubles}",
}

EN_DETAILS = {
    "product": "{title}\n{description}\n{rubles} via SBP or {price} ⭐\nAvailable: {stock}",
    "profile": "ID: {id}\nBalance: {main}\nReferral balance: {referral}\nOrders: {orders}\nItems delivered: {units}",
    "quantity": "Quantity: 1 to {max}",
    "sbp_details": "Order #{order}\nAmount: <b>{amount}</b>\nPhone: <code>{phone}</code>\nBank: <b>{bank}</b>",
    "stats": "Orders: {orders} · Items: {units}\nPaid: {stars} ⭐ · SBP: {rubles}",
}

DYNAMIC_BUTTONS = {"category_entry", "product_entry", "quantity_entry", "order_entry", "ticket_entry", "a_card"}
FORMAT_TAGS = {"bold": "b", "italic": "i", "underline": "u", "strikethrough": "s", "spoiler": "tg-spoiler", "code": "code"}


def template_literal(value):
    return value.replace("{", "{{").replace("}", "}}")


def message_html(text, entities):
    data = text.encode("utf-16-le")
    events = []
    for i, entity in enumerate(entities):
        kind = entity["type"]
        if kind == "custom_emoji" and entity.get("custom_emoji_id"):
            tag = f'tg-emoji emoji-id="{escape(entity["custom_emoji_id"], quote=True)}"'
            name = "tg-emoji"
        elif kind in FORMAT_TAGS:
            tag = name = FORMAT_TAGS[kind]
        else:
            continue
        start = entity["offset"] * 2
        end = start + entity["length"] * 2
        if 0 <= start < end <= len(data):
            events.extend(((start, 1, -end, i, f"<{tag}>"), (end, 0, -start, -i, f"</{name}>")))
    result = []
    cursor = 0
    for offset, _, _, _, tag in sorted(events):
        result.extend((escape(data[cursor:offset].decode("utf-16-le")), tag))
        cursor = offset
    result.append(escape(data[cursor:].decode("utf-16-le")))
    return "".join(result).strip()


class Design:
    def design_groups(self, kind):
        if kind == "text":
            return {**TEXT_GROUPS, "admin": ("Тексты админки", self.design_admin_texts())}
        title, entries = BUTTON_GROUPS["admin"]
        return {**BUTTON_GROUPS, "admin": (title, {**entries, **self.design_admin_buttons()})}

    def design_button(self, label, action, style=None):
        button = {"text": label, "callback_data": action}
        if style:
            button["style"] = style
        return button

    @staticmethod
    def design_rows(buttons, columns=2):
        return [buttons[i:i + columns] for i in range(0, len(buttons), columns)]

    def design_screen(self, args, saved=False):
        kind, lang, *rest = args
        if kind not in {"text", "button"} or lang not in {"ru", "en"}:
            raise ShopError("invalid")
        groups = self.design_groups(kind)
        base = f"a:d:{kind}:{lang}"
        button = self.design_button
        if not rest:
            rows = self.design_rows([button(title, f"{base}:{group}") for group, (title, _) in groups.items()])
            other = "en" if lang == "ru" else "ru"
            rows.append([button("English" if other == "en" else "Русский", f"a:d:{kind}:{other}")])
            self.ad_text("<b>Кнопки бота</b>" if kind == "button" else "<b>Тексты бота</b>", rows, "a:design")
            return
        group, *rest = rest
        if group not in groups:
            raise ShopError("invalid")
        title, entries = groups[group]
        section = f"{base}:{group}"
        if not rest or re.fullmatch(r"p[0-9]+", rest[0]):
            page = int(rest[0][1:]) if rest else 0
            items = list(entries.items())
            if page * 8 >= len(items):
                raise ShopError("invalid")
            rows = self.design_rows([button(label, f"{section}:{key}") for key, label in items[page * 8:page * 8 + 8]])
            pages = []
            if page:
                pages.append(button("‹ Предыдущие", f"{section}:p{page - 1}"))
            if (page + 1) * 8 < len(items):
                pages.append(button("Следующие ›", f"{section}:p{page + 1}"))
            if pages:
                rows.append(pages)
            self.ad_text(f"<b>{escape(title)}</b> · {page + 1}/{(len(items) + 7) // 8}", rows, base)
            return
        key, *rest = rest
        if key not in entries:
            raise ShopError("invalid")
        label = entries[key]
        location = f"{section}:{key}"
        action = rest[0] if rest else ""
        setting = self.design_setting(kind, lang, group, key)
        page = list(entries).index(key) // 8
        back = f"{section}:p{page}"
        if action == "reset":
            with self.s.db:
                self.s.run("DELETE FROM settings WHERE key=?", setting)
            self.design_screen(args[:4], saved=True)
            return
        if kind == "text":
            with self.s.db:
                self.s.state(self.admin, "a:design_text", *args[:4])
            prompt = f"<b>{escape(label)}</b>\nОтправьте новый текст одним сообщением."
            if key in AUTO_DETAILS and group != "admin":
                prompt += "\nДанные заказа или раздела бот добавит сам."
            if saved:
                prompt = "Сохранено. Можно отправить новый вариант.\n\n" + prompt
            rows = [[button("Вернуть исходный текст", f"{location}:reset")]]
            if key == "home" and group == "shop":
                rows.insert(0, [button("Фото приветствия", "a:welcome_photo")])
            self.ad_text(prompt, rows, back)
            return
        config = self.s.get(setting, {})
        if action.startswith("color_") and action[6:] in COLORS:
            _, style, accent = COLORS[action[6:]]
            config.update(style=style, accent=accent)
        elif action == "clear":
            config.pop("icon", None)
            config.pop("accent", None)
            config["emoji"] = ""
        elif action in {"label", "emoji"}:
            with self.s.db:
                self.s.state(self.admin, f"a:design_{action}", *args[:4])
            prompt = "Отправьте новую надпись." if action == "label" else "Отправьте один обычный или премиум-эмодзи."
            self.ad_text(prompt, [[button("Без эмодзи", f"{location}:clear")]], location)
            return
        elif action not in {"", "preview", "color"}:
            raise ShopError("invalid")
        if action.startswith("color_") or action == "clear":
            with self.s.db:
                self.s.put(setting, config)
            saved = True
        # Opening the editor is enough to start changing the button.
        with self.s.db:
            self.s.state(self.admin, "a:design_auto", *args[:4])
        samples = {"amount": "132 ₽" if key.startswith("sbp") else 100, "n": 1}
        preview = self.copy.button_for(lang, key, f"{location}:preview",
                                       label=None if key in BUTTON else label, **samples)
        colors = [button(name, f"{location}:color_{color}", style) for color, (name, style, _) in COLORS.items()]
        rows = [[preview], *self.design_rows(colors, 3),
                [button("Без эмодзи", f"{location}:clear"), button("Сбросить", f"{location}:reset")]]
        keys = list(entries)
        index = keys.index(key)
        adjacent = []
        if index:
            adjacent.append(button("‹ Предыдущая кнопка", f"{section}:{keys[index - 1]}"))
        if index + 1 < len(keys):
            adjacent.append(button("Следующая кнопка ›", f"{section}:{keys[index + 1]}"))
        if adjacent:
            rows.append(adjacent)
        title = (f"<b>{escape(label)}</b>\nПервая кнопка — предпросмотр.\n"
                 "Отправьте новую надпись или один эмодзи. Можно отправить премиум-эмодзи вместе с надписью.\n"
                 "Цвет меняется нажатием ниже. Премиум-эмодзи заменяет обычный значок.")
        if key in DYNAMIC_BUTTONS:
            title += "\nНадпись будет префиксом перед названием или номером."
        self.ad_text(("Сохранено.\n\n" if saved else "") + title, rows, back)

    @staticmethod
    def design_setting(kind, lang, group, key):
        if kind == "text" and group == "admin":
            return f"admin_text:{key}"
        return f"{kind}:{lang}:{key}"

    def design_input(self, action, args, msg):
        kind, lang, group, key = args
        if key not in self.design_groups(kind)[group][1]:
            raise ShopError("invalid")
        raw = msg.get("text", "")
        text = raw.strip()
        entities = msg.get("entities", [])
        if not text:
            raise ShopError("invalid")
        setting = self.design_setting(kind, lang, group, key)
        with self.s.db:
            if action == "design_text":
                if len(text) > (1000 if key in {"delivered", "ticket"} else 2500):
                    raise ShopError("invalid")
                html = message_html(raw, entities)
                if group != "admin":
                    html = template_literal(html)
                    if key in AUTO_DETAILS:
                        details = EN_DETAILS.get(key, AUTO_DETAILS[key]) if lang == "en" else AUTO_DETAILS[key]
                        html += "\n\n" + details
                self.s.put(setting, html)
            else:
                config = self.s.get(setting, {})
                icons = [e for e in entities if e["type"] == "custom_emoji"]
                ordinary = (len(text) <= 12 and any(category(c) == "So" or c == "\u20e3" for c in text) and all(
                    category(c) in {"So", "Sk", "Mn", "Cf", "Me"} or c in "0123456789#*" for c in text))
                if action == "design_auto":
                    action = "design_emoji" if icons or ordinary else "design_label"
                label_text = text if action == "design_label" else None
                if action == "design_emoji":
                    if len(icons) == 1:
                        entity = icons[0]
                        data = raw.encode("utf-16-le")
                        start = entity["offset"] * 2
                        end = start + entity["length"] * 2
                        if not 0 <= start < end <= len(data) or not entity.get("custom_emoji_id"):
                            raise ShopError("invalid")
                        try:
                            remainder = (data[:start] + data[end:]).decode("utf-16-le").strip()
                        except UnicodeDecodeError:
                            raise ShopError("invalid") from None
                        if remainder:
                            label_text = remainder
                        config["icon"] = entity["custom_emoji_id"]
                        config.pop("emoji", None)
                        config.pop("accent", None)
                    elif not icons and ordinary:
                        config["emoji"] = text
                        config.pop("icon", None)
                        config.pop("accent", None)
                    else:
                        raise ShopError("invalid")
                if label_text is not None:
                    if len(label_text) > 45 or "\n" in label_text:
                        raise ShopError("invalid")
                    if key in DYNAMIC_BUTTONS:
                        config.pop("label", None)
                        config["prefix"] = label_text
                    else:
                        default = BUTTON.get(key, ("", ""))[lang == "en"]
                        suffix = [name for _, name, _, _ in Formatter().parse(default) if name]
                        config["label"] = template_literal(label_text) + "".join(" · {" + name + "}" for name in suffix)
                self.s.put(setting, config)
            self.s.state(self.admin)
        self.design_screen(args, saved=True)
