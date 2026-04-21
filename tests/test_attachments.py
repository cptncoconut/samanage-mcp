"""Tests for attachment safety guards (SSRF, path traversal, size caps)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import httpx
import pytest
import respx

from samanage_mcp import attachments as att
from samanage_mcp.attachments import (
    AttachmentError,
    fetch_url_bytes,
    load_attachment,
    read_local_path_bytes,
)
from samanage_mcp.config import settings


@pytest.fixture(autouse=True)
def _restore_attachment_settings() -> None:
    """Snapshot + restore attachment-related settings per test."""
    keys = [
        "attachment_max_bytes",
        "attachment_url_allowed_hosts",
        "attachment_allow_private_ips",
        "attachment_max_redirects",
        "attachment_allow_local_paths",
        "attachment_root",
    ]
    snap = {k: getattr(settings, k) for k in keys}
    yield
    for k, v in snap.items():
        setattr(settings, k, v)


# ------------------------------------------------------------- URL guards


@respx.mock
async def test_fetch_url_allowed_host_public_ip() -> None:
    respx.get("https://api.samanage.com/file.png").mock(
        return_value=httpx.Response(200, content=b"\x89PNG")
    )
    with mock.patch.object(att, "_resolve_host_ips", return_value=["8.8.8.8"]):
        fname, content = await fetch_url_bytes("https://api.samanage.com/file.png")
    assert fname == "file.png"
    assert content == b"\x89PNG"


async def test_fetch_url_rejects_disallowed_host() -> None:
    with pytest.raises(AttachmentError, match="not in the attachment allowlist"):
        await fetch_url_bytes("https://evil.example.com/f.png")


async def test_fetch_url_rejects_private_ip() -> None:
    with mock.patch.object(att, "_resolve_host_ips", return_value=["127.0.0.1"]):
        with pytest.raises(AttachmentError, match="disallowed address"):
            await fetch_url_bytes("https://api.samanage.com/f.png")


async def test_fetch_url_rejects_link_local_metadata() -> None:
    """Cloud instance-metadata service — the classic SSRF target."""
    with mock.patch.object(att, "_resolve_host_ips", return_value=["169.254.169.254"]):
        with pytest.raises(AttachmentError, match="disallowed address"):
            await fetch_url_bytes("https://api.samanage.com/f.png")


async def test_fetch_url_rejects_non_http_scheme() -> None:
    with pytest.raises(AttachmentError, match="unsupported URL scheme"):
        await fetch_url_bytes("file:///etc/passwd")


@respx.mock
async def test_fetch_url_follows_allowed_redirect() -> None:
    respx.get("https://api.samanage.com/a").mock(
        return_value=httpx.Response(302, headers={"location": "https://api.samanage.com/b"})
    )
    respx.get("https://api.samanage.com/b").mock(
        return_value=httpx.Response(200, content=b"ok")
    )
    with mock.patch.object(att, "_resolve_host_ips", return_value=["8.8.8.8"]):
        fname, content = await fetch_url_bytes("https://api.samanage.com/a")
    assert content == b"ok"
    assert fname == "b"


@respx.mock
async def test_fetch_url_rejects_redirect_to_disallowed_host() -> None:
    respx.get("https://api.samanage.com/a").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example.com/x"})
    )
    with mock.patch.object(att, "_resolve_host_ips", return_value=["8.8.8.8"]):
        with pytest.raises(AttachmentError, match="not in the attachment allowlist"):
            await fetch_url_bytes("https://api.samanage.com/a")


@respx.mock
async def test_fetch_url_redirect_cap() -> None:
    settings.attachment_max_redirects = 1
    respx.get("https://api.samanage.com/a").mock(
        return_value=httpx.Response(302, headers={"location": "https://api.samanage.com/b"})
    )
    respx.get("https://api.samanage.com/b").mock(
        return_value=httpx.Response(302, headers={"location": "https://api.samanage.com/c"})
    )
    with mock.patch.object(att, "_resolve_host_ips", return_value=["8.8.8.8"]):
        with pytest.raises(AttachmentError, match="too many redirects"):
            await fetch_url_bytes("https://api.samanage.com/a")


@respx.mock
async def test_fetch_url_size_cap_content_length() -> None:
    settings.attachment_max_bytes = 10
    respx.get("https://api.samanage.com/big.bin").mock(
        return_value=httpx.Response(
            200, headers={"content-length": "100"}, content=b"x" * 100
        )
    )
    with mock.patch.object(att, "_resolve_host_ips", return_value=["8.8.8.8"]):
        with pytest.raises(AttachmentError, match="content-length"):
            await fetch_url_bytes("https://api.samanage.com/big.bin")


@respx.mock
async def test_fetch_url_size_cap_streamed() -> None:
    settings.attachment_max_bytes = 5

    async def _chunked_stream():
        yield b"x" * 100

    respx.get("https://api.samanage.com/big.bin").mock(
        return_value=httpx.Response(
            200,
            headers={"transfer-encoding": "chunked"},
            stream=_chunked_stream(),
        )
    )
    with mock.patch.object(att, "_resolve_host_ips", return_value=["8.8.8.8"]):
        with pytest.raises(AttachmentError, match="exceeded cap"):
            await fetch_url_bytes("https://api.samanage.com/big.bin")


async def test_fetch_url_host_allowlist_extends() -> None:
    settings.attachment_url_allowed_hosts = "trusted.example.com"
    with mock.patch.object(att, "_resolve_host_ips", return_value=["8.8.8.8"]):
        # Only checks the safe-URL path, no network call needed.
        await att._assert_url_is_safe("https://trusted.example.com/x")


# ------------------------------------------------------------- local path


def test_local_path_disabled_by_default() -> None:
    with pytest.raises(AttachmentError, match="disabled"):
        read_local_path_bytes("/etc/hosts")


def test_local_path_requires_root(tmp_path: Path) -> None:
    settings.attachment_allow_local_paths = True
    settings.attachment_root = ""
    with pytest.raises(AttachmentError, match="ATTACHMENT_ROOT is required"):
        read_local_path_bytes(str(tmp_path / "x.txt"))


def test_local_path_rejects_outside_root(tmp_path: Path) -> None:
    settings.attachment_allow_local_paths = True
    root = tmp_path / "allowed"
    root.mkdir()
    settings.attachment_root = str(root)

    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"hi")
    with pytest.raises(AttachmentError, match="outside ATTACHMENT_ROOT"):
        read_local_path_bytes(str(outside))


def test_local_path_reads_allowed_file(tmp_path: Path) -> None:
    settings.attachment_allow_local_paths = True
    root = tmp_path / "allowed"
    root.mkdir()
    settings.attachment_root = str(root)
    target = root / "ok.txt"
    target.write_bytes(b"hello")

    fname, content = read_local_path_bytes(str(target))
    assert fname == "ok.txt"
    assert content == b"hello"


def test_local_path_size_cap(tmp_path: Path) -> None:
    settings.attachment_allow_local_paths = True
    root = tmp_path / "allowed"
    root.mkdir()
    settings.attachment_root = str(root)
    settings.attachment_max_bytes = 4
    target = root / "big.bin"
    target.write_bytes(b"x" * 100)

    with pytest.raises(AttachmentError, match="exceeds cap"):
        read_local_path_bytes(str(target))


# ------------------------------------------------------------- dispatcher


@respx.mock
async def test_load_attachment_dispatches_url() -> None:
    respx.get("https://api.samanage.com/a.png").mock(
        return_value=httpx.Response(200, content=b"ok")
    )
    with mock.patch.object(att, "_resolve_host_ips", return_value=["8.8.8.8"]):
        fname, content = await load_attachment("https://api.samanage.com/a.png")
    assert fname == "a.png"
    assert content == b"ok"


async def test_load_attachment_dispatches_local_path_disabled() -> None:
    with pytest.raises(AttachmentError, match="disabled"):
        await load_attachment("/etc/hosts")
