from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Challenge:
    id: str
    provider: str
    app_id: str


class ChallengeProvider:
    """Provider port. The Tencent API call is intentionally isolated here."""

    def __init__(self, app_id: str, secret_id: str, secret_key: str, app_secret_key: str) -> None:
        self.app_id = app_id
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.app_secret_key = app_secret_key
        self.degraded = False

    @property
    def enabled(self) -> bool:
        return bool(self.app_id and self.secret_id and self.secret_key and self.app_secret_key)

    def create(self) -> Challenge:
        return Challenge(id=str(uuid4()), provider='tencent' if self.enabled else 'unavailable', app_id=self.app_id)

    async def verify(self, ticket: str, randstr: str, user_ip: str) -> bool | None:
        """True/False result; None means provider failure and activates safe degradation.

        Tencent's SDK is optional at import time so local development does not
        need cloud credentials. Production installs `tencentcloud-sdk-python`.
        """
        if not self.enabled:
            self.degraded = True
            return None
        try:
            from tencentcloud.captcha.v20190722 import captcha_client, models
            from tencentcloud.common import credential

            cred = credential.Credential(self.secret_id, self.secret_key)
            client = captcha_client.CaptchaClient(cred, 'ap-guangzhou')
            request = models.DescribeCaptchaResultRequest()
            request.CaptchaType = 9
            request.Ticket = ticket
            request.Randstr = randstr
            request.UserIp = user_ip
            request.CaptchaAppId = int(self.app_id)
            request.AppSecretKey = self.app_secret_key
            response = await asyncio.to_thread(client.DescribeCaptchaResult, request)
            self.degraded = False
            captcha_code = response.CaptchaCode
            if isinstance(captcha_code, int) and not isinstance(captcha_code, bool):
                return captcha_code == 1
            if isinstance(captcha_code, str):
                return captcha_code == '1'
            return False
        except Exception:
            self.degraded = True
            return None
