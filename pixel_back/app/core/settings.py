from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _int(name: str, default: int, minimum: int = 0) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _csv(name: str) -> tuple[str, ...]:
    return tuple(
        item.strip().rstrip("/")
        for item in os.getenv(name, "").split(",")
        if item.strip()
    )


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    sql_echo: bool
    canvas_width: int
    canvas_height: int
    canvas_read_only: bool
    snapshot_directory: Path
    snapshot_threshold: int
    allowed_origins: tuple[str, ...]
    trust_proxy_headers: bool
    ws_max_message_bytes: int
    ws_send_timeout_seconds: float
    ws_connection_queue_size: int
    dispatcher_queue_size: int
    visitor_cookie_secret: str
    visitor_cookie_days: int
    admin_token_hash: str
    admin_session_secret: str
    admin_session_minutes: int
    abuse_mode: str
    ws_bucket_capacity: float
    ws_bucket_refill_per_second: float
    visitor_bucket_capacity: float
    visitor_bucket_refill_per_second: float
    ip_bucket_capacity: float
    ip_bucket_refill_per_second: float
    overwrite_bucket_capacity: float
    overwrite_refill_seconds: float
    verified_risk_window_minutes: int
    verified_risk_block_minutes: int
    tencent_secret_id: str
    tencent_secret_key: str
    tencent_captcha_app_id: str
    tencent_captcha_app_secret_key: str

    @property
    def canvas_size(self) -> int:
        return self.canvas_width * self.canvas_height

    @property
    def tencent_captcha_enabled(self) -> bool:
        return bool(
            self.tencent_secret_id
            and self.tencent_secret_key
            and self.tencent_captcha_app_id
            and self.tencent_captcha_app_secret_key
        )

    @classmethod
    def from_environment(cls) -> "Settings":
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        postgres_host = os.getenv("POSTGRES_HOST", "localhost")
        postgres_port = _int("POSTGRES_PORT", 5432, 1)
        postgres_user = os.getenv("POSTGRES_USER", "user")
        postgres_password = os.getenv("POSTGRES_PASSWORD", "password")
        postgres_db = os.getenv("POSTGRES_DB", "pixel_canvas")
        if app_env == "production" and postgres_password == "password":
            raise ValueError("POSTGRES_PASSWORD must be configured in production")

        snapshot_path = Path(os.getenv("SNAPSHOT_DIRECTORY", "snapshots"))
        if not snapshot_path.is_absolute():
            snapshot_path = BACKEND_ROOT / snapshot_path

        abuse_mode = os.getenv("ABUSE_MODE", "observe").strip().lower()
        if abuse_mode not in {"observe", "enforce"}:
            raise ValueError("ABUSE_MODE must be observe or enforce")

        database_url = os.getenv('DATABASE_URL', '').strip() or (
            "postgresql+asyncpg://"
            f"{quote_plus(postgres_user)}:{quote_plus(postgres_password)}"
            f"@{postgres_host}:{postgres_port}/{quote_plus(postgres_db)}"
        )
        visitor_cookie_secret = os.getenv('VISITOR_COOKIE_SECRET', '') or (
            'development-cookie-secret' if app_env != 'production' else ''
        )
        settings = cls(
            app_env=app_env,
            database_url=database_url,
            sql_echo=_bool("SQL_ECHO", False),
            canvas_width=_int("CANVAS_WIDTH", 1000, 1),
            canvas_height=_int("CANVAS_HEIGHT", 1000, 1),
            canvas_read_only=_bool("CANVAS_READ_ONLY", False),
            snapshot_directory=snapshot_path.resolve(),
            snapshot_threshold=_int("SNAPSHOT_THRESHOLD", 250, 1),
            allowed_origins=_csv("ALLOWED_ORIGINS"),
            trust_proxy_headers=_bool("TRUST_PROXY_HEADERS", False),
            ws_max_message_bytes=_int("WS_MAX_MESSAGE_BYTES", 4096, 256),
            ws_send_timeout_seconds=_float("WS_SEND_TIMEOUT_SECONDS", 2.0, 0.1),
            ws_connection_queue_size=_int("WS_CONNECTION_QUEUE_SIZE", 256, 1),
            dispatcher_queue_size=_int("DISPATCHER_QUEUE_SIZE", 10000, 1),
            visitor_cookie_secret=visitor_cookie_secret,
            visitor_cookie_days=_int("VISITOR_COOKIE_DAYS", 90, 1),
            admin_token_hash=os.getenv("ADMIN_TOKEN_HASH", ""),
            admin_session_secret=os.getenv("ADMIN_SESSION_SECRET", ""),
            admin_session_minutes=_int("ADMIN_SESSION_MINUTES", 30, 1),
            abuse_mode=abuse_mode,
            ws_bucket_capacity=_float("WS_BUCKET_CAPACITY", 40.0, 1.0),
            ws_bucket_refill_per_second=_float(
                "WS_BUCKET_REFILL_PER_SECOND", 10.0, 0.01
            ),
            visitor_bucket_capacity=_float("VISITOR_BUCKET_CAPACITY", 12.0, 1.0),
            visitor_bucket_refill_per_second=_float(
                "VISITOR_BUCKET_REFILL_PER_SECOND", 3.0, 0.01
            ),
            ip_bucket_capacity=_float("IP_BUCKET_CAPACITY", 120.0, 1.0),
            ip_bucket_refill_per_second=_float(
                "IP_BUCKET_REFILL_PER_SECOND", 30.0, 0.01
            ),
            overwrite_bucket_capacity=_float(
                "OVERWRITE_BUCKET_CAPACITY", 20.0, 1.0
            ),
            overwrite_refill_seconds=_float("OVERWRITE_REFILL_SECONDS", 15.0, 0.1),
            verified_risk_window_minutes=_int(
                "VERIFIED_RISK_WINDOW_MINUTES", 10, 1
            ),
            verified_risk_block_minutes=_int(
                "VERIFIED_RISK_BLOCK_MINUTES", 30, 1
            ),
            tencent_secret_id=os.getenv("TENCENT_SECRET_ID", ""),
            tencent_secret_key=os.getenv("TENCENT_SECRET_KEY", ""),
            tencent_captcha_app_id=os.getenv("TENCENT_CAPTCHA_APP_ID", ""),
            tencent_captcha_app_secret_key=os.getenv(
                "TENCENT_CAPTCHA_APP_SECRET_KEY", ""
            ),
        )
        if settings.app_env == "production" and not settings.visitor_cookie_secret:
            raise ValueError("VISITOR_COOKIE_SECRET must be configured in production")
        if settings.app_env == "production" and (
            not settings.admin_token_hash or not settings.admin_session_secret
        ):
            raise ValueError("ADMIN_TOKEN_HASH and ADMIN_SESSION_SECRET must be configured in production")
        return settings
