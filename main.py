import argparse
import getpass
import json
import logging
import os
import re
import time
from pathlib import Path

from bot import Bot
from copybook import rub
from store import REFERRAL_CREDIT, Store
from telegram import Telegram, TelegramError

LOG = logging.getLogger("shop")
ADMIN_ID = 8717087613
UPDATES = ["message", "callback_query", "pre_checkout_query", "chat_join_request"]


class Worker:
    def __init__(self, bot):
        self.bot = bot
        self.s = bot.s
        self.api = bot.api

    def next(self):
        current = int(time.time())
        job = self.s.one("SELECT * FROM jobs WHERE due<=? ORDER BY due,rowid LIMIT 1", current)
        if not job:
            return
        options = json.loads(job["data"])
        try:
            self.process(job["kind"], **options)
        except TelegramError as error:
            tries = job["failures"] + 1
            if error.code in {400, 403} and job["kind"] in {
                "paid", "delivered_notice", "ticket", "ticket_close", "notice_refund",
                "balance", "copy", "referral", "declined",
            }:
                if job["kind"] in {"ticket", "copy"}:
                    with self.s.db:
                        self.s.enqueue(f"failure:{job['key']}", "failure", description=job["kind"])
                LOG.warning("Telegram could not deliver %s (%s)", job["key"], error.code)
            else:
                delay = error.retry_after or min(3600, 3 * (2 ** min(tries, 10)))
                with self.s.db:
                    self.s.run("UPDATE jobs SET due=?, failures=? WHERE key=?", current + delay, tries, job["key"])
                    if job["kind"] == "deliver" and tries == 1:
                        self.s.enqueue(f"delivery_error:{options['order']}", "review", order=options["order"])
                LOG.warning("Queued %s for another attempt (%s)", job["key"], error.code)
                return
        with self.s.db:
            self.s.run("DELETE FROM jobs WHERE key=?", job["key"])

    def process(self, kind, **data):
        bot = self.bot
        admin = bot.admin
        user = data.get("user")
        if kind == "ticket":
            receiver, ticket = data["receiver"], data["ticket"]
            is_admin_reply = data["admin"]
            target = f"{'ticket' if is_admin_reply else 'a:ticket'}:{ticket}"
            if is_admin_reply:
                bot.say(receiver, "ticket_reply", [[bot.b(receiver, "ticket_entry", target, label=f"№{ticket}")]], id=ticket)
            else:
                bot.ad_text(f"Новое сообщение в тикете №{ticket}", [[bot.b(admin, "ticket_entry", target, label=f"№{ticket}")]])
            self.api.call("copyMessage", chat_id=receiver, from_chat_id=data["source"], message_id=data["message"])
            return
        if kind == "copy":
            self.api.call("copyMessage", chat_id=user, from_chat_id=data["source"], message_id=data["message"])
            return
        if kind == "failure":
            bot.ad_text("Не удалось доставить сообщение. Возможно, получатель заблокировал бота или исходное сообщение удалено.",
                        key="send_failure")
            return
        if kind == "ticket_close":
            bot.say(user, "ticket_closed_notice", id=data["ticket"])
            return
        if kind in {"balance", "referral"}:
            bot.say(user, "notify_balance" if kind == "balance" else "referral_paid",
                    amount=rub(data["amount"] if kind == "balance" else REFERRAL_CREDIT))
            return
        if kind == "unexpected":
            self.refund(user, data["charge"])
            bot.say(user, "unexpected", [[bot.b(user, "support", "support")]])
            return
        order = data["order"]
        row = self.s.order(order)
        user = row["user"]
        if kind == "receipt" and row["status"] == "review":
            try:
                bot.ad_receipt(row)
            except TelegramError as error:
                if error.code != 400:
                    raise
                LOG.warning("Telegram receipt attachment could not be sent for order %s", order)
            bot.ad_card("order", order)
        elif kind == "declined":
            bot.say(user, "sbp_declined", [[bot.b(user, "support", "support")]], order=order, reason=row["reject_reason"])
        elif kind == "review":
            if row["status"] in {"review", "fulfilling"}:
                bot.ad_card("order", order)
        elif kind == "paid":
            bot.say(user, "paid", [[bot.b(user, "see_order", f"order:{order}")]], order=order)
        elif kind == "deliver":
            self.deliver(row)
        elif kind == "delivered_notice" and row["status"] == "delivered":
            bot.show_delivery(row)
        elif kind == "refund" and row["status"] == "refunding":
            self.refund(user, row["charged"])
            with self.s.db:
                self.s.release(row)
                self.s.run("UPDATE orders SET status='refunded' WHERE id=?", order)
                self.s.enqueue(f"refund_notice:{order}", "notice_refund", order=order)
        elif kind == "notice_refund":
            bot.say(user, "refund", [[bot.b(user, "support", "support")]], order=order, reason=row["reject_reason"])
        elif kind == "revoke":
            try:
                self.api.call("revokeChatInviteLink", chat_id=int(row["target"]), invite_link=row["invite"])
            except TelegramError as error:
                if error.code != 400 or not any(word in error.description.upper() for word in ("EXPIRED", "REVOKED", "INVITE_HASH_INVALID")):
                    raise

    def refund(self, user, charge):
        try:
            self.api.call("refundStarPayment", user_id=user, telegram_payment_charge_id=charge)
        except TelegramError as error:
            if "CHARGE_ALREADY_REFUNDED" not in error.description.upper():
                raise

    def deliver(self, row):
        if row["status"] != "fulfilling":
            return
        order = row["id"]
        url, expires = row["invite"], row["invite_until"]
        if row["mode"] == "invite" and not url:
            expires = int(time.time()) + 7 * 86400
            invite = self.api.call("createChatInviteLink", chat_id=int(row["target"]), name=row["invite_name"],
                                   expire_date=expires, creates_join_request=True)
            url = invite["invite_link"]
        with self.s.db:
            self.s.run("UPDATE orders SET status='delivered', invite=?, invite_until=? WHERE id=?", url, expires, order)
            self.s.referred_sale(row)
            self.s.enqueue(f"delivered_notice:{order}", "delivered_notice", order=order)


def poll(bot):
    store, api = bot.s, bot.api
    bot.username = api.call("getMe")["username"]
    LOG.info("Bot @%s is running", bot.username)
    worker = Worker(bot)
    offset = store.get("offset", 0)
    while True:
        try:
            updates = api.call("getUpdates", offset=offset, timeout=3, allowed_updates=UPDATES, limit=100)
            # Answer pre-checkout queries before processing less time-sensitive work in the batch.
            for update in updates:
                if "pre_checkout_query" in update:
                    bot.update(update)
            for update in updates:
                if "pre_checkout_query" not in update:
                    bot.update(update)
                offset = update["update_id"] + 1
                with store.db:
                    store.put("offset", offset)
            with store.db:
                store.expired()
            for _ in range(3):
                worker.next()
        except TelegramError as error:
            if error.code == 409:
                LOG.error("Telegram returned 409. Stop other instances and remove an existing webhook before polling.")
                return 2
            LOG.warning("Telegram temporarily unavailable (%s)", error.code)
            time.sleep(min(60, error.retry_after or 3))


def main():
    parser = argparse.ArgumentParser(description="Heliys Telegram shop")
    parser.add_argument("--test", action="store_true", help="use Telegram's separate test environment")
    parser.add_argument("--db", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or getpass.getpass("Telegram bot token: ")
    if not re.fullmatch(r"[0-9]{5,16}:[A-Za-z0-9_-]{25,64}", token.strip()):
        parser.error("Telegram bot token has an invalid format")
    file = args.db or Path(__file__).resolve().parent / ("shop-test.sqlite3" if args.test else "shop.sqlite3")
    api = Telegram(token.strip(), args.test)
    store = Store(file)
    try:
        return poll(Bot(api, store, ADMIN_ID))
    except KeyboardInterrupt:
        return 0
    except TelegramError as error:
        LOG.error("Unable to start bot. Telegram API returned %s.", error.code)
        return 1
    finally:
        store.db.close()


if __name__ == "__main__":
    raise SystemExit(main())
