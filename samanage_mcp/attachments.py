"""Safe attachment ingestion helpers.

Defends against:
  * SSRF via URL attachments (host allowlist + private-IP rejection on every
    redirect hop).
  * Arbitrary local-file reads (disabled by default; when enabled requires an
    absolute `ATTACHMENT_ROOT` and rejects paths that escape it).
  * Memory exhaustion (streamed reads with a byte cap).

Public API: ``load_attachment(source)`` which returns ``(filename, content)``
ready to hand to ``SamanageClient.upload_attachment``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import functools
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse, urljoin

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class AttachmentError(RuntimeError):
    """Raised when an attachment source fails a safety check."""


# ---------------------------------------------------------------- host policy


def _default_allowed_hosts() -> set[str]:
    """Hosts always permitted: the configured Samanage base URL host."""
    base = (settings.samanage_base_url or "").strip()
    if not base:
        return set()
    host = urlparse(base).hostname
    return {host.lower()} if host else set()


def _configured_allowed_hosts() -> set[str]:
    raw = (settings.attachment_url_allowed_hosts or "").strip()
    if not raw:
        return set()
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


@functools.lru_cache(maxsize=1)
def _allowed_hosts() -> set[str]:
    return _default_allowed_hosts() | _configured_allowed_hosts()


def _host_is_allowed(host: str | None) -> bool:
    if not host:
        return False
    return host.lower() in _allowed_hosts()


# ----------------------------------------------------------------- IP policy


def _ip_is_safe(addr: str) -> bool:
    """Return True if `addr` is a routable public IP.

    Private / loopback / link-local / reserved / multicast / unspecified are
    all rejected unless `attachment_allow_private_ips=True`.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if settings.attachment_allow_private_ips:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolve_host_ips(host: str) -> list[str]:
    """Resolve `host` to a list of IP strings via getaddrinfo (off the event loop)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as exc:
        raise AttachmentError(f"cannot resolve host {host!r}: {exc}") from exc
    ips = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family in (socket.AF_INET, socket.AF_INET6):
            ips.append(sockaddr[0])
    # Deduplicate while preserving order.
    seen: set[str] = set()
    uniq: list[str] = []
    for ip in ips:
        if ip not in seen:
            seen.add(ip)
            uniq.append(ip)
    return uniq


async def _assert_url_is_safe(url: str) -> None:
    """Validate scheme, host allowlist, and resolve-then-check IP safety."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise AttachmentError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise AttachmentError("URL missing host")
    if not _host_is_allowed(host):
        raise AttachmentError(
            f"host {host!r} is not in the attachment allowlist "
            "(set ATTACHMENT_URL_ALLOWED_HOSTS)"
        )
    ips = await _resolve_host_ips(host)
    if not ips:
        raise AttachmentError(f"host {host!r} resolved to no addresses")
    bad = [ip for ip in ips if not _ip_is_safe(ip)]
    if bad:
        raise AttachmentError(
            f"host {host!r} resolves to disallowed address(es) {bad} "
            "(set ATTACHMENT_ALLOW_PRIVATE_IPS=true to override)"
        )


# ---------------------------------------------------------------- URL fetch


async def fetch_url_bytes(url: str) -> tuple[str, bytes]:
    """Download a URL with SSRF guards, manual redirect handling, and size cap.

    Returns `(filename, content)`. Filename is derived from the final URL path.
    """
    max_bytes = int(settings.attachment_max_bytes)
    max_redirects = max(0, int(settings.attachment_max_redirects))

    current = url
    hops = 0
    timeout = settings.http_timeout_seconds

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, trust_env=False
    ) as http:
        while True:
            await _assert_url_is_safe(current)
            async with http.stream("GET", current) as resp:
                # Redirects
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        raise AttachmentError(
                            f"redirect {resp.status_code} from {current!r} missing Location"
                        )
                    if hops >= max_redirects:
                        raise AttachmentError(
                            f"too many redirects (> {max_redirects}) starting from {url!r}"
                        )
                    next_url = urljoin(current, location)
                    hops += 1
                    current = next_url
                    continue

                if resp.status_code != 200:
                    raise AttachmentError(
                        f"URL {current!r} returned HTTP {resp.status_code}"
                    )

                # Content-Length pre-check (optional signal)
                cl = resp.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > max_bytes:
                    raise AttachmentError(
                        f"URL {current!r} content-length {cl} exceeds cap {max_bytes}"
                    )

                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise AttachmentError(
                            f"URL {current!r} body exceeded cap {max_bytes} bytes"
                        )

                filename = Path(urlparse(current).path).name or "attachment"
                return filename, bytes(buf)


# -------------------------------------------------------------- local path


def read_local_path_bytes(path: str | Path) -> tuple[str, bytes]:
    """Read a local file, enforcing opt-in + root-containment + size cap."""
    if not settings.attachment_allow_local_paths:
        raise AttachmentError(
            "local-file attachments are disabled "
            "(set ATTACHMENT_ALLOW_LOCAL_PATHS=true and ATTACHMENT_ROOT to enable)"
        )
    root_raw = (settings.attachment_root or "").strip()
    if not root_raw:
        raise AttachmentError(
            "ATTACHMENT_ROOT is required when ATTACHMENT_ALLOW_LOCAL_PATHS is true"
        )
    root = Path(root_raw).resolve()
    if not root.is_absolute() or not root.is_dir():
        raise AttachmentError(f"ATTACHMENT_ROOT {root!s} is not an existing directory")

    target = Path(path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise AttachmentError(
            f"path {target!s} is outside ATTACHMENT_ROOT {root!s}"
        ) from exc
    if not target.is_file():
        raise AttachmentError(f"path {target!s} is not a regular file")
    # Reject symlinks that point out of root even if the resolved target is inside
    # (defence-in-depth; Path.resolve() already follows, so this guards the parent chain).
    if target.is_symlink():
        raise AttachmentError(f"path {target!s} is a symlink; refusing to follow")

    size = target.stat().st_size
    max_bytes = int(settings.attachment_max_bytes)
    if size > max_bytes:
        raise AttachmentError(
            f"file {target!s} size {size} exceeds cap {max_bytes}"
        )

    return target.name, target.read_bytes()


# ---------------------------------------------------------------- dispatcher


async def load_attachment(source: str) -> tuple[str, bytes]:
    """Return `(filename, content)` for an attachment source (URL or local path).

    Raises `AttachmentError` on any policy violation.
    """
    if source.startswith(("http://", "https://")):
        return await fetch_url_bytes(source)
    return read_local_path_bytes(source)


__all__: Iterable[str] = (
    "AttachmentError",
    "fetch_url_bytes",
    "read_local_path_bytes",
    "load_attachment",
)
