"""Short-lived, one-use desktop pairing without putting the API key in a URL."""
import hashlib
import hmac
import secrets
import threading
import time


def make_launch_ticket(secret: str) -> str:
    payload = f'{int(time.time()) + 60}.{secrets.token_urlsafe(24)}'
    signature = hmac.new(secret.encode(), ('studio:' + payload).encode(), hashlib.sha256).hexdigest()
    return payload + '.' + signature


class StudioSessions:
    def __init__(self, secret: str):
        self.secret = secret
        self.sessions: dict[str, float] = {}
        self.used: dict[str, float] = {}
        self.lock = threading.Lock()

    def accepts(self, value: str) -> bool:
        if not value:
            return False
        if secrets.compare_digest(value.encode(), self.secret.encode()):
            return True
        with self.lock:
            return self.sessions.get(value, 0) > time.time()

    def redeem(self, ticket: str) -> str | None:
        try:
            expiry, nonce, signature = ticket.split('.')
            expires = int(expiry)
        except (ValueError, TypeError):
            return None
        now = time.time()
        if not now < expires <= now + 65 or not 20 <= len(nonce) <= 64:
            return None
        expected = hmac.new(self.secret.encode(), f'studio:{expiry}.{nonce}'.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(signature.encode(), expected.encode()):
            return None
        with self.lock:
            self.used = {key: until for key, until in self.used.items() if until > now}
            self.sessions = {key: until for key, until in self.sessions.items() if until > now}
            if nonce in self.used or len(self.sessions) >= 128:
                return None
            self.used[nonce] = expires
            session_token = secrets.token_urlsafe(32)
            self.sessions[session_token] = now + 4 * 3600
            return session_token
