import http.client
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

LOG = logging.getLogger('shop')
READ_ONLY = {'getMe', 'getUpdates', 'getChat', 'getChatMember'}


class TelegramError(Exception):
    def __init__(self, method, code, description, retry_after=None):
        super().__init__(f'{method}: {description}')
        self.code = code
        self.description = description
        self.retry_after = retry_after


class Telegram:
    def __init__(self, token, test=False):
        self.path = f"/bot{token}/{'test/' if test else ''}"
        self.url = 'https://api.telegram.org' + self.path
        self._local = threading.local()
        self._connections = set()
        self._lock = threading.Lock()
        self._acks = ThreadPoolExecutor(max_workers=2, thread_name_prefix='telegram-click')
        self._ack_slots = threading.BoundedSemaphore(16)
        # Preserve OS/environment proxy behavior where urllib is needed.
        self._proxy = bool(urllib.request.getproxies().get('https')) and not urllib.request.proxy_bypass('api.telegram.org')

    def _connection(self, timeout):
        connection = getattr(self._local, 'connection', None)
        if connection is not None and time.monotonic() - self._local.used > 20:
            self.close_thread()
            connection = None
        if connection is None:
            connection = http.client.HTTPSConnection('api.telegram.org', timeout=timeout)
            with self._lock:
                self._connections.add(connection)
            self._local.connection = connection
        connection.timeout = timeout
        if connection.sock is not None:
            connection.sock.settimeout(timeout)
        self._local.used = time.monotonic()
        return connection

    def close_thread(self):
        connection = getattr(self._local, 'connection', None)
        if connection is not None:
            connection.close()
            with self._lock:
                self._connections.discard(connection)
            self._local.connection = None

    def _request(self, method, body, timeout):
        if self._proxy:
            request = urllib.request.Request(self.url + method, body, {'Content-Type': 'application/json'}, method='POST')
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                try:
                    return json.load(error)
                except ValueError:
                    raise TelegramError(method, error.code, 'HTTP error') from None
        connection = self._connection(timeout)
        connection.request('POST', self.path + method, body=body,
                           headers={'Content-Type': 'application/json', 'Connection': 'keep-alive'})
        response = connection.getresponse()
        raw = response.read()  # Fully consume the response before reusing its connection.
        self._local.used = time.monotonic()
        if response.will_close:
            self.close_thread()
        try:
            return json.loads(raw)
        except ValueError:
            raise TelegramError(method, response.status, 'Invalid Telegram response') from None

    def call(self, method, **data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        timeout = data.get('timeout', 0) + 10
        started = time.perf_counter()
        for attempt in range(2):
            try:
                payload = self._request(method, body, timeout)
                break
            except (OSError, ValueError, http.client.HTTPException):
                self.close_thread()
                # Never replay a payment, delivery or message after an ambiguous network error.
                if attempt or method not in READ_ONLY:
                    raise TelegramError(method, 503, 'Telegram connection failed') from None
        elapsed = time.perf_counter() - started
        if method != 'getUpdates' and elapsed >= 1:
            LOG.info('Telegram %s took %.2fs', method, elapsed)
        if not isinstance(payload, dict) or 'ok' not in payload:
            raise TelegramError(method, 503, 'Invalid Telegram response')
        if not payload['ok']:
            raise TelegramError(method, payload.get('error_code', 503), payload.get('description', 'Telegram error'),
                                payload.get('parameters', {}).get('retry_after'))
        return payload.get('result')

    def answer_callback(self, query_id):
        # A slow acknowledgement must not block sending the requested screen.
        if not self._ack_slots.acquire(blocking=False):
            return
        def acknowledge():
            try:
                self.call('answerCallbackQuery', callback_query_id=query_id)
            except TelegramError:
                pass
            finally:
                self._ack_slots.release()
        try:
            self._acks.submit(acknowledge)
        except RuntimeError:
            self._ack_slots.release()

    def close(self):
        self._acks.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            connection.close()
