import json
import urllib.error
import urllib.request


class TelegramError(Exception):
    def __init__(self, method, code, description, retry_after=None):
        super().__init__(f"{method}: {description}")
        self.code = code
        self.description = description
        self.retry_after = retry_after


class Telegram:
    def __init__(self, token, test=False):
        self.url = f"https://api.telegram.org/bot{token}/{'test/' if test else ''}"

    def call(self, method, **data):
        request = urllib.request.Request(
            self.url + method, json.dumps(data, ensure_ascii=False).encode("utf-8"),
            {"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=data.get("timeout", 0) + 10) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                payload = json.load(error)
            except ValueError:
                raise TelegramError(method, error.code, "HTTP error") from None
        except (OSError, ValueError):
            raise TelegramError(method, 503, "Telegram connection failed") from None
        if not payload["ok"]:
            raise TelegramError(
                method, payload["error_code"], payload["description"],
                payload.get("parameters", {}).get("retry_after"),
            )
        return payload.get("result")
