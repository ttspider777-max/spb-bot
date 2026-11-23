"""Step-by-step product creation and field editing. Drafts survive restarts."""
import re
from decimal import Decimal
from html import escape
from secrets import token_hex

from copybook import rub
from store import ShopError, KOPECKS_PER_STAR

FIELDS = {
    "category": "Категория", "title": "Название", "description": "Описание",
    "price": "Цена в Stars", "rub_price": "Цена по СБП", "stock": "Количество",
    "mode": "Способ выдачи", "target": "Что выдавать", "photo": "Фото",
}
MODES = {"manual": "Вручную", "text": "Текст или ссылка", "invite": "Доступ в канал / чат"}
PROMPTS = {
    "category": "Выберите категорию кнопкой. Вводить ID не нужно.",
    "catname": "Отправьте название новой категории (до 70 символов). Она создастся скрытой.",
    "title": "Отправьте название товара (до 70 символов).",
    "description": "Отправьте описание товара (до 255 символов).",
    "price": "Отправьте цену за одну штуку в Stars — целое число от 1 до 1 000 000.",
    "rub_price": "Отправьте цену за одну штуку в рублях, например 1,32. Или выберите автоматический расчёт.",
    "stock": "Сколько штук доступно? Отправьте целое число, например 10.",
    "mode": "Выберите способ выдачи кнопкой.",
    "target": "Отправьте текст или ссылку для автоматической выдачи (до 2500 символов).",
    "photo": "Отправьте фото товара или нажмите «Без фото».",
}


class ProductWizard:
    @property
    def product_draft_key(self):
        return f"product_draft:{self.admin}"

    def product_start(self, product=None):
        draft = {"token": token_hex(4), "step": "category", "data": {}, "product": product}
        if product:
            row = self.s.one("SELECT * FROM products WHERE id=?", product)
            if not row:
                raise ShopError("unavailable")
            draft.update(data={key: row[key] for key in FIELDS}, step="review",
                         revision=row["revision"], original_stock=row["stock"], active=row["active"])
        self.product_show(draft)

    def product_load(self, token, step):
        draft = self.s.get(self.product_draft_key)
        if not draft or draft["token"] != token or draft["step"] != step:
            raise ShopError("already_handled")
        return draft

    def product_steps(self, draft):
        steps = list(FIELDS)
        if draft["data"].get("mode") == "manual":
            steps.remove("target")
        return steps + ["review"]

    def product_show(self, draft, page=0, error=None):
        step, data = draft["step"], draft["data"]
        base = f"a:w:{draft['token']}:{step}"
        button = self.design_button
        rows = []
        if step == "review":
            cat = self.s.one("SELECT title,active FROM categories WHERE id=?", data["category"])
            category = cat["title"] if cat else "Категория удалена"
            price = data["rub_price"] if data["rub_price"] is not None else data["price"] * KOPECKS_PER_STAR
            text = (f"<b>Проверьте товар</b>\n{escape(data['title'])}\n{escape(data['description'])}\n\n"
                    f"Категория: {escape(category)}\nЦена: {data['price']} ⭐ / {rub(price)} по СБП\n"
                    f"Количество: {data['stock']}\nВыдача: {MODES[data['mode']]}\n"
                    f"Фото: {'есть' if data.get('photo') else 'нет'}")
            if data["mode"] != "manual":
                text += "\nЧто выдавать: " + escape(data["target"])
            if cat and not cat["active"]:
                text += "\n\nКатегория скрыта. Чтобы товар был виден в каталоге, опубликуйте категорию."
            if draft["product"]:
                rows.append([button("Сохранить изменения", f"{base}:save", "success")])
            else:
                rows.append([button("Опубликовать", f"{base}:publish", "success"),
                             button("Сохранить скрытым", f"{base}:save")])
            edits = [button(label, f"{base}:field_{key}") for key, label in FIELDS.items()
                     if key != "target" or data["mode"] != "manual"]
            rows.extend([edits[i:i + 2] for i in range(0, len(edits), 2)])
        else:
            steps = self.product_steps(draft)
            position = steps.index(step) + 1 if step in steps else 1
            text = f"<b>{FIELDS.get(step, 'Новая категория')} · шаг {position}/{len(steps) - 1}</b>\n{PROMPTS[step]}"
            if step == "category":
                cats = self.s.all("SELECT * FROM categories ORDER BY id LIMIT 9 OFFSET ?", page * 8)
                for cat in cats[:8]:
                    rows.append([button(cat["title"], f"{base}:cat_{cat['id']}")])
                nav = []
                if page:
                    nav.append(button("‹ Предыдущие", f"{base}:page_{page - 1}"))
                if len(cats) > 8:
                    nav.append(button("Следующие ›", f"{base}:page_{page + 1}"))
                if nav:
                    rows.append(nav)
                rows.append([button("Создать категорию", f"{base}:newcat")])
            elif step == "mode":
                rows = [[button(label, f"{base}:mode_{key}")] for key, label in MODES.items()]
            elif step == "rub_price":
                rows = [[button(f"Авто: {rub(data['price'] * KOPECKS_PER_STAR)}", f"{base}:auto")]]
            elif step == "photo":
                rows = [[button("Без фото", f"{base}:skip")]]
            elif step == "target" and data["mode"] == "invite":
                text = (f"<b>Доступ в канал / чат · шаг {position}/{len(steps) - 1}</b>\n"
                        "Добавьте бота администратором с правом приглашать участников. "
                        "Отправьте ID канала / чата, например -1001234567890.")
            if step in data:
                value = data[step]
                current = MODES.get(value, value) if step == "mode" else value
                if step == "category":
                    cat = self.s.one("SELECT title FROM categories WHERE id=?", value)
                    current = cat["title"] if cat else "Удалена"
                elif step == "rub_price":
                    current = "Автоматический расчёт" if value is None else rub(value)
                elif step == "photo":
                    current = "Фото добавлено" if value else "Без фото"
                text += "\n\nСейчас: " + escape(str(current)[:400])
                rows.append([button("Оставить как есть", f"{base}:keep")])
            if step != "category" or draft.get("editing"):
                rows.append([button("‹ Назад", f"{base}:back")])
        rows.append([button("Отменить", f"{base}:cancel")])
        if error:
            text = escape(error) + "\n\n" + text
        with self.s.db:
            self.s.put(self.product_draft_key, draft)
            self.s.state(self.admin, "a:product_step", draft["token"], step)
        if step == "review" and data.get("photo"):
            self.send(self.admin, text, rows, photo=data["photo"], home=False)
        else:
            self.ad_text(text, rows, back=None)

    def product_advance(self, draft):
        step, data = draft["step"], draft["data"]
        if step == "mode" and data["mode"] == "manual":
            data["target"] = ""
        if draft.get("editing"):
            # A changed delivery method needs its own new delivery contents.
            draft["step"] = "target" if step == "mode" and data["mode"] != "manual" and not data.get("target") else "review"
            if draft["step"] == "review":
                draft.pop("editing", None)
                draft.pop("edit_backup", None)
        else:
            steps = self.product_steps(draft)
            draft["step"] = steps[steps.index(step) + 1]
        self.product_show(draft)

    def product_action(self, args):
        if len(args) != 3:
            raise ShopError("invalid")
        token, step, action = args
        draft = self.product_load(token, step)
        data = draft["data"]
        if action == "cancel":
            with self.s.db:
                self.s.run("DELETE FROM settings WHERE key=?", self.product_draft_key)
                self.s.state(self.admin)
            self.admin_route(["products"])
            return
        if action == "back":
            if draft.pop("editing", None):
                backup = draft.pop("edit_backup", None)
                if backup:
                    draft["data"] = backup["data"]
                    draft["stock_changed"] = backup["stock_changed"]
                draft["step"] = "review"
            elif step == "catname":
                draft["step"] = "category"
            else:
                steps = self.product_steps(draft)
                draft["step"] = steps[max(0, steps.index(step) - 1)]
            self.product_show(draft)
            return
        if step == "review":
            if action.startswith("field_") and action[6:] in FIELDS:
                field = action[6:]
                if field == "target" and data["mode"] == "manual":
                    raise ShopError("invalid")
                draft.update(step=field, editing=True,
                             edit_backup={"data": dict(data), "stock_changed": draft.get("stock_changed", False)})
                self.product_show(draft)
            elif action in {"save", "publish"}:
                self.product_save(draft, publish=action == "publish")
            else:
                raise ShopError("invalid")
            return
        if action == "keep" and step in data:
            self.product_advance(draft)
            return
        if step == "category" and action.startswith("page_"):
            page = int(action[5:])
            if page < 0:
                raise ShopError("invalid")
            self.product_show(draft, page)
            return
        if step == "category" and action == "newcat":
            draft["step"] = "catname"
            self.product_show(draft)
            return
        if step == "category" and action.startswith("cat_"):
            value = int(action[4:])
            if not self.s.one("SELECT 1 FROM categories WHERE id=?", value):
                raise ShopError("unavailable")
            data[step] = value
        elif step == "mode" and action.startswith("mode_") and action[5:] in MODES:
            if data.get("mode") != action[5:]:
                data.pop("target", None)
            data[step] = action[5:]
        elif step == "photo" and action == "skip":
            data[step] = None
        elif step == "rub_price" and action == "auto":
            data[step] = None
        else:
            raise ShopError("invalid")
        self.product_advance(draft)

    def product_input(self, args, msg):
        draft = self.product_load(*args)
        step, data = draft["step"], draft["data"]
        body = (msg.get("text") or "").strip()
        error = None
        if step in {"title", "description", "catname"}:
            limit = 255 if step == "description" else 70
            if not body or len(body) > limit or (step != "description" and "\n" in body):
                error = f"Отправьте текст длиной от 1 до {limit} символов."
            elif step == "catname":
                with self.s.db:
                    cursor = self.s.run("INSERT INTO categories(title) VALUES(?)", body)
                    data["category"] = cursor.lastrowid
                draft["step"] = "category"
            else:
                data[step] = body
        elif step in {"price", "stock"}:
            least, most = (1, 10**6) if step == "price" else (0, 10**9)
            if not re.fullmatch(r"[0-9]{1,10}", body) or not least <= int(body) <= most:
                error = f"Введите целое число от {least} до {most}."
            else:
                data[step] = int(body)
                if step == "stock":
                    draft["stock_changed"] = True
        elif step == "rub_price":
            if not re.fullmatch(r"[0-9]{1,7}(?:[.,][0-9]{1,2})?", body):
                error = "Введите цену в рублях, например 1,32."
            else:
                amount = int(Decimal(body.replace(',', '.')) * 100)
                if not 100 <= amount <= 100000000:
                    error = "Цена должна быть от 1 до 1 000 000 рублей."
                else:
                    data[step] = amount
        elif step == "target":
            if data["mode"] == "invite":
                if not re.fullmatch(r"-[0-9]{4,17}", body):
                    error = "Отправьте числовой ID канала / чата, начиная с -100."
                else:
                    self.product_check_invite(body)
                    data[step] = body
            elif not 1 <= len(body) <= 2500:
                error = "Отправьте текст выдачи длиной от 1 до 2500 символов."
            else:
                data[step] = body
        elif step == "photo" and msg.get("photo"):
            data[step] = msg["photo"][-1]["file_id"]
        else:
            error = "Выберите действие кнопкой ниже." if step in {"category", "mode", "review"} else "Отправьте фото или нажмите «Без фото»."
        if error:
            self.product_show(draft, error=error)
            return
        self.product_advance(draft)

    def product_check_invite(self, target):
        me = self.api.call("getMe")
        member = self.api.call("getChatMember", chat_id=int(target), user_id=me["id"])
        if member["status"] != "administrator" or not member.get("can_invite_users"):
            raise ShopError("invalid")

    def product_save(self, draft, publish=False):
        data = draft["data"]
        if not all(key in data for key in FIELDS):
            raise ShopError("invalid")
        if data["mode"] == "invite":
            self.product_check_invite(data["target"])
        with self.s.db:
            if not self.s.one("SELECT 1 FROM categories WHERE id=?", data["category"]):
                raise ShopError("unavailable")
            product = draft["product"]
            if product:
                row = self.s.one("SELECT * FROM products WHERE id=?", product)
                if not row or row["revision"] != draft["revision"]:
                    raise ShopError("already_handled")
                if draft.get("stock_changed") and row["stock"] != draft["original_stock"]:
                    self.product_show(draft, error="Остаток изменился после начала редактирования. Отмените изменения и откройте товар заново.")
                    return
                if not draft.get("stock_changed"):
                    data["stock"] = row["stock"]
                self.s.run("""UPDATE products SET category=?,title=?,description=?,price=?,rub_price=?,stock=?,
                              mode=?,target=?,photo=?,revision=revision+1 WHERE id=?""",
                           *(data[key] for key in FIELDS), product)
            else:
                cursor = self.s.run("""INSERT INTO products(category,title,description,price,rub_price,stock,mode,target,photo,active)
                                       VALUES(?,?,?,?,?,?,?,?,?,?)""", *(data[key] for key in FIELDS), int(publish))
                product = cursor.lastrowid
            self.s.run("DELETE FROM settings WHERE key=?", self.product_draft_key)
            self.s.state(self.admin)
        self.ad_card("product", product)
