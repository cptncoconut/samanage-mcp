"""Catalog tools: categories, departments, sites, groups, solutions (CRUD)."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import SamanageError, client
from ..config import settings

logger = logging.getLogger(__name__)


# Map MCP resource plural -> JSON body singular key expected by Samanage.
_SINGULAR = {
    "categories": "category",
    "departments": "department",
    "sites": "site",
    "groups": "group",
    "solutions": "solution",
}


async def _list(resource: str, query: str | None, limit: int) -> dict[str, Any]:
    try:
        items = await client.list(resource, per_page=100)
    except SamanageError as exc:
        return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
    if query:
        q = query.strip().lower()
        items = [i for i in items if q in str(i.get("name", "")).lower()]
    items = items[: max(0, int(limit))]
    return {"resource": resource, "count": len(items), "items": items}


async def _get(resource: str, id: str | int) -> dict[str, Any]:
    try:
        resp = await client.get(resource, id=id)
    except SamanageError as exc:
        return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
    return {"resource": resource, "id": id, "item": resp}


async def _create(resource: str, name: str, extra: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if extra:
        payload.update(extra)
    if settings.samanage_dry_run:
        logger.warning("[DRY RUN] create %s payload: %s", resource, payload)
        return {"dry_run": True, "resource": resource, "payload": payload}
    try:
        resp = await client.post(resource, json={_SINGULAR[resource]: payload})
    except SamanageError as exc:
        return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
    return {"resource": resource, "item": resp}


async def _update(
    resource: str,
    id: str | int,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if not fields:
        return {"error": "nothing to update", "id": id}
    if settings.samanage_dry_run:
        logger.warning("[DRY RUN] update %s id=%s payload=%s", resource, id, fields)
        return {"dry_run": True, "resource": resource, "id": id, "payload": fields}
    try:
        resp = await client.put(resource, id=id, json={_SINGULAR[resource]: fields})
    except SamanageError as exc:
        return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
    return {"resource": resource, "id": id, "updated": fields, "response": resp}


async def _delete(resource: str, id: str | int) -> dict[str, Any]:
    if settings.samanage_dry_run:
        logger.warning("[DRY RUN] delete %s id=%s", resource, id)
        return {"dry_run": True, "resource": resource, "id": id}
    try:
        resp = await client.delete(resource, id=id)
    except SamanageError as exc:
        return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
    return {"resource": resource, "id": id, "deleted": True, "response": resp}


def register(mcp: FastMCP) -> None:
    # ---------- Categories ----------
    @mcp.tool()
    async def list_categories(query: str | None = None, limit: int = 200) -> dict[str, Any]:
        """List Samanage incident categories (subcategories are embedded in each)."""
        return await _list("categories", query, limit)

    @mcp.tool()
    async def get_category(id: str | int) -> dict[str, Any]:
        """Fetch a single category by id."""
        return await _get("categories", id)

    @mcp.tool()
    async def create_category(
        name: str, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create a category. Honors `SAMANAGE_DRY_RUN`."""
        return await _create("categories", name, extra)

    @mcp.tool()
    async def update_category(
        id: str | int,
        name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a category. Honors `SAMANAGE_DRY_RUN`."""
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if extra:
            fields.update(extra)
        return await _update("categories", id, fields)

    @mcp.tool()
    async def delete_category(id: str | int) -> dict[str, Any]:
        """Delete a category. Destructive; honors `SAMANAGE_DRY_RUN`."""
        return await _delete("categories", id)

    # ---------- Departments ----------
    @mcp.tool()
    async def list_departments(query: str | None = None, limit: int = 200) -> dict[str, Any]:
        """List Samanage departments."""
        return await _list("departments", query, limit)

    @mcp.tool()
    async def get_department(id: str | int) -> dict[str, Any]:
        return await _get("departments", id)

    @mcp.tool()
    async def create_department(
        name: str, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create a department. Honors `SAMANAGE_DRY_RUN`."""
        return await _create("departments", name, extra)

    @mcp.tool()
    async def update_department(
        id: str | int,
        name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a department. Honors `SAMANAGE_DRY_RUN`."""
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if extra:
            fields.update(extra)
        return await _update("departments", id, fields)

    @mcp.tool()
    async def delete_department(id: str | int) -> dict[str, Any]:
        """Delete a department. Destructive; honors `SAMANAGE_DRY_RUN`."""
        return await _delete("departments", id)

    # ---------- Sites ----------
    @mcp.tool()
    async def list_sites(query: str | None = None, limit: int = 200) -> dict[str, Any]:
        """List Samanage sites."""
        return await _list("sites", query, limit)

    @mcp.tool()
    async def get_site(id: str | int) -> dict[str, Any]:
        return await _get("sites", id)

    @mcp.tool()
    async def create_site(name: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a site. Honors `SAMANAGE_DRY_RUN`."""
        return await _create("sites", name, extra)

    @mcp.tool()
    async def update_site(
        id: str | int,
        name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a site. Honors `SAMANAGE_DRY_RUN`."""
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if extra:
            fields.update(extra)
        return await _update("sites", id, fields)

    @mcp.tool()
    async def delete_site(id: str | int) -> dict[str, Any]:
        """Delete a site. Destructive; honors `SAMANAGE_DRY_RUN`."""
        return await _delete("sites", id)

    # ---------- Groups ----------
    @mcp.tool()
    async def list_groups(query: str | None = None, limit: int = 200) -> dict[str, Any]:
        """List Samanage groups (for assignment + membership)."""
        return await _list("groups", query, limit)

    @mcp.tool()
    async def get_group(id: str | int) -> dict[str, Any]:
        return await _get("groups", id)

    @mcp.tool()
    async def create_group(name: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a group. Honors `SAMANAGE_DRY_RUN`."""
        return await _create("groups", name, extra)

    @mcp.tool()
    async def update_group(
        id: str | int,
        name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a group. Honors `SAMANAGE_DRY_RUN`."""
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if extra:
            fields.update(extra)
        return await _update("groups", id, fields)

    @mcp.tool()
    async def delete_group(id: str | int) -> dict[str, Any]:
        """Delete a group. Destructive; honors `SAMANAGE_DRY_RUN`."""
        return await _delete("groups", id)

    @mcp.tool()
    async def add_group_member(id: str | int, email: str) -> dict[str, Any]:
        """Add a user (by email) to a group. Honors `SAMANAGE_DRY_RUN`."""
        fields = {"memberships": [{"user": {"email": email}}]}
        return await _update("groups", id, fields)

    # ---------- Solutions ----------
    @mcp.tool()
    async def list_solutions(query: str | None = None, limit: int = 200) -> dict[str, Any]:
        """List Samanage knowledge-base solutions."""
        return await _list("solutions", query, limit)

    @mcp.tool()
    async def get_solution(id: str | int) -> dict[str, Any]:
        return await _get("solutions", id)

    @mcp.tool()
    async def create_solution(
        name: str,
        description: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a knowledge-base solution. Honors `SAMANAGE_DRY_RUN`."""
        payload: dict[str, Any] = {"name": name, "description": description}
        if extra:
            payload.update(extra)
        if settings.samanage_dry_run:
            logger.warning("[DRY RUN] create_solution payload: %s", payload)
            return {"dry_run": True, "payload": payload}
        try:
            resp = await client.post("solutions", json={"solution": payload})
        except SamanageError as exc:
            return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}
        return {"solution": resp}

    @mcp.tool()
    async def update_solution(
        id: str | int,
        name: str | None = None,
        description: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a solution. Honors `SAMANAGE_DRY_RUN`."""
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if description is not None:
            fields["description"] = description
        if extra:
            fields.update(extra)
        return await _update("solutions", id, fields)

    @mcp.tool()
    async def delete_solution(id: str | int) -> dict[str, Any]:
        """Delete a solution. Destructive; honors `SAMANAGE_DRY_RUN`."""
        return await _delete("solutions", id)
