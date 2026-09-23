from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass

import redis.asyncio as redis

from app.core.config import Settings

_SESSION_PREFIX = "sess:"
_OAUTH_STATE_PREFIX = "oauth_state:"
_REVOKED_JTI_PREFIX = "revoked_jti:"


@dataclass(slots=True)
class SessionData:
    sub: str
    tenant_id: str
    access_token: str
    refresh_token: str
    id_token: str
    access_expires_at: float
    refresh_expires_at: float
    csrf_token: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "SessionData":
        return cls(**json.loads(raw))


class SessionStore:
    """Server-side session store for the BFF auth pattern (A4): the browser
    only ever holds an opaque session id cookie; access/refresh tokens never
    leave the backend. See docs/keycloak-setup.md."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def create(self, data: SessionData) -> str:
        session_id = secrets.token_urlsafe(32)
        await self._redis.set(
            _SESSION_PREFIX + session_id, data.to_json(), ex=self._settings.session_ttl_s
        )
        return session_id

    async def get(self, session_id: str) -> SessionData | None:
        raw = await self._redis.get(_SESSION_PREFIX + session_id)
        if raw is None:
            return None
        return SessionData.from_json(raw)

    async def update(self, session_id: str, data: SessionData) -> None:
        await self._redis.set(
            _SESSION_PREFIX + session_id, data.to_json(), ex=self._settings.session_ttl_s
        )

    async def revoke(self, session_id: str) -> None:
        await self._redis.delete(_SESSION_PREFIX + session_id)

    async def store_oauth_state(self, state: str, payload: dict[str, str], ttl_s: int = 600) -> None:
        await self._redis.set(_OAUTH_STATE_PREFIX + state, json.dumps(payload), ex=ttl_s)

    async def pop_oauth_state(self, state: str) -> dict[str, str] | None:
        key = _OAUTH_STATE_PREFIX + state
        raw = await self._redis.get(key)
        if raw is None:
            return None
        await self._redis.delete(key)
        return json.loads(raw)

    async def revoke_jti(self, jti: str, exp: int) -> None:
        ttl = max(1, int(exp - time.time()))
        await self._redis.set(_REVOKED_JTI_PREFIX + jti, "1", ex=ttl)

    async def is_jti_revoked(self, jti: str) -> bool:
        return await self._redis.exists(_REVOKED_JTI_PREFIX + jti) == 1
