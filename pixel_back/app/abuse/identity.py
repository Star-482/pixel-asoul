from __future__ import annotations

import base64
import hashlib
import hmac
import time
from uuid import uuid4


class VisitorIdentity:
    COOKIE_NAME = 'pixel_visitor'

    def __init__(self, secret: str, days: int) -> None:
        self._secret = secret.encode('utf-8')
        self.max_age = days * 24 * 60 * 60

    def issue(self) -> tuple[str, str]:
        visitor_id = str(uuid4())
        issued_at = str(int(time.time()))
        body = f'{visitor_id}.{issued_at}'
        signature = hmac.new(self._secret, body.encode('utf-8'), hashlib.sha256).digest()
        token = f'{body}.{base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")}'
        return visitor_id, token

    def verify(self, token: str | None) -> str | None:
        if not token or not self._secret:
            return None
        try:
            visitor_id, issued_at, encoded_signature = token.split('.', 2)
            if len(visitor_id) != 36 or int(issued_at) + self.max_age < time.time():
                return None
            body = f'{visitor_id}.{issued_at}'
            expected = hmac.new(self._secret, body.encode('utf-8'), hashlib.sha256).digest()
            padding = '=' * (-len(encoded_signature) % 4)
            actual = base64.urlsafe_b64decode(encoded_signature + padding)
            return visitor_id if hmac.compare_digest(expected, actual) else None
        except (ValueError, UnicodeError):
            return None
