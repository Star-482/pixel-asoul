from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    type: str
    request_id: str | None
    data: dict


class ProtocolError(ValueError):
    pass


def parse_message(raw: str, max_bytes: int) -> IncomingMessage:
    if len(raw.encode('utf-8')) > max_bytes:
        raise ProtocolError('message_too_large')
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProtocolError('invalid_json') from error
    if not isinstance(payload, dict) or not isinstance(payload.get('type'), str):
        raise ProtocolError('invalid_message')
    data = payload.get('data', {})
    if not isinstance(data, dict):
        raise ProtocolError('invalid_message')
    request_id = payload.get('request_id')
    if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 64):
        raise ProtocolError('invalid_request_id')
    return IncomingMessage(payload['type'], request_id, data)


def error_payload(
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    retry_after: int | None = None,
) -> dict:
    data: dict[str, object] = {'code': code, 'message': message, 'retryable': code in {'rate_limited', 'destructive_cooldown'}}
    if retry_after is not None:
        data['retry_after'] = retry_after
    payload: dict[str, object] = {'type': 'error', 'data': data}
    if request_id:
        payload['request_id'] = request_id
    return payload
