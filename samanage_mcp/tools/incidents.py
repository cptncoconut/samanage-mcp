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


def _as_list(value: list[str] | str | None) -> list[str] | None:
    if value is None:
        return None
    return value if isinstance(value, list) else [value]


def _build_incident_filters(
    *,
    state: list[str] | str | None = None,
    priority: list[str] | str | None = None,
    assignee: list[str] | str | None = None,
    requester: list[str] | str | None = None,
    category: list[str] | str | None = None,
    site: list[str] | str | None = None,
    department: list[str] | str | None = None,
    group: list[str] | str | None = None,
    name_contains: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    updated_days: int | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> dict[str, Any]:
    """Translate ergonomic tool args into Samanage's query-string conventions."""
    params: dict[str, Any] = {}
    array_fields = {
        "state[]": _as_list(state),
        "priority[]": _as_list(priority),
        "assignee[]": _as_list(assignee),
        "requester[]": _as_list(requester),
        "category[]": _as_list(category),
        "site[]": _as_list(site),
        "department[]": _as_list(department),
        "group[]": _as_list(group),
    }
    for key, val in array_fields.items():
        if val:
            params[key] = val
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
    return params


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


def _matches_party(
    incident: dict[str, Any],
    field: str,
    values: list[str] | None,
) -> bool:
    """Return True if the incident's assignee/requester matches any of *values*.

    Matches are case-insensitive against both `email` and `name` sub-fields.
    When *values* is None/empty the check is skipped (returns True).
    """
    if not values:
        return True
    party = incident.get(field)
    if not party or not isinstance(party, dict):
        return False
    email = str(party.get("email") or "").lower()
    name = str(party.get("name") or "").lower()
    for v in values:
        v_lower = v.lower()
        if v_lower in email or v_lower in name:
            return True
    return False


_SLIM_DROP = {
    "description", "description_no_html",
    "releases", "problems", "problem", "incidents", "changes", "tasks",
    "time_tracks", "solutions", "assets", "mobiles", "other_assets",
    "configuration_items", "discovery_hardwares", "purchase_orders",
    "sla_violations", "custom_fields_values", "cc",
}


def _slim_incident(item: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *item* with large/unused fields removed."""
    return {k: v for k, v in item.items() if k not in _SLIM_DROP}


def _client_filter(
    items: list[dict[str, Any]],
    *,
    name_contains: str | None,
    assignee: list[str] | str | None,
    requester: list[str] | str | None,
) -> list[dict[str, Any]]:
    """Apply filters that the Samanage API does not reliably honour server-side."""
    assignee_list = _as_list(assignee)
    requester_list = _as_list(requester)
    name_lower = name_contains.lower() if name_contains else None

    result = []
    for item in items:
        if name_lower and name_lower not in str(item.get("name") or "").lower():
            continue
        if not _matches_party(item, "assignee", assignee_list):
            continue
        if not _matches_party(item, "requester", requester_list):
            continue
        result.append(item)
    return result


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
        if isinstance(resp, dict):
            resp = _slim_incident(resp)
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
        assignee: list[str] | str | None = None,
        requester: list[str] | str | None = None,
        category: list[str] | str | None = None,
        site: list[str] | str | None = None,
        department: list[str] | str | None = None,
        group: list[str] | str | None = None,
        name_contains: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        updated_days: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        per_page: int = 100,
        max_pages: int | None = 5,
        filters: dict[str, Any] | None = None,
        slim: bool = True,
    ) -> dict[str, Any]:
        """List Samanage incidents with filters.

        Named filter args map to Samanage's array-valued query keys:
          state[], priority[], assignee[], requester[], category[], site[],
          department[], group[], created[]=[from,to], updated (days),
          name.contains, sort_by, sort_order.

        For anything else — custom fields, additional filters your tenant
        supports, etc. — pass a `filters` dict whose keys are sent verbatim
        as query params. Examples:
          {"priority[]": ["High", "Critical"]}
          {"My Custom Field": "Some Value"}
          {"tags[]": "vip"}

        `slim=True` (default) strips large unused fields (description, cc, etc.)
        to keep responses compact. Pass `slim=False` for the full raw record.

        Samanage only honors filters when the versioned Accept header is sent;
        this server sets `application/vnd.samanage.v2.1+json` by default.
        """
        params: dict[str, Any] = _build_incident_filters(
            state=state,
            priority=priority,
            assignee=assignee,
            requester=requester,
            category=category,
            site=site,
            department=department,
            group=group,
            name_contains=name_contains,
            created_from=created_from,
            created_to=created_to,
            updated_days=updated_days,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        if filters:
            params.update(filters)

        try:
            items = await client.list(
                "incidents", params=params, per_page=per_page, max_pages=max_pages
            )
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}

        # The Samanage API silently ignores several filter params (name.contains,
        # assignee[], requester[]). Apply these client-side after fetching.
        items = _client_filter(
            items,
            name_contains=name_contains,
            assignee=assignee,
            requester=requester,
        )
        if slim:
            items = [_slim_incident(i) for i in items]
        return {"count": len(items), "incidents": items, "applied_filters": params}

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
