from __future__ import annotations

import base64
import hashlib
import secrets
import time
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.security.jwt import Principal, TokenValidationError, TokenValidator
from app.security.sessions import SessionData, SessionStore

REFRESH_SKEW_S = 60


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(40))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class OidcClient:
    """Authorization-code + PKCE flow against Keycloak, token exchange, and
    refresh -- the "backend for frontend" half of A4. The browser never sees
    an access or refresh token; only an opaque session cookie."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._validator = TokenValidator(settings)

    @property
    def _authorize_endpoint(self) -> str:
        return (
            f"{self._settings.keycloak_public_url}/realms/{self._settings.keycloak_realm}"
            "/protocol/openid-connect/auth"
        )

    @property
    def _token_endpoint(self) -> str:
        return (
            f"{self._settings.keycloak_base_url}/realms/{self._settings.keycloak_realm}"
            "/protocol/openid-connect/token"
        )

    @property
    def _logout_endpoint(self) -> str:
        return (
            f"{self._settings.keycloak_public_url}/realms/{self._settings.keycloak_realm}"
            "/protocol/openid-connect/logout"
        )

    def build_authorize_url(
        self, redirect_uri: str, state: str, nonce: str, code_challenge: str, *, acr_values: str | None = None
    ) -> str:
        params = {
            "client_id": self._settings.keycloak_client_id,
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if acr_values:
            params["acr_values"] = acr_values
            params["prompt"] = "login"
        return f"{self._authorize_endpoint}?{httpx.QueryParams(params)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                self._token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._settings.keycloak_client_id,
                    "client_secret": self._settings.keycloak_client_secret,
                    "code_verifier": code_verifier,
                },
            )
        resp.raise_for_status()
        return resp.json()

    async def refresh(self, refresh_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                self._token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self._settings.keycloak_client_id,
                    "client_secret": self._settings.keycloak_client_secret,
                },
            )
        resp.raise_for_status()
        return resp.json()

    def validate_access_token(self, access_token: str) -> Principal:
        return self._validator.validate(access_token)

    def rp_initiated_logout_url(self, id_token_hint: str, post_logout_redirect_uri: str) -> str:
        params = {
            "id_token_hint": id_token_hint,
            "post_logout_redirect_uri": post_logout_redirect_uri,
            "client_id": self._settings.keycloak_client_id,
        }
        return f"{self._logout_endpoint}?{httpx.QueryParams(params)}"


async def tokens_to_session_data(token_response: dict) -> SessionData:
    now = time.time()
    return SessionData(
        sub="",  # filled by caller after validating the access token
        tenant_id="",
        access_token=token_response["access_token"],
        refresh_token=token_response.get("refresh_token", ""),
        id_token=token_response.get("id_token", ""),
        access_expires_at=now + float(token_response.get("expires_in", 300)),
        refresh_expires_at=now + float(token_response.get("refresh_expires_in", 1800)),
        csrf_token=secrets.token_urlsafe(24),
    )


async def resolve_principal_with_refresh(
    oidc: OidcClient, store: SessionStore, session_id: str, data: SessionData
) -> tuple[Principal, SessionData]:
    """Returns a validated Principal for the session, transparently
    refreshing the access token first if it's within REFRESH_SKEW_S of
    expiry. Raises TokenValidationError if the session cannot be revived."""
    if data.access_expires_at - time.time() < REFRESH_SKEW_S:
        if data.refresh_expires_at < time.time():
            raise TokenValidationError("Refresh token expired; re-login required")
        token_response = await oidc.refresh(data.refresh_token)
        new_data = await tokens_to_session_data(token_response)
        new_data.csrf_token = data.csrf_token
        principal = oidc.validate_access_token(new_data.access_token)
        new_data.sub = principal.sub
        new_data.tenant_id = str(principal.tenant_id)
        await store.update(session_id, new_data)
        return principal, new_data

    principal = oidc.validate_access_token(data.access_token)
    return principal, data


__all__ = [
    "OidcClient",
    "generate_pkce_pair",
    "resolve_principal_with_refresh",
    "tokens_to_session_data",
    "uuid4",
]
