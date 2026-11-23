from html import escape
import re
from titles import TitleHTML, button_title

TEXT = {
    "home": ("Здравствуйте, {name}! Выберите раздел магазина.", "Hi, {name}! Choose a section."),
    "links": ("Полезные ссылки", "Useful links"),
    "rules": (
        "1. Выберите товар в каталоге.\n2. Оплатите заказ выбранным способом. Для СБП отправьте чек в боте.\n"
        "3. После подтверждения оплаты автоматическая выдача обычно занимает до 5 минут. Для ручной выдачи дождитесь сообщения от администратора.\n"
        "4. Если возникла проблема, напишите в поддержку и укажите номер заказа.\n\n"
        "Замена возможна, если проблема с товаром подтверждена поддержкой.",
        "1. Choose a product.\n2. Pay using the selected method. For SBP, submit your receipt in the bot.\n3. Wait for delivery or a message from the administrator.\n"
        "4. If you have a problem, contact support with your order number.\n\n"
        "A replacement is available if support confirms the issue.",
    ),
    "catalog": ("Выберите категорию.", "Choose a category."),
    "empty": ("Здесь пока ничего нет.", "Nothing here yet."),
    "category": ("{title}\nВыберите товар.", "{title}\nChoose a product."),
    "product": ("<b>{title}</b>\n{description}\n\nЦена за штуку · {rubles} по СБП или {price} ⭐\nВ наличии · {stock}",
                "<b>{title}</b>\n{description}\n\nUnit price · {rubles} via SBP or {price} ⭐\nAvailable · {stock}"),
    "quantity": ("Введите количество от 1 до {max}.", "Enter a quantity from 1 to {max}."),
    "quote": ("{title} × {qty}\nВыберите способ оплаты. Сумма указана на кнопке.",
              "{title} × {qty}\nChoose a payment method. The amount is shown on the button."),
    "invoice": ("Оплатите счёт выше. Если заказ устарел, оформите его заново.",
                "Pay the invoice above. If the order expired, create a new one."),
    "invoice_line": ("Заказ №{order} · {qty} шт.", "Order #{order} · {qty} items"),
    "sbp_details": (
        "<b>Заказ №{order} · оплата по СБП</b>\nСумма · <b>{amount}</b>\nНомер · <code>{phone}</code>\nБанк · <b>{bank}</b>\n\nПереведите точную сумму и нажмите «Я оплатил».",
        "<b>Order #{order} · SBP payment</b>\nAmount · <b>{amount}</b>\nPhone · <code>{phone}</code>\nBank · <b>{bank}</b>\n\nTransfer the exact amount and tap “I paid”.",
    ),
    "sbp_prompt": ("Пришлите чек по заказу №{order} фотографией, изображением или PDF-файлом.",
                   "Send the receipt for order #{order} as a photo, image or PDF."),
    "sbp_received": ("Чек по заказу №{order} отправлен администратору. Ожидайте решения.",
                     "We sent the receipt for order #{order} to the administrator for review."),
    "receipt_duplicate": ("Этот файл чека уже использован. Если нужна помощь, напишите в поддержку.",
                          "This receipt file has already been used. Contact support for help."),
    "sbp_declined": ("Извините, заявку по заказу №{order} отклонили.\nПричина · {reason}\nЕсли вы перевели деньги, напишите в поддержку.",
                     "Order #{order} was declined.\nReason · {reason}\nIf you transferred money, contact support."),
    "sbp_order": ("Заказ №{id}\n{title} × {qty}\nОплата по СБП · {total}\nСтатус · {status}",
                  "Order #{id}\n{title} × {qty}\nSBP payment · {total}\nStatus · {status}"),
    "sbp_status_review": ("Чек на проверке", "Receipt under review"),
    "status_declined": ("Отклонён", "Declined"),
    "profile": ("<b>Профиль</b>\nID · <code>{id}</code>\nБаланс · {main}\nРеферальный баланс · {referral}\nОформлено заказов · {orders}\nПолучено товаров · {units}",
                "<b>Profile</b>\nID · <code>{id}</code>\nBalance · {main}\nReferral balance · {referral}\nOrders placed · {orders}\nItems delivered · {units}"),
    "stats": ("Заказов выдано · {orders}\nТоваров получено · {units}\nОплачено · {stars} ⭐ и {rubles} по СБП",
              "Orders delivered · {orders}\nItems delivered · {units}\nPaid · {stars} ⭐ and {rubles} via SBP"),
    "topup": ("Пополнить Telegram Stars можно через настройки Telegram или @PremiumBot. Бонусный баланс магазина пополняется промокодами и начислениями.",
              "Top up Telegram Stars in Telegram settings or via @PremiumBot. Promo codes and credits add to your shop balance."),
    "referral": ("Приглашено · {invited}\nСовершили покупку · {buyers}\nНачисление · {reward} за первую выданную покупку каждого приглашённого.\n\n{link}",
                 "Invited · {invited}\nPurchased · {buyers}\nEarn {reward} per referral after their first order is delivered.\n\n{link}"),
    "referral_paid": ("На реферальный баланс начислено {amount}.", "You earned {amount} in referral credit."),
    "promo_prompt": ("Отправьте промокод.", "Send your promo code."),
    "promo_done": ("На баланс начислено {amount}.", "We added {amount} to your balance."),
    "promo_invalid": ("Промокод недействителен, исчерпан или уже использован.", "The code is invalid, depleted or already used."),
    "language": ("Выберите язык.", "Choose your language."),
    "transactions": ("<b>Транзакции</b>\n{items}", "<b>Transactions</b>\n{items}"),
    "orders": ("Ваши заказы", "Your orders"),
    "pending": ("Заказы, ожидающие оплаты", "Orders awaiting payment"),
    "order": ("Заказ №{id}\n{title} × {qty}\nК оплате · {total} ⭐\nСтатус · {status}",
              "Order #{id}\n{title} × {qty}\nAmount · {total} ⭐\nStatus · {status}"),
    "status_open": ("Ожидает оплаты", "Awaiting payment"),
    "status_reserved": ("Ожидает оплаты", "Awaiting payment"),
    "status_expired": ("Истёк", "Expired"),
    "status_review": ("Ожидает ручной выдачи", "Awaiting manual delivery"),
    "status_fulfilling": ("Выдаётся", "Delivering"),
    "status_delivered": ("Выдан", "Delivered"),
    "status_refunding": ("Возвращаем оплату", "Refund in progress"),
    "status_refunded": ("Отклонён, оплата возвращена", "Declined and refunded"),
    "paid": ("Оплата заказа №{order} подтверждена.", "Payment confirmed for order #{order}."),
    "delivered": ("Заказ №{order} выдан.\n{delivery}", "Order #{order} delivered.\n{delivery}"),
    "refund": ("Извините, заявку по заказу №{order} отклонили. Stars вернулись на ваш счёт.\nПричина · {reason}\nНапишите в поддержку, если остались вопросы.",
               "Order #{order} was declined. We refunded your Stars.\nReason · {reason}\nContact support if you have questions."),
    "unexpected": ("Оплата по устаревшему или недействительному счёту возвращена. Оформите заказ заново или напишите в поддержку.",
                   "We refunded your payment for an expired or invalid invoice. Create a new order or contact support."),
    "support": ("Поддержка", "Support"),
    "ticket_prompt": ("Опишите проблему. Если есть номер заказа, укажите его. Можно отправить текст, фото или файл.",
                      "Describe the issue. Include the order number if available. You can send text, a photo or a file."),
    "ticket_sent": ("Сообщение отправлено в тикет №{id}.", "Message sent to ticket #{id}."),
    "ticket": ("Тикет №{id} · {status}\n{history}", "Ticket #{id} · {status}\n{history}"),
    "ticket_open": ("Открыт", "Open"),
    "ticket_closed": ("Закрыт", "Closed"),
    "ticket_reply": ("Ответ поддержки в тикете №{id}", "Support reply in ticket #{id}"),
    "ticket_closed_notice": ("Поддержка закрыла тикет №{id}.", "Support closed ticket #{id}."),
    "media": ("Вложение", "Attachment"),
    "message_prompt": ("Отправьте текст, фото или файл.", "Send text, a photo or a file."),
    "subscription": ("Подпишитесь на указанные каналы или чаты, затем нажмите «Проверить подписку».",
                     "Join the listed channels or chats, then tap Check subscription."),
    "subscription_error": ("Не удалось проверить подписку. Попробуйте позже или напишите в поддержку.",
                           "We could not verify your subscription. Try again later or contact support."),
    "banned": ("Доступ ограничен. Вы можете написать в поддержку.", "Your access is restricted. You can contact support."),
    "unavailable": ("Раздел или товар недоступен.", "This section or product is unavailable."),
    "stock": ("Такого количества нет в наличии или карточка товара изменилась.", "The quantity is unavailable or the product has changed."),
    "amount_range": ("Сумма заказа слишком велика. Уменьшите количество.", "The total is too high. Choose a smaller quantity."),
    "balance_changed": ("Баланс изменился. Оформите заказ заново.", "Your balance changed. Create a new order."),
    "invalid_invoice": ("Счёт недействителен. Оформите заказ заново.", "The invoice is invalid. Create a new order."),
    "already_handled": ("Действие уже выполнено или недоступно.", "This action has already been processed or is unavailable."),
    "invalid": ("Проверьте формат ввода и попробуйте ещё раз.", "Check your input and try again."),
    "saved": ("Сохранено.", "Saved."),
    "welcome_invite": ("Перейдите по ссылке и отправьте заявку со своего Telegram-аккаунта:\n{link}",
                       "Open the link and request to join from your Telegram account:\n{link}"),
    "invite_used": ("Приглашение использовано.", "Invitation used."),
    "invite_expired": ("Срок приглашения истёк. Напишите в поддержку.", "This invitation expired. Contact support."),
    "notify_balance": ("Баланс изменён администратором на {amount}.", "The administrator adjusted your balance by {amount}."),
}

BUTTON = {
    "catalog": ("🛍 Каталог", "🛍 Catalog"),
    "links": ("🔗 Полезные ссылки", "🔗 Useful links"),
    "profile": ("👤 Профиль", "👤 Profile"),
    "support": ("🔥 Поддержка", "🔥 Support"),
    "reviews": ("⭐ Отзывы", "⭐ Reviews"),
    "channel": ("🎧 Канал", "🎧 Channel"),
    "rules": ("📘 Правила", "📘 Rules"),
    "home": ("‹ В главное меню", "‹ Main menu"),
    "back": ("‹ Назад", "‹ Back"),
    "topup": ("💲 Пополнить баланс", "💲 Top up"),
    "purchases": ("📦 Мои покупки", "📦 My purchases"),
    "stats": ("📊 Статистика покупок", "📊 Purchase statistics"),
    "referral": ("👥 Реферальная программа", "👥 Referral program"),
    "promo": ("🎟 Промокод", "🎟 Promo code"),
    "transactions": ("💰 Транзакции", "💰 Transactions"),
    "language": ("🌐 Язык / Language", "🌐 Language / Язык"),
    "pending": ("Ожидают оплаты", "Awaiting payment"),
    "buy": ("Выбрать количество", "Select quantity"),
    "pay": ("Оплатить · {amount} ⭐", "Pay · {amount} ⭐"),
    "sbp": ("Оплатить по СБП · {amount}", "Pay via SBP · {amount}"),
    "sbp_discount": ("СБП с бонусами · {amount}", "SBP with credit · {amount}"),
    "sbp_paid": ("Я оплатил", "I paid"),
    "discount": ("Списать бонусы и оплатить · {amount} ⭐", "Use credit and pay · {amount} ⭐"),
    "subscribe": ("Проверить подписку", "Check subscription"),
    "subscription_link": ("Подписаться · {n}", "Join · {n}"),
    "new_ticket": ("Создать тикет", "New ticket"),
    "reply": ("Ответить", "Reply"),
    "see_order": ("Посмотреть заказ", "View order"),
    "open_link": ("Открыть приглашение", "Open invitation"),
    "premium_bot": ("Открыть @PremiumBot", "Open @PremiumBot"),
    "prev": ("‹ Предыдущая", "‹ Previous"),
    "next": ("Следующая ›", "Next ›"),
}


def rub(amount):
    sign = "−" if amount < 0 else ""
    amount = abs(amount)
    return f"{sign}{amount // 100},{amount % 100:02d} ₽"


# Strip decorative leading emoji only: keep prices, currencies and navigation text.
_LEADING_EMOJI = re.compile(
    r"^(?:[0-9#*]\ufe0f?\u20e3|[\U0001f000-\U0001faff\u2600-\u27bf\u2300-\u23ff]"
    r"[\ufe0e\ufe0f\U0001f3fb-\U0001f3ff]*(?:\u200d[\U0001f000-\U0001faff\u2600-\u27bf]"
    r"[\ufe0e\ufe0f\U0001f3fb-\U0001f3ff]*)*)\s*"
)


def without_button_emoji(text):
    result = text.lstrip()
    while True:
        cleaned = _LEADING_EMOJI.sub("", result, count=1)
        if cleaned == result:
            return result
        result = cleaned


class Copybook:
    def __init__(self, store):
        self.store = store

    def lang(self, user):
        return self.store.get(f"lang:{user}", "ru")

    def text(self, user, key, **values):
        lang = self.lang(user)
        default = TEXT[key][lang == "en"]
        template = self.store.get(f"text:{lang}:{key}", default)
        return template.format(**{k: (str(v) if isinstance(v, TitleHTML) else escape(str(v))) for k, v in values.items()})

    def button(self, user, key, callback=None, url=None, label=None, style=None, item_icon=None, **values):
        return self.button_for(self.lang(user), key, callback, url, label, style, item_icon=item_icon, **values)

    def named_button(self, user, key, callback, row, prefix="", suffix=""):
        text, icon = button_title(row)
        return self.button(user, key, callback, label=prefix + text + suffix, item_icon=icon)

    def button_for(self, lang, key, callback=None, url=None, label=None, style=None, item_icon=None, **values):
        default = label or BUTTON.get(key, (key, key))[lang == "en"]
        config = self.store.get(f"button:{lang}:{key}", {})
        # A name's own icon wins over generic list-button decoration.
        if item_icon:
            config = {**config, "icon": item_icon}
        template = config.get("label")
        text = template.format(**values) if template is not None else default if label is not None else default.format(**values)
        prefix = config.get("prefix", "")
        replacing_icon = bool(config.get("icon")) or "emoji" in config or bool(config.get("accent"))
        if replacing_icon:
            text = without_button_emoji(text) or text
            prefix = without_button_emoji(prefix)
        # A premium icon is the sole decorative icon, including for older saved settings.
        accent = None if config.get("icon") else config.get("accent")
        emoji = None if config.get("icon") else config.get("emoji")
        text = " ".join(filter(None, (accent, emoji, prefix, text)))
        button = {"text": text, "url": url} if url else {"text": text, "callback_data": callback}
        if config.get("style", style):
            button["style"] = config.get("style", style)
        if config.get("icon"):
            button["icon_custom_emoji_id"] = config["icon"]
        return button
