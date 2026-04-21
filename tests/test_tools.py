"""End-to-end MCP tool tests (call_tool returns (contents, structured))."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from samanage_mcp.config import settings
from samanage_mcp.server import mcp


async def _call(tool_name: str, **args: Any) -> dict[str, Any]:
    contents, structured = await mcp.call_tool(tool_name, args)
    assert isinstance(structured, dict), f"expected dict from {tool_name}, got {structured!r}"
    return structured


# --------------------------------------------------------- dry-run write tools


async def test_create_incident_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call(
        "create_incident",
        name="wifi down",
        description="site A offline",
        priority="high",
        requester="user@example.com",
    )
    assert out["dry_run"] is True
    inc = out["incident"]
    assert inc["name"] == "wifi down"
    assert inc["priority"] == "High"
    assert inc["requester"] == {"email": "user@example.com"}


async def test_create_incident_uses_default_requester() -> None:
    settings.samanage_dry_run = True
    settings.samanage_default_requester = "fallback@example.com"
    out = await _call("create_incident", name="n", description="d")
    assert out["incident"]["requester"] == {"email": "fallback@example.com"}


async def test_update_incident_dry_run_close() -> None:
    settings.samanage_dry_run = True
    out = await _call("update_incident", id=42, note="fixed", close=True)
    assert out["dry_run"] is True
    assert out["id"] == 42
    assert out["payload"]["state"] == "Closed"
    assert out["payload"]["comment"]["body"] == "fixed"


async def test_update_incident_nothing_to_update() -> None:
    out = await _call("update_incident", id=1)
    assert out["error"] == "nothing to update"


async def test_delete_incident_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("delete_incident", id=7)
    assert out == {"dry_run": True, "id": 7}


async def test_add_comment_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("add_comment", incident_id=5, body="note", is_private=True)
    assert out["dry_run"] is True
    assert out["payload"]["comment"] == {"body": "note", "is_private": True}


async def test_add_attachment_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("add_attachment_to_incident", incident_id=5, source="/tmp/x.png")
    assert out == {"dry_run": True, "incident_id": 5, "source": "/tmp/x.png"}


# ---------------------------------------------------------------- live-ish tools


@respx.mock
async def test_create_incident_live() -> None:
    settings.samanage_dry_run = False
    respx.post("https://api.samanage.com/incidents.json").mock(
        return_value=httpx.Response(201, json={"incident": {"id": 99, "name": "n"}})
    )
    out = await _call("create_incident", name="n", description="d")
    assert out["id"] == 99
    assert out["incident"]["id"] == 99


@respx.mock
async def test_list_incidents_builds_filters() -> None:
    settings.samanage_dry_run = False
    route = respx.get("https://api.samanage.com/incidents.json").mock(
        return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    )
    out = await _call(
        "list_incidents",
        state=["Active", "New"],
        priority="High",
        name_contains="wifi",
        max_pages=1,
    )
    assert out["count"] == 2
    req = route.calls.last.request
    qs = req.url.params
    assert qs.get_list("state[]") == ["Active", "New"]
    assert qs.get_list("priority[]") == ["High"]
    assert qs["name.contains"] == "wifi"


@respx.mock
async def test_list_users_filters_and_slims() -> None:
    respx.get("https://api.samanage.com/users.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "Alice", "email": "alice@example.com", "role": {"name": "Admin"}},
                {"id": 2, "name": "Bob", "email": "bob@example.com"},
            ],
        )
    )
    out = await _call("list_users", query="alice")
    assert out["count"] == 1
    assert out["users"][0]["role"] == "Admin"
    assert "raw_json" not in out["users"][0]  # slim view


@respx.mock
async def test_find_user_by_email_not_found() -> None:
    respx.get("https://api.samanage.com/users.json").mock(
        return_value=httpx.Response(200, json=[{"name": "Other", "email": "other@example.com"}])
    )
    out = await _call("find_user_by_email", email="nope@example.com")
    assert out == {"found": False, "email": "nope@example.com"}


@respx.mock
async def test_list_categories_name_filter() -> None:
    respx.get("https://api.samanage.com/categories.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "Network"},
                {"id": 2, "name": "Hardware"},
            ],
        )
    )
    out = await _call("list_categories", query="net")
    assert out["count"] == 1
    assert out["items"][0]["name"] == "Network"


@respx.mock
async def test_list_comments_paginates() -> None:
    respx.get("https://api.samanage.com/incidents/3/comments.json").mock(
        side_effect=[
            httpx.Response(200, json=[{"id": "a"}]),
            httpx.Response(200, json=[]),
        ]
    )
    out = await _call("list_comments", incident_id=3)
    assert out["count"] == 1


@respx.mock
async def test_http_error_surfaced_as_error_dict() -> None:
    respx.get("https://api.samanage.com/incidents/404.json").mock(
        return_value=httpx.Response(404, json={"error": "missing"})
    )
    out = await _call("get_incident", id=404)
    assert out["status_code"] == 404
    assert "missing" in str(out.get("body"))


# ------------------------------------------------------------- write tools


async def test_create_user_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call(
        "create_user",
        name="Jane Doe",
        email="jane@example.com",
        role="Admin",
        department="IT",
        site="HQ",
    )
    assert out["dry_run"] is True
    user = out["user"]
    assert user["email"] == "jane@example.com"
    assert user["role"] == {"name": "Admin"}
    assert user["department"] == {"name": "IT"}
    assert user["site"] == {"name": "HQ"}


@respx.mock
async def test_create_user_live() -> None:
    settings.samanage_dry_run = False
    route = respx.post("https://api.samanage.com/users.json").mock(
        return_value=httpx.Response(201, json={"id": 501, "email": "jane@example.com"})
    )
    out = await _call("create_user", name="Jane", email="jane@example.com")
    assert route.called
    assert out["user"]["id"] == 501


async def test_update_user_nothing_to_update() -> None:
    out = await _call("update_user", id=1)
    assert out["error"] == "nothing to update"


async def test_delete_user_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("delete_user", id=11)
    assert out == {"dry_run": True, "id": 11}


async def test_create_category_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("create_category", name="Network")
    assert out["dry_run"] is True
    assert out["resource"] == "categories"
    assert out["payload"]["name"] == "Network"


async def test_update_site_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("update_site", id=42, name="HQ-2")
    assert out["dry_run"] is True
    assert out["resource"] == "sites"
    assert out["payload"] == {"name": "HQ-2"}


async def test_delete_department_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("delete_department", id=3)
    assert out == {"dry_run": True, "resource": "departments", "id": 3}


@respx.mock
async def test_create_group_live_sends_singular_key() -> None:
    settings.samanage_dry_run = False
    route = respx.post("https://api.samanage.com/groups.json").mock(
        return_value=httpx.Response(201, json={"id": 77, "name": "Ops"})
    )
    out = await _call("create_group", name="Ops")
    assert out["item"]["id"] == 77
    import json as _json

    body = _json.loads(route.calls.last.request.content)
    assert body == {"group": {"name": "Ops"}}


async def test_add_group_member_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("add_group_member", id=5, email="jane@example.com")
    assert out["dry_run"] is True
    assert out["payload"] == {"memberships": [{"user": {"email": "jane@example.com"}}]}


async def test_create_solution_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("create_solution", name="KB1", description="steps")
    assert out["dry_run"] is True
    assert out["payload"] == {"name": "KB1", "description": "steps"}


# ---------------------------------------------------- registration matrix


@pytest.mark.parametrize(
    "tool_name",
    [
        # incidents
        "create_incident",
        "update_incident",
        "summarize_incidents_this_month",
        "list_incidents",
        "get_incident",
        "delete_incident",
        "list_comments",
        "add_comment",
        "add_attachment_to_incident",
        # users
        "list_users",
        "find_user_by_email",
        "resolve_user",
        "create_user",
        "update_user",
        "delete_user",
        # catalog
        "list_categories",
        "get_category",
        "create_category",
        "update_category",
        "delete_category",
        "list_departments",
        "get_department",
        "create_department",
        "update_department",
        "delete_department",
        "list_sites",
        "get_site",
        "create_site",
        "update_site",
        "delete_site",
        "list_groups",
        "get_group",
        "create_group",
        "update_group",
        "delete_group",
        "add_group_member",
        "list_solutions",
        "get_solution",
        "create_solution",
        "update_solution",
        "delete_solution",
    ],
)
async def test_tool_registered(tool_name: str) -> None:
    tools = await mcp.list_tools()
    assert tool_name in {t.name for t in tools}
