from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from secrets import token_urlsafe

from fastapi import HTTPException, Request


class AdminAuth:
    COOKIE_NAME = 'pixel_admin'
    CSRF_HEADER = 'x-csrf-token'

    def __init__(self, token_hash: str, session_secret: str, minutes: int, secure: bool) -> None:
        self._token_hash = token_hash.strip().lower()
        self._secret = session_secret.encode('utf-8')
        self._seconds = minutes * 60
        self.secure = secure

    @property
    def enabled(self) -> bool:
        return bool(self._token_hash and self._secret)

    def verify_token(self, token: str) -> bool:
        if not self.enabled:
            return False
        digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
        return hmac.compare_digest(digest, self._token_hash)

    def issue(self, admin_id: str = 'administrator') -> tuple[str, str]:
        csrf = token_urlsafe(24)
        payload = {'sub': admin_id, 'csrf': csrf, 'exp': int(time.time()) + self._seconds}
        encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
        signature = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
        return f'{encoded}.{signature}', csrf

    def decode(self, token: str | None) -> dict | None:
        if not self.enabled or not token:
            return None
        try:
            encoded, signature = token.rsplit('.', 1)
            expected = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                return None
            padded = encoded + '=' * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            return payload if int(payload['exp']) >= time.time() else None
        except (ValueError, KeyError, json.JSONDecodeError):
            return None

    def require(self, request: Request, *, mutation: bool = False) -> dict:
        payload = self.decode(request.cookies.get(self.COOKIE_NAME))
        if payload is None:
            raise HTTPException(status_code=401, detail='管理员登录已失效')
        if mutation:
            origin = request.headers.get('origin', '').rstrip('/')
            allowed = request.app.state.runtime.settings.allowed_origins
            if allowed and origin not in allowed:
                raise HTTPException(status_code=403, detail='Origin 不受信任')
            if not hmac.compare_digest(request.headers.get(self.CSRF_HEADER, ''), payload['csrf']):
                raise HTTPException(status_code=403, detail='CSRF 校验失败')
        return payload
