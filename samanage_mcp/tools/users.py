"""User-related MCP tools."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import SamanageError, client
from ..config import settings

logger = logging.getLogger(__name__)


def _slim(user: dict[str, Any]) -> dict[str, Any]:
    """Return a compact view of a user record for LLM consumption."""
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": (user.get("role") or {}).get("name") if isinstance(user.get("role"), dict) else user.get("role"),
        "disabled": user.get("disabled"),
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_users(
        query: str | None = None,
        limit: int = 50,
        full: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """List Samanage users.

        - `query` is a client-side case-insensitive substring filter against
          name or email.
        - `filters` is a dict of query params sent verbatim to Samanage for
          server-side filtering (e.g. `{"role[]": "Administrator"}` or
          `{"department[]": "IT"}`; custom-field names may also be used).

        Returns a compact view by default; pass `full=True` for raw records.
        """
        try:
            if filters:
                # filtered list bypasses the users cache since cache is
                # keyed on "no filter"
                users = await client.list("users", params=filters, per_page=100)
            else:
                users = await client.fetch_users()
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code}

        if query:
            q = query.strip().lower()
            users = [
                u
                for u in users
                if q in str(u.get("name", "")).lower() or q in str(u.get("email", "")).lower()
            ]

        users = users[: max(0, int(limit))]
        return {
            "count": len(users),
            "users": users if full else [_slim(u) for u in users],
        }

    @mcp.tool()
    async def find_user_by_email(email: str) -> dict[str, Any]:
        """Return the first Samanage user whose email matches (case-insensitive)."""
        try:
            users = await client.fetch_users()
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code}

        target = email.strip().lower()
        for u in users:
            if str(u.get("email", "")).strip().lower() == target:
                return {"found": True, "user": u}
        return {"found": False, "email": email}

    @mcp.tool()
    async def resolve_user(candidate: str, fallback: str | None = None) -> dict[str, Any]:
        """Best-effort map a free-text name or email to a Samanage user.

        Returns the resolved email/name when a user matches, else None."""
        resolved = await client.resolve_requester(candidate=candidate, fallback=fallback)
        return {"candidate": candidate, "resolved": resolved}

    # ----------------------------------------------------------- write tools

    @mcp.tool()
    async def create_user(
        name: str,
        email: str,
        role: str | None = None,
        department: str | None = None,
        site: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Samanage user. `role` may be a role name; `department`/`site` are names.
        Raw overrides can be merged via `extra`. Honors `SAMANAGE_DRY_RUN`."""
        payload: dict[str, Any] = {"name": name, "email": email}
        if role:
            payload["role"] = {"name": role}
        if department:
            payload["department"] = {"name": department}
        if site:
            payload["site"] = {"name": site}
        if extra:
            payload.update(extra)
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] create_user payload: %s", payload)
            return {"dry_run": True, "user": payload}
        try:
            resp = await client.post("users", json={"user": payload})
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"user": resp}

    @mcp.tool()
    async def update_user(
        id: str | int,
        name: str | None = None,
        email: str | None = None,
        role: str | None = None,
        disabled: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a Samanage user by id. Honors `SAMANAGE_DRY_RUN`."""
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if email is not None:
            payload["email"] = email
        if role is not None:
            payload["role"] = {"name": role}
        if disabled is not None:
            payload["disabled"] = disabled
        if extra:
            payload.update(extra)
        if not payload:
            return {"error": "nothing to update", "id": id}
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] update_user id=%s payload=%s", id, payload)
            return {"dry_run": True, "id": id, "payload": payload}
        try:
            resp = await client.put("users", id=id, json={"user": payload})
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"id": id, "updated": payload, "response": resp}

    @mcp.tool()
    async def delete_user(id: str | int) -> dict[str, Any]:
        """Delete a Samanage user. Destructive; honors `SAMANAGE_DRY_RUN`."""
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] delete_user id=%s", id)
            return {"dry_run": True, "id": id}
        try:
            resp = await client.delete("users", id=id)
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"id": id, "deleted": True, "response": resp}
