"""MCP tool registrations for samanage-mcp.

Each module exposes a `register(mcp)` function that attaches its tools to
the given FastMCP instance. `register_all` wires them up in one call.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import catalog, incidents, response_templates, users


def register_all(mcp: FastMCP) -> None:
    incidents.register(mcp)
    users.register(mcp)
    catalog.register(mcp)
    response_templates.register(mcp)


__all__ = [
    "register_all",
    "incidents",
    "users",
    "catalog",
    "response_templates",
]
