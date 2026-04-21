"""Unit tests for SamanageClient (httpx mocked via respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from samanage_mcp.client import SamanageClient, SamanageError


@pytest.fixture
def cli() -> SamanageClient:
    return SamanageClient(
        base_url="https://api.samanage.com",
        api_token="test-token",
        users_cache_ttl_seconds=0,  # disable cache for tests
    )


@respx.mock
async def test_get_parses_json(cli: SamanageClient) -> None:
    respx.get("https://api.samanage.com/incidents/42.json").mock(
        return_value=httpx.Response(200, json={"incident": {"id": 42, "name": "x"}})
    )
    resp = await cli.get("incidents", id=42)
    assert resp == {"incident": {"id": 42, "name": "x"}}


@respx.mock
async def test_post_put_delete(cli: SamanageClient) -> None:
    respx.post("https://api.samanage.com/incidents.json").mock(
        return_value=httpx.Response(201, json={"id": 7})
    )
    respx.put("https://api.samanage.com/incidents/7.json").mock(
        return_value=httpx.Response(200, json={"id": 7, "state": "Closed"})
    )
    respx.delete("https://api.samanage.com/incidents/7.json").mock(
        return_value=httpx.Response(204)
    )
    created = await cli.post("incidents", json={"incident": {"name": "n"}})
    assert created == {"id": 7}
    updated = await cli.put("incidents", id=7, json={"incident": {"state": "Closed"}})
    assert updated["state"] == "Closed"
    assert await cli.delete("incidents", id=7) is True


@respx.mock
async def test_list_paginates_until_short_page(cli: SamanageClient) -> None:
    full_page = [{"id": i} for i in range(100)]
    short_page = [{"id": 100}]
    respx.get("https://api.samanage.com/incidents.json").mock(
        side_effect=[
            httpx.Response(200, json=full_page),
            httpx.Response(200, json=short_page),
        ]
    )
    items = await cli.list("incidents", per_page=100)
    assert len(items) == 101


@respx.mock
async def test_list_stops_on_empty_page(cli: SamanageClient) -> None:
    respx.get("https://api.samanage.com/users.json").mock(
        side_effect=[
            httpx.Response(200, json=[{"id": 1}]),
            httpx.Response(200, json=[]),
        ]
    )
    items = await cli.list("users", per_page=1)
    assert items == [{"id": 1}]


@respx.mock
async def test_list_respects_max_pages(cli: SamanageClient) -> None:
    page = [{"id": i} for i in range(2)]
    respx.get("https://api.samanage.com/incidents.json").mock(
        return_value=httpx.Response(200, json=page)
    )
    items = await cli.list("incidents", per_page=2, max_pages=3)
    assert len(items) == 6  # 3 pages x 2 items


@respx.mock
async def test_http_error_raises(cli: SamanageClient) -> None:
    respx.get("https://api.samanage.com/incidents/999.json").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    with pytest.raises(SamanageError) as excinfo:
        await cli.get("incidents", id=999)
    assert excinfo.value.status_code == 404


@respx.mock
async def test_nested_post(cli: SamanageClient) -> None:
    respx.post("https://api.samanage.com/incidents/12/comments.json").mock(
        return_value=httpx.Response(201, json={"id": "c1"})
    )
    resp = await cli.nested_post("incidents", 12, "comments", json={"comment": {"body": "hi"}})
    assert resp == {"id": "c1"}


@respx.mock
async def test_nested_list_paginates(cli: SamanageClient) -> None:
    respx.get("https://api.samanage.com/incidents/12/comments.json").mock(
        side_effect=[
            httpx.Response(200, json=[{"id": "a"}, {"id": "b"}]),
            httpx.Response(200, json=[]),
        ]
    )
    items = await cli.nested_list("incidents", 12, "comments", per_page=2)
    assert {i["id"] for i in items} == {"a", "b"}


@respx.mock
async def test_resolve_requester_exact_name(cli: SamanageClient) -> None:
    respx.get("https://api.samanage.com/users.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"name": "Alice Example", "email": "alice@example.com"},
                {"name": "Bob Sample", "email": "bob@example.com"},
            ],
        )
    )
    resolved = await cli.resolve_requester(candidate="Alice Example")
    assert resolved == "alice@example.com"


@respx.mock
async def test_resolve_requester_token_match(cli: SamanageClient) -> None:
    respx.get("https://api.samanage.com/users.json").mock(
        return_value=httpx.Response(
            200,
            json=[{"name": "", "email": "jdoe@example.com"}],
        )
    )
    resolved = await cli.resolve_requester(candidate="John Doe")
    assert resolved == "jdoe@example.com"


@respx.mock
async def test_resolve_requester_no_match(cli: SamanageClient) -> None:
    respx.get("https://api.samanage.com/users.json").mock(
        return_value=httpx.Response(200, json=[{"name": "Other", "email": "other@example.com"}])
    )
    resolved = await cli.resolve_requester(candidate="Nobody Here")
    assert resolved is None


async def test_unconfigured_client_raises() -> None:
    bare = SamanageClient(base_url="", api_token="")
    with pytest.raises(SamanageError):
        await bare.get("incidents", id=1)


@respx.mock
async def test_upload_attachment_posts_multipart(cli: SamanageClient) -> None:
    route = respx.post("https://api.samanage.com/attachments.json").mock(
        return_value=httpx.Response(200, json={"id": "att1"})
    )
    resp = await cli.upload_attachment(
        attachable_type="Incident",
        attachable_id=12,
        filename="a.txt",
        content=b"hello",
    )
    assert resp == {"id": "att1"}
    assert route.called
    sent = route.calls.last.request
    body = sent.content.decode("utf-8", errors="replace")
    assert "Incident" in body
    assert "12" in body
    assert "a.txt" in body
