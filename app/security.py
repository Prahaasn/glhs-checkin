"""Small, bounded defenses for the supervised single-server pilot."""
import time
import hashlib
import hmac
import secrets
from collections import OrderedDict
from threading import Lock

from fastapi import HTTPException


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must be 12 to 256 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        method, rounds, salt, expected = stored.split("$")
        if method != "pbkdf2_sha256" or int(rounds) != 600_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


class FailureLimiter:
    def __init__(self, limit=20, window=60, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.entries = OrderedDict()
        self.lock = Lock()

    def check(self, identity):
        with self.lock:
            now = self.clock()
            count, start = self.entries.get(identity, (0, now))
            if now - start >= self.window:
                self.entries.pop(identity, None)
            elif count >= self.limit:
                raise HTTPException(429, "Too many failed attempts. Please wait one minute.", headers={"Retry-After": "60"})

    def failed(self, identity):
        with self.lock:
            now = self.clock()
            count, start = self.entries.get(identity, (0, now))
            if now - start >= self.window:
                count, start = 0, now
            self.entries[identity] = (count + 1, start)
            self.entries.move_to_end(identity)
            while len(self.entries) > 10000:
                self.entries.popitem(last=False)


class BodyLimitMiddleware:
    """Reject oversized request bodies before JSON parsing, including chunked bodies."""
    def __init__(self, app, limit=8192):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > self.limit:
                await send({'type': 'http.response.start', 'status': 413, 'headers': [(b'content-type', b'application/json'), (b'cache-control', b'no-store')]})
                await send({'type': 'http.response.body', 'body': b'{"detail":"Request body too large."}'})
                return
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
