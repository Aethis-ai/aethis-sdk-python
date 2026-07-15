"""Real self-serve key acquisition on staging, the way a user acquires one.

The staging integration lane does not read a pre-minted key from a secret; it
mints one through the same public path a developer does — Clerk sign-in ticket →
frontend-API JWT → ``POST /api/v1/keys/`` — then tears it down. This is what
makes scope-set drift between the mint surface and the engine visible (the
day-one 403 that triggered workspace#477).

Secrets are never logged. The JWT, sign-in ticket and full key are treated as
opaque and never printed. Every network call is bounded by a timeout so a wedged
dependency fails loud rather than hanging (no-interactive-blocking rule).

Env inputs (all with sane defaults except the two credentials):

- ``CLERK_SECRET_KEY_DEV_TOOLS``  — Clerk Backend-API key for the dev-tools app.
- ``CLERK_E2E_DX_USER_ID``        — the fenced e2e user to mint sign-in tickets for.
- ``AETHIS_STAGING_BASE_URL``     — engine base (default ``https://staging.api.aethis.ai``).
- ``CLERK_FRONTEND_API_URL``      — Clerk frontend API (default ``https://clerk.aethis.ai``).
- ``CLERK_SIGN_IN_ORIGIN``        — Origin header for the browser-mode exchange
                                     (default ``https://aethis.ai``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

KEY_NAME_PREFIX = "e2e-dx-sdk-"
_HTTP_TIMEOUT = 30.0
# Stray keys older than this from an earlier crashed run get swept.
_STALE_AFTER = timedelta(hours=1)


class MintUnavailable(RuntimeError):
    """The mint path could not be exercised (missing creds, unreachable Clerk /
    engine, wedged exchange). Raised so the lane fails **loud**, never skips
    (Decision 9)."""


@dataclass(frozen=True)
class StagingConfig:
    base_url: str
    clerk_frontend_url: str
    clerk_secret_key: str
    e2e_user_id: str
    sign_in_origin: str

    @classmethod
    def from_env(cls) -> "StagingConfig":
        secret = os.environ.get("CLERK_SECRET_KEY_DEV_TOOLS")
        user_id = os.environ.get("CLERK_E2E_DX_USER_ID")
        missing = [
            name
            for name, val in (
                ("CLERK_SECRET_KEY_DEV_TOOLS", secret),
                ("CLERK_E2E_DX_USER_ID", user_id),
            )
            if not val
        ]
        if missing:
            raise MintUnavailable("staging lane requires " + ", ".join(missing) + " — refusing to skip (Decision 9)")
        assert secret and user_id  # for type-checkers
        return cls(
            base_url=os.environ.get("AETHIS_STAGING_BASE_URL", "https://staging.api.aethis.ai").rstrip("/"),
            clerk_frontend_url=os.environ.get("CLERK_FRONTEND_API_URL", "https://clerk.aethis.ai").rstrip("/"),
            clerk_secret_key=secret,
            e2e_user_id=user_id,
            sign_in_origin=os.environ.get("CLERK_SIGN_IN_ORIGIN", "https://aethis.ai"),
        )


def _clerk_jwt(cfg: StagingConfig) -> str:
    """Mint a session JWT for the fenced e2e user via the two-step Clerk flow."""
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        try:
            tok_resp = client.post(
                "https://api.clerk.com/v1/sign_in_tokens",
                headers={"Authorization": f"Bearer {cfg.clerk_secret_key}"},
                json={"user_id": cfg.e2e_user_id, "expires_in_seconds": 600},
            )
        except httpx.HTTPError as e:  # pragma: no cover - network failure path
            raise MintUnavailable(f"Clerk sign-in-token request failed: {e}") from e
        if tok_resp.status_code != 200:
            raise MintUnavailable(f"Clerk sign-in-token returned {tok_resp.status_code}")
        ticket = tok_resp.json().get("token")
        if not ticket:
            raise MintUnavailable("Clerk sign-in-token response carried no token")

        # Browser-mode exchange: form-encoded, cookie jar, Origin set, no _is_native.
        try:
            exch = client.post(
                f"{cfg.clerk_frontend_url}/v1/client/sign_ins",
                headers={
                    "Origin": cfg.sign_in_origin,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"strategy": "ticket", "ticket": ticket},
            )
        except httpx.HTTPError as e:  # pragma: no cover
            raise MintUnavailable(f"Clerk sign-in exchange failed: {e}") from e
        if exch.status_code not in (200, 201):
            raise MintUnavailable(f"Clerk sign-in exchange returned {exch.status_code}")
        try:
            jwt = exch.json()["client"]["sessions"][0]["last_active_token"]["jwt"]
        except (KeyError, IndexError, TypeError) as e:
            raise MintUnavailable("Clerk sign-in exchange response missing session JWT") from e
        if not jwt:
            raise MintUnavailable("Clerk sign-in exchange returned an empty JWT")
        return jwt


@dataclass
class MintedKey:
    full_key: str
    key_id: str
    scopes: list[str]


class KeyMinter:
    """Session-scoped mint/teardown helper. Tracks every key it creates and
    revokes them (plus stale strays) on :meth:`teardown`."""

    def __init__(self, cfg: StagingConfig) -> None:
        self._cfg = cfg
        self._jwt = _clerk_jwt(cfg)
        self._minted: list[str] = []

    def mint(self, name_suffix: str, scopes: list[str] | None = None) -> MintedKey:
        name = f"{KEY_NAME_PREFIX}{name_suffix}"
        body: dict[str, object] = {"name": name}
        if scopes is not None:
            body["scopes"] = scopes
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(
                f"{self._cfg.base_url}/api/v1/keys/",
                headers={"Authorization": f"Bearer {self._jwt}"},
                json=body,
            )
        if resp.status_code not in (200, 201):
            raise MintUnavailable(f"key mint returned {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        key_id = data.get("key_id")
        full_key = data.get("full_key")
        if not key_id or not full_key:
            raise MintUnavailable("key mint response missing key_id / full_key")
        self._minted.append(key_id)
        return MintedKey(full_key=full_key, key_id=key_id, scopes=data.get("scopes") or [])

    def _delete(self, client: httpx.Client, key_id: str) -> None:
        try:
            client.delete(
                f"{self._cfg.base_url}/api/v1/keys/{key_id}",
                headers={"Authorization": f"Bearer {self._jwt}"},
            )
        except httpx.HTTPError:  # pragma: no cover - best-effort teardown
            pass

    def teardown(self) -> None:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            for key_id in self._minted:
                self._delete(client, key_id)
            self._sweep_stale(client)

    def _sweep_stale(self, client: httpx.Client) -> None:
        """Revoke any leftover ``e2e-dx-sdk-*`` key from a crashed earlier run."""
        try:
            resp = client.get(
                f"{self._cfg.base_url}/api/v1/keys/",
                headers={"Authorization": f"Bearer {self._jwt}"},
            )
        except httpx.HTTPError:  # pragma: no cover
            return
        if resp.status_code != 200:
            return
        cutoff = datetime.now(timezone.utc) - _STALE_AFTER
        for item in resp.json():
            name = item.get("name") or ""
            if not name.startswith(KEY_NAME_PREFIX) or item.get("revoked"):
                continue
            created = _parse_ts(item.get("created_at"))
            if created is None or created < cutoff:
                self._delete(client, item.get("key_id", ""))


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
