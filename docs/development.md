# Development

## Setup

```bash
make install
# equivalent to:
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

Requires Python 3.11+. Use `pyenv` or `brew install python@3.12` if needed.

## Make targets

| Target | Description |
|---|---|
| `make install` | Create `.venv` and install the package + dev dependencies. |
| `make lint` | Run `ruff check` (no fixes). |
| `make format` | Run `ruff format` + auto-fix lint issues. |
| `make test` | Run the full pytest suite (no real API calls). |
| `make run` | Start the stdio server. |
| `make run-http` | Start the HTTP server on `127.0.0.1:8765`. |
| `make inspect` | Launch MCP Inspector pointing at the stdio server. |

## Running the server locally

Stdio (for use with Warp / Claude Desktop / MCP Inspector):

```bash
SAMANAGE_API_TOKEN=your_token samanage-mcp
```

HTTP (for testing remote clients):

```bash
SAMANAGE_API_TOKEN=your_token samanage-mcp --http --host 127.0.0.1 --port 8765
```

Inspect interactively with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector samanage-mcp
```

## Tests

Tests live in `tests/` and never hit the real Samanage API — all HTTP is
mocked with [respx](https://lundberg.github.io/respx/).

| File | What it covers |
|---|---|
| `tests/test_client.py` | `SamanageClient` unit tests: pagination, retry, auth, error parsing. |
| `tests/test_tools.py` | End-to-end tool calls via `FastMCP.call_tool`: dry-run writes, filter building, error surfacing. |
| `tests/test_attachments.py` | SSRF guards, redirect validation, size cap, local-path containment. |
| `tests/test_config.py` | Token resolution from env, token file, and dotenv. |
| `tests/test_response_templates.py` | Template list, get-by-name, apply to incident. |

```bash
make test                    # all tests
pytest tests/test_client.py  # single file
pytest -k "retry"            # filter by name
```

## Code style

[Ruff](https://docs.astral.sh/ruff/) handles both formatting and linting.
Line length is 100, target is Python 3.11+.

```bash
make format   # format + autofix
make lint     # check only (CI mode)
```

## Project structure

```
samanage_mcp/
  client.py          # async httpx wrapper, pagination, retry, user cache
  config.py          # pydantic-settings; token resolution from env/file/.env
  server.py          # FastMCP entry point; --http / stdio transport
  attachments.py     # SSRF + path-traversal guards for file/URL attachments
  tools/
    incidents.py     # incident CRUD + comments + attachments
    users.py         # user CRUD + resolve helpers
    catalog.py       # categories, departments, sites, groups, solutions
    response_templates.py
```
