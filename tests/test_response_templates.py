"""Tests for response-template tools."""

from __future__ import annotations

from typing import Any

import httpx
import pytest  # noqa: F401
import respx

from samanage_mcp.config import settings
from samanage_mcp.server import mcp


async def _call(tool_name: str, **args: Any) -> dict[str, Any]:
    contents, structured = await mcp.call_tool(tool_name, args)
    assert isinstance(structured, dict), f"expected dict from {tool_name}, got {structured!r}"
    return structured


# -------------------------------------------------------------- dry-run writes


async def test_create_response_template_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("create_response_template", name="Greeting", body="Hello!")
    assert out["dry_run"] is True
    assert out["payload"] == {"name": "Greeting", "body": "Hello!"}


async def test_update_response_template_nothing_to_update() -> None:
    out = await _call("update_response_template", id=1)
    assert out["error"] == "nothing to update"


async def test_update_response_template_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("update_response_template", id=3, body="Updated body")
    assert out["dry_run"] is True
    assert out["id"] == 3
    assert out["payload"] == {"body": "Updated body"}


async def test_delete_response_template_dry_run() -> None:
    settings.samanage_dry_run = True
    out = await _call("delete_response_template", id=9)
    assert out == {"dry_run": True, "id": 9}


async def test_apply_template_requires_id_or_name() -> None:
    out = await _call("apply_response_template_to_incident", incident_id=1)
    assert "specify either" in out["error"]


# -------------------------------------------------------------- live-ish calls


@respx.mock
async def test_list_response_templates_slim_view() -> None:
    respx.get("https://api.samanage.com/response_templates.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "Greeting", "body": "Hello!"},
                {"id": 2, "name": "Farewell", "body": "Goodbye!"},
            ],
        )
    )
    out = await _call("list_response_templates", query="greet")
    assert out["count"] == 1
    assert out["templates"][0] == {"id": 1, "name": "Greeting", "body": "Hello!"}


@respx.mock
async def test_list_response_templates_respects_custom_path() -> None:
    # Pretend the tenant exposes them under /comment_templates
    settings.samanage_response_template_resource = "comment_templates"
    try:
        respx.get("https://api.samanage.com/comment_templates.json").mock(
            return_value=httpx.Response(200, json=[{"id": 42, "name": "X", "body": "y"}])
        )
        out = await _call("list_response_templates")
        assert out["count"] == 1
        assert out["templates"][0]["id"] == 42
    finally:
        settings.samanage_response_template_resource = "response_templates"


@respx.mock
async def test_create_response_template_live_wraps_singular() -> None:
    settings.samanage_dry_run = False
    route = respx.post("https://api.samanage.com/response_templates.json").mock(
        return_value=httpx.Response(201, json={"id": 11, "name": "N", "body": "b"})
    )
    out = await _call("create_response_template", name="N", body="b")
    assert out["template"]["id"] == 11
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent == {"response_template": {"name": "N", "body": "b"}}


@respx.mock
async def test_apply_template_by_name_posts_comment() -> None:
    settings.samanage_dry_run = False
    respx.get("https://api.samanage.com/response_templates.json").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "name": "Reboot notice", "body": "Please reboot."}]
        )
    )
    comment_route = respx.post(
        "https://api.samanage.com/incidents/77/comments.json"
    ).mock(return_value=httpx.Response(201, json={"id": "c1"}))
    out = await _call(
        "apply_response_template_to_incident",
        incident_id=77,
        template_name="Reboot notice",
        append_text="Ping us if issue persists.",
    )
    assert out["incident_id"] == 77
    assert comment_route.called
    import json as _json

    sent = _json.loads(comment_route.calls.last.request.content)
    assert sent["comment"]["body"].startswith("Please reboot.")
    assert "Ping us if issue persists." in sent["comment"]["body"]


@respx.mock
async def test_apply_template_template_not_found() -> None:
    settings.samanage_dry_run = False
    respx.get("https://api.samanage.com/response_templates.json").mock(
        return_value=httpx.Response(200, json=[])
    )
    out = await _call(
        "apply_response_template_to_incident",
        incident_id=1,
        template_name="Nope",
    )
    assert "not found" in out["error"]


async def test_tool_registration() -> None:
    names = {t.name for t in await mcp.list_tools()}
    for expected in (
        "list_response_templates",
        "get_response_template",
        "create_response_template",
        "update_response_template",
        "delete_response_template",
        "apply_response_template_to_incident",
    ):
        assert expected in names, f"{expected} not registered"
