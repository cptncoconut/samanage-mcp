"""Async httpx-based Samanage / SWSD API client.

Centralizes auth, URL building, pagination, and the small number of helpers
(user cache + requester resolution) ported from the original slackticketbot.
Tool modules should depend on this client and stay thin.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

import httpx
from httpx import HTTPStatusError

from .config import settings

logger = logging.getLogger(__name__)


class SamanageError(RuntimeError):
    """Raised for non-2xx Samanage responses."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class SamanageClient:
    """Thin async wrapper around the Samanage REST API.

    All resource paths are expressed as `"incidents"`, `"users"`, etc. The
    client appends `.json` and builds the full URL from `settings.samanage_base_url`.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_token: str | None = None,
        default_timeout: float | None = None,
        list_timeout: float | None = None,
        users_cache_ttl_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.samanage_base_url or "").rstrip("/")
        self.api_token = api_token or settings.samanage_api_token or ""
        self.default_timeout = (
            default_timeout if default_timeout is not None else settings.http_timeout_seconds
        )
        self.list_timeout = (
            list_timeout if list_timeout is not None else settings.list_timeout_seconds
        )
        self._users_cache_ttl = (
            users_cache_ttl_seconds
            if users_cache_ttl_seconds is not None
            else settings.users_cache_ttl_seconds
        )
        self._users_cache: list[dict[str, Any]] = []
        self._users_cache_ts: float | None = None

    # ---------------------------------------------------------------- helpers

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_token)

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {
            "X-Samanage-Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _resource_url(self, resource: str, *, id: str | int | None = None) -> str:
        resource = resource.strip("/")
        if id is None:
            return f"{self.base_url}/{resource}.json"
        return f"{self.base_url}/{resource}/{id}.json"

    def _require_configured(self) -> None:
        if not self.configured:
            raise SamanageError(
                "Samanage API not configured: set SAMANAGE_API_TOKEN and SAMANAGE_BASE_URL."
            )

    # ------------------------------------------------------------- core verbs

    async def get(
        self,
        resource: str,
        *,
        id: str | int | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self._require_configured()
        url = self._resource_url(resource, id=id)
        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
            return self._parse(resp)

    async def post(self, resource: str, *, json: dict[str, Any]) -> Any:
        self._require_configured()
        url = self._resource_url(resource)
        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            resp = await client.post(url, headers=self._headers(json_body=True), json=json)
            return self._parse(resp)

    async def put(
        self,
        resource: str,
        *,
        id: str | int,
        json: dict[str, Any],
    ) -> Any:
        self._require_configured()
        url = self._resource_url(resource, id=id)
        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            resp = await client.put(url, headers=self._headers(json_body=True), json=json)
            return self._parse(resp)

    async def delete(self, resource: str, *, id: str | int) -> Any:
        self._require_configured()
        url = self._resource_url(resource, id=id)
        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            resp = await client.delete(url, headers=self._headers())
            if resp.status_code in (200, 202, 204):
                return True
            return self._parse(resp)

    async def list(
        self,
        resource: str,
        *,
        params: dict[str, Any] | None = None,
        per_page: int = 100,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a list resource until an empty/short page is seen."""
        self._require_configured()
        url = self._resource_url(resource)
        out: list[dict[str, Any]] = []
        page = 1
        async with httpx.AsyncClient(timeout=self.list_timeout) as client:
            while True:
                page_params: dict[str, Any] = {"per_page": per_page, "page": page}
                if params:
                    page_params.update(params)
                resp = await client.get(url, headers=self._headers(), params=page_params)
                batch = self._parse_list(resp)
                if not batch:
                    break
                out.extend(batch)
                if len(batch) < per_page:
                    break
                page += 1
                if max_pages is not None and page > max_pages:
                    break
        return out

    # ------------------------------------------------------- nested resources

    def _nested_url(self, parent: str, parent_id: str | int, sub: str) -> str:
        parent = parent.strip("/")
        sub = sub.strip("/")
        return f"{self.base_url}/{parent}/{parent_id}/{sub}.json"

    async def nested_get(
        self,
        parent: str,
        parent_id: str | int,
        sub: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self._require_configured()
        url = self._nested_url(parent, parent_id, sub)
        async with httpx.AsyncClient(timeout=self.default_timeout) as http:
            resp = await http.get(url, headers=self._headers(), params=params)
            return self._parse(resp)

    async def nested_list(
        self,
        parent: str,
        parent_id: str | int,
        sub: str,
        *,
        params: dict[str, Any] | None = None,
        per_page: int = 100,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        self._require_configured()
        url = self._nested_url(parent, parent_id, sub)
        out: list[dict[str, Any]] = []
        page = 1
        async with httpx.AsyncClient(timeout=self.list_timeout) as http:
            while True:
                page_params: dict[str, Any] = {"per_page": per_page, "page": page}
                if params:
                    page_params.update(params)
                resp = await http.get(url, headers=self._headers(), params=page_params)
                batch = self._parse_list(resp)
                if not batch:
                    break
                out.extend(batch)
                if len(batch) < per_page:
                    break
                page += 1
                if max_pages is not None and page > max_pages:
                    break
        return out

    async def nested_post(
        self,
        parent: str,
        parent_id: str | int,
        sub: str,
        *,
        json: dict[str, Any],
    ) -> Any:
        self._require_configured()
        url = self._nested_url(parent, parent_id, sub)
        async with httpx.AsyncClient(timeout=self.default_timeout) as http:
            resp = await http.post(url, headers=self._headers(json_body=True), json=json)
            return self._parse(resp)

    async def upload_attachment(
        self,
        *,
        attachable_type: str,
        attachable_id: str | int,
        filename: str,
        content: bytes,
    ) -> Any:
        """Upload a file as a Samanage attachment bound to `attachable_type`/`id`."""
        self._require_configured()
        url = f"{self.base_url}/attachments.json"
        files = {"file[attachment]": (filename, content)}
        data = {
            "file[attachable_type]": attachable_type,
            "file[attachable_id]": str(attachable_id),
        }
        headers = {
            "X-Samanage-Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.default_timeout) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            return self._parse(resp)

    # --------------------------------------------------------- response parse

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        try:
            resp.raise_for_status()
        except HTTPStatusError as exc:
            try:
                body: Any = exc.response.json()
            except Exception:
                body = exc.response.text
            raise SamanageError(
                f"Samanage HTTP {exc.response.status_code}: {body!r}",
                status_code=exc.response.status_code,
                body=body,
            ) from exc
        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text

    @staticmethod
    def _parse_list(resp: httpx.Response) -> list[dict[str, Any]]:
        data = SamanageClient._parse(resp)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            # Some endpoints wrap the list under a single key
            for v in data.values():
                if isinstance(v, list):
                    return [item for item in v if isinstance(item, dict)]
        return []

    # ----------------------------------------------------- users cache & resolve

    async def fetch_users(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Return cached Samanage users, refreshing on TTL expiry."""
        if not self.configured:
            return []
        now = time.time()
        if (
            not force_refresh
            and self._users_cache_ts is not None
            and (now - self._users_cache_ts) < self._users_cache_ttl
        ):
            return self._users_cache
        try:
            users = await self.list("users", per_page=100)
        except SamanageError as exc:
            logger.warning("fetch_users error: %s", exc)
            return self._users_cache  # keep stale on error
        self._users_cache = users
        self._users_cache_ts = now
        return users

    async def resolve_requester(
        self,
        *,
        candidate: str | None,
        fallback: str | None = None,
    ) -> str | None:
        """Best-effort map of a free-text name/email to a Samanage user's email or name.

        Returns the user's email when available, else the user's display name,
        else None so the caller can fall back to a configured default.
        """
        candidate = (candidate or "").strip()
        fallback = (fallback or "").strip()
        users = await self.fetch_users()
        if not users:
            return None

        def _norm(s: str) -> str:
            return s.strip().lower()

        cand_norm = _norm(candidate) if candidate else ""

        def _pick(u: dict[str, Any], default: str | None) -> str | None:
            return u.get("email") or u.get("name") or default

        # Exact-match email first
        if "@" in candidate:
            for u in users:
                if _norm(str(u.get("email", ""))) == cand_norm:
                    return _pick(u, candidate)

        # Exact match on display name
        if cand_norm:
            for u in users:
                if _norm(str(u.get("name", ""))) == cand_norm:
                    return _pick(u, candidate)

        # Derived username tokens matched against email local-part
        tokens: list[str] = []
        if cand_norm:
            parts = [p for p in cand_norm.split() if p]
            if parts:
                first = parts[0]
                last = parts[-1] if len(parts) > 1 else ""
                tokens.append(first)
                if last:
                    tokens.extend([last, f"{first}.{last}", f"{first}{last}", f"{first[0]}{last}"])

        if tokens:
            for u in users:
                email_raw = str(u.get("email", ""))
                if "@" not in email_raw:
                    continue
                local = email_raw.split("@", 1)[0].lower()
                if any(tok and tok in local for tok in tokens):
                    return _pick(u, candidate)

        # Loose substring on name/email
        if cand_norm:
            for u in users:
                name = _norm(str(u.get("name", "")))
                email = _norm(str(u.get("email", "")))
                if (name and cand_norm in name) or (email and cand_norm in email):
                    return _pick(u, candidate)

        # Fallback candidate
        if fallback:
            fb = _norm(fallback)
            for u in users:
                if _norm(str(u.get("name", ""))) == fb or _norm(str(u.get("email", ""))) == fb:
                    return _pick(u, fallback)

        return None


# Shared default client for tools/servers to import.
client = SamanageClient()


def reset_client(**kwargs: Any) -> SamanageClient:
    """Reconfigure the module-level client in-place.

    Tool modules import `client` by reference at module load time, so this
    function mutates the existing instance's attributes rather than rebinding
    the name.
    """
    fresh = SamanageClient(**kwargs)
    client.__dict__.clear()
    client.__dict__.update(fresh.__dict__)
    return client


__all__: Iterable[str] = ("SamanageClient", "SamanageError", "client", "reset_client")
