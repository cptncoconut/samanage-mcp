"""Response-template tools.

Samanage response templates (aka canned responses) are prewritten text blocks
agents can insert into an incident comment. The API endpoint is not publicly
documented; the default path is `/response_templates.json` and can be
overridden via `SAMANAGE_RESPONSE_TEMPLATE_RESOURCE` if your tenant exposes
it under a different name.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import SamanageError, client
from ..config import settings

logger = logging.getLogger(__name__)


def _resource() -> str:
    return settings.samanage_response_template_resource


def _wrap(payload: dict[str, Any]) -> dict[str, Any]:
    return {settings.samanage_response_template_singular: payload}


def _slim(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        # some tenants name it `body`, others `content` or `description`
        "body": item.get("body") or item.get("content") or item.get("description"),
    }


def _extract_body(template: dict[str, Any]) -> str | None:
    """Pull the template body regardless of which field name Samanage uses."""
    if not isinstance(template, dict):
        return None
    nested = template.get(settings.samanage_response_template_singular)
    src = nested if isinstance(nested, dict) else template
    body = src.get("body") or src.get("content") or src.get("description")
    return body if isinstance(body, str) else None


async def _find_by_name(name: str) -> dict[str, Any] | None:
    try:
        items = await client.list(_resource(), per_page=100)
    except SamanageError:
        return None
    target = name.strip().lower()
    for item in items:
        if str(item.get("name", "")).strip().lower() == target:
            return item
    return None


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_response_templates(
        query: str | None = None,
        limit: int = 200,
        full: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """List Samanage response (canned) templates. Optional `query` filters
        by name substring (client-side). Returns a slim view by default;
        pass `full=True` for raw records."""
        try:
            items = await client.list(_resource(), params=filters, per_page=100)
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}

        if query:
            q = query.strip().lower()
            items = [i for i in items if q in str(i.get("name", "")).lower()]
        items = items[: max(0, int(limit))]
        return {
            "count": len(items),
            "templates": items if full else [_slim(i) for i in items],
        }

    @mcp.tool()
    async def get_response_template(
        id: str | int | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a single response template by id or by exact name (case-insensitive)."""
        if id is None and not name:
            return {"error": "specify either id or name"}
        try:
            if id is not None:
                resp = await client.get(_resource(), id=id)
                return {"template": resp}
            found = await _find_by_name(str(name))
            if not found:
                return {"found": False, "name": name}
            return {"found": True, "template": found}
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}

    @mcp.tool()
    async def create_response_template(
        name: str,
        body: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a response template. `body` is the canned text.
        Honors `SAMANAGE_DRY_RUN`."""
        payload: dict[str, Any] = {"name": name, "body": body}
        if extra:
            payload.update(extra)
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] create_response_template payload: %s", payload)
            return {"dry_run": True, "payload": payload}
        try:
            resp = await client.post(_resource(), json=_wrap(payload))
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"template": resp}

    @mcp.tool()
    async def update_response_template(
        id: str | int,
        name: str | None = None,
        body: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a response template by id. Only provided fields are changed.
        Honors `SAMANAGE_DRY_RUN`."""
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if body is not None:
            fields["body"] = body
        if extra:
            fields.update(extra)
        if not fields:
            return {"error": "nothing to update", "id": id}
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] update_response_template id=%s payload=%s", id, fields)
            return {"dry_run": True, "id": id, "payload": fields}
        try:
            resp = await client.put(_resource(), id=id, json=_wrap(fields))
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"id": id, "updated": fields, "response": resp}

    @mcp.tool()
    async def delete_response_template(id: str | int) -> dict[str, Any]:
        """Delete a response template. Destructive; honors `SAMANAGE_DRY_RUN`."""
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] delete_response_template id=%s", id)
            return {"dry_run": True, "id": id}
        try:
            resp = await client.delete(_resource(), id=id)
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"id": id, "deleted": True, "response": resp}

    @mcp.tool()
    async def apply_response_template_to_incident(
        incident_id: str | int,
        template_id: str | int | None = None,
        template_name: str | None = None,
        is_private: bool = False,
        append_text: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a response template (by id or name) and post its body as a
        comment on the incident. Optionally append extra text. Respects
        `SAMANAGE_DRY_RUN`."""
        if template_id is None and not template_name:
            return {"error": "specify either template_id or template_name"}
        try:
            if template_id is not None:
                resp = await client.get(_resource(), id=template_id)
                template = resp
            else:
                found = await _find_by_name(str(template_name))
                if not found:
                    return {"error": f"template named {template_name!r} not found"}
                template = found
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}

        body = _extract_body(template if isinstance(template, dict) else {})
        if not body:
            return {"error": "template has no body/content/description field", "template": template}
        if append_text:
            body = f"{body}\n\n{append_text}"

        payload = {"comment": {"body": body, "is_private": is_private}}
        if settings.samanage_dry_run:
            logger.warning(
                "[DRY RUN] apply_response_template_to_incident id=%s payload=%s",
                incident_id,
                payload,
            )
            return {"dry_run": True, "incident_id": incident_id, "payload": payload}

        try:
            resp = await client.nested_post("incidents", incident_id, "comments", json=payload)
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"incident_id": incident_id, "template": _slim(template if isinstance(template, dict) else {}), "response": resp}
