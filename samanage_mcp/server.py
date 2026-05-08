"""samanage-mcp FastMCP server entry point.

Defaults to stdio transport (for Warp, Claude Desktop, Cursor, MCP Inspector).
Pass `--http` to serve over streamable HTTP.
"""

from __future__ import annotations

import argparse
import logging
import os

from mcp.server.fastmcp import FastMCP

from .config import settings, token_source
from .tools import register_all

logger = logging.getLogger(__name__)


def _build_server() -> FastMCP:
    logging.basicConfig(
        level=getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _log_credential_source()
    mcp = FastMCP("samanage-mcp")
    register_all(mcp)
    return mcp


def _log_credential_source() -> None:
    if not (settings.samanage_api_token or "").strip():
        logger.warning(
            "samanage-mcp starting without an API token; set SAMANAGE_API_TOKEN "
            "(preferably via your MCP client's server config env block) or "
            "SAMANAGE_API_TOKEN_FILE."
        )
        return
    logger.info(
        "samanage-mcp credentials loaded from %s; base_url=%s",
        token_source,
        settings.samanage_base_url,
    )


# Module-level instance so `fastmcp run samanage_mcp/server.py` and
# `mcp dev samanage_mcp/server.py` can discover it.
mcp = _build_server()


def main() -> None:
    parser = argparse.ArgumentParser(prog="samanage-mcp")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve over streamable HTTP instead of stdio.",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", bind_host=args.host, bind_port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
