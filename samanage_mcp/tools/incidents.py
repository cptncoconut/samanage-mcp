"""Incident-related MCP tools (phase 2: parity with slackticketbot)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from ..attachments import AttachmentError, load_attachment
from ..client import SamanageError, client
from ..config import settings

logger = logging.getLogger(__name__)


def _assign_party(obj: dict[str, Any], key: str, identifier: str) -> None:
    """Set requester/assignee-shaped sub-object to either email or name."""
    sub = obj.setdefault(key, {})
    if "@" in identifier:
        sub["email"] = identifier
    else:
        sub["name"] = identifier


async def _attach_to_incident(incident_id: str | int, attachment: str) -> dict[str, Any]:
    """Attach a local file path or remote URL to an incident, gated by
    ``samanage_mcp.attachments`` safety checks (host allowlist, private-IP
    guard, size cap, mandatory `ATTACHMENT_ROOT` for local paths).

    Returns a status dict; never raises `AttachmentError` to the caller.
    """
    try:
        filename, content = await load_attachment(attachment)
    except AttachmentError as exc:
        return {"source": attachment, "ok": False, "error": f"attachment rejected: {exc}"}

    result = await client.upload_attachment(
        attachable_type="Incident",
        attachable_id=incident_id,
        filename=filename,
        content=content,
    )
    return {"source": attachment, "ok": True, "response": result}


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def create_incident(
        name: str,
        description: str,
        priority: str | None = None,
        category: str | None = None,
        subcategory: str | None = None,
        requester: str | None = None,
        assignee: str | None = None,
        state: str | None = None,
        attachments: list[str] | None = None,
        resolve_requester_from_text: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a Samanage incident.

        `requester` / `assignee` accept either an email or a display name; when
        `resolve_requester_from_text=True`, free-text names are mapped to a
        registered Samanage user via the cached users list. If `requester` is
        omitted and `SAMANAGE_DEFAULT_REQUESTER` is set, that email is used as a
        fallback. `extra` is merged into the `incident` payload for fields not
        covered by explicit args (custom fields, site, department, etc).
        """
        body: dict[str, Any] = {
            "name": name,
            "description": description,
            "category": (category or "Incident").title(),
            "subcategory": (subcategory or "Support").title(),
            "priority": (priority or "Medium").title(),
        }
        if state:
            body["state"] = state

        if requester:
            ident = requester
            if resolve_requester_from_text:
                resolved = await client.resolve_requester(candidate=requester)
                if resolved:
                    ident = resolved
            _assign_party(body, "requester", ident)
        elif settings.samanage_default_requester:
            body["requester"] = {"email": settings.samanage_default_requester}

        if assignee:
            ident = assignee
            if resolve_requester_from_text:
                resolved = await client.resolve_requester(candidate=assignee)
                if resolved:
                    ident = resolved
            _assign_party(body, "assignee", ident)

        if extra:
            body.update(extra)

        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] create_incident payload: %s", body)
            return {"dry_run": True, "incident": body}

        try:
            resp = await client.post("incidents", json={"incident": body})
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}

        incident: dict[str, Any] = {}
        if isinstance(resp, dict):
            maybe = resp.get("incident")
            incident = maybe if isinstance(maybe, dict) else resp
        incident_id = (
            incident.get("id") or incident.get("number") or incident.get("incident_number")
        )

        attach_results: list[dict[str, Any]] = []
        if attachments and incident_id is not None:
            for item in attachments:
                try:
                    attach_results.append(await _attach_to_incident(incident_id, item))
                except Exception as exc:  # pragma: no cover - defensive
                    attach_results.append({"source": item, "ok": False, "error": str(exc)})

        return {
            "id": incident_id,
            "incident": incident,
            "attachments": attach_results,
        }

    @mcp.tool()
    async def update_incident(
        id: str | int,
        note: str | None = None,
        state: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        close: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing incident: add a note/comment, change state, priority,
        or reassign. Pass `close=True` to set state to "Closed" (unless
        overridden via `state`)."""
        payload: dict[str, Any] = {}
        if note:
            payload.setdefault("comment", {})["body"] = note
        if priority:
            payload["priority"] = priority.title()
        if assignee:
            _assign_party(payload, "assignee", assignee)
        if state:
            payload["state"] = state
        elif close:
            payload["state"] = "Closed"
        if extra:
            payload.update(extra)

        if not payload:
            return {"error": "nothing to update", "id": id}

        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] update_incident id=%s payload=%s", id, payload)
            return {"dry_run": True, "id": id, "payload": payload}

        try:
            resp = await client.put("incidents", id=id, json={"incident": payload})
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"id": id, "updated": payload, "response": resp}

    @mcp.tool()
    async def summarize_incidents_this_month() -> dict[str, Any]:
        """Return total + per-state counts for incidents created this calendar month (UTC)."""
        if not client.configured:
            return {"error": "Samanage not configured"}
        now = datetime.now(timezone.utc)
        start_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        start_iso = start_month.isoformat().replace("+00:00", "Z")

        per_page = 100
        total = 0
        by_state: dict[str, int] = {}
        page = 1
        url = client._resource_url("incidents")  # noqa: SLF001 (internal use)
        async with httpx.AsyncClient(timeout=settings.list_timeout_seconds) as http:
            while True:
                resp = await http.get(
                    url,
                    headers=client._headers(),  # noqa: SLF001
                    params={"per_page": per_page, "page": page},
                )
                if resp.status_code != 200:
                    return {
                        "error": f"HTTP {resp.status_code}",
                        "body": resp.text[:500],
                    }
                try:
                    data = resp.json()
                except Exception:
                    return {"error": "bad JSON", "body": resp.text[:500]}
                if not isinstance(data, list):
                    return {"error": "unexpected body type", "type": str(type(data))}

                matched = 0
                all_older = True
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    created = (
                        item.get("created_at") or item.get("created") or item.get("created_on")
                    )
                    if not created:
                        continue
                    try:
                        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if dt.date() >= start_month.date():
                        total += 1
                        matched += 1
                        all_older = False
                        state_key = item.get("state") or item.get("status") or "UNKNOWN"
                        by_state[state_key] = by_state.get(state_key, 0) + 1

                if len(data) < per_page or all_older:
                    break
                page += 1

        return {"start_iso": start_iso, "total": total, "by_state": by_state}

    # -------------------------------------------------- phase 3 read-heavy ops

    @mcp.tool()
    async def list_incidents(
        state: list[str] | str | None = None,
        priority: list[str] | str | None = None,
        assignee: str | None = None,
        requester: str | None = None,
        name_contains: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        updated_days: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        per_page: int = 100,
        max_pages: int | None = 5,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """List Samanage incidents with common filters.

        Filters map to Samanage query params: `state[]`, `priority[]`,
        `assigned_to`, `requester`, `name.contains`, `created[]=[from,to]`,
        `updated` (days). Pass raw extra filters via `extra_params`.
        Defaults to at most 5 pages x 100 per page.
        """
        params: dict[str, Any] = {}
        if state:
            params["state[]"] = state if isinstance(state, list) else [state]
        if priority:
            params["priority[]"] = priority if isinstance(priority, list) else [priority]
        if assignee:
            params["assigned_to"] = assignee
        if requester:
            params["requester"] = requester
        if name_contains:
            params["name.contains"] = name_contains
        if created_from and created_to:
            params["created[]"] = [created_from, created_to]
        elif created_from:
            params["created_gt"] = created_from
        elif created_to:
            params["created_lt"] = created_to
        if updated_days is not None:
            params["updated"] = updated_days
        if sort_by:
            params["sort_by"] = sort_by
        if sort_order:
            params["sort_order"] = sort_order
        if extra_params:
            params.update(extra_params)

        try:
            items = await client.list(
                "incidents", params=params, per_page=per_page, max_pages=max_pages
            )
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"count": len(items), "incidents": items}

    @mcp.tool()
    async def get_incident(id: str | int) -> dict[str, Any]:
        """Fetch a single incident by id or number."""
        try:
            resp = await client.get("incidents", id=id)
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        if isinstance(resp, dict) and "incident" in resp:
            return resp
        return {"incident": resp}

    @mcp.tool()
    async def delete_incident(id: str | int) -> dict[str, Any]:
        """Delete an incident. Destructive; respects `SAMANAGE_DRY_RUN`."""
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] delete_incident id=%s", id)
            return {"dry_run": True, "id": id}
        try:
            resp = await client.delete("incidents", id=id)
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"id": id, "deleted": True, "response": resp}

    @mcp.tool()
    async def list_comments(incident_id: str | int) -> dict[str, Any]:
        """Return all comments on an incident."""
        try:
            items = await client.nested_list("incidents", incident_id, "comments")
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"incident_id": incident_id, "count": len(items), "comments": items}

    @mcp.tool()
    async def add_comment(
        incident_id: str | int,
        body: str,
        is_private: bool = False,
    ) -> dict[str, Any]:
        """Add a comment to an incident. `is_private` hides from requester when supported."""
        payload: dict[str, Any] = {"comment": {"body": body, "is_private": is_private}}
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] add_comment id=%s payload=%s", incident_id, payload)
            return {"dry_run": True, "incident_id": incident_id, "payload": payload}
        try:
            resp = await client.nested_post("incidents", incident_id, "comments", json=payload)
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"incident_id": incident_id, "response": resp}

    @mcp.tool()
    async def add_attachment_to_incident(
        incident_id: str | int,
        source: str,
    ) -> dict[str, Any]:
        """Attach a local file path or URL to an incident."""
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] add_attachment_to_incident id=%s source=%s", incident_id, source)
            return {"dry_run": True, "incident_id": incident_id, "source": source}
        try:
            return await _attach_to_incident(incident_id, source)
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        except AttachmentError as exc:
            return {"source": source, "ok": False, "error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive
            return {"source": source, "ok": False, "error": str(exc)}
