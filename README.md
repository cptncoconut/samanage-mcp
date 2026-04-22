# samanage-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that exposes SolarWinds Service Desk
(Samanage / SWSD) operations as tools, letting AI agents in Warp, Claude Desktop,
Cursor, and other MCP clients create, update, query, and close incidents — as well as
manage users, categories, departments, groups, and response templates.

## Zero-install quickstart (clone + configure Warp, nothing else)

Requires Python 3.11+ on your `PATH` (macOS: `brew install python@3.12` if
you don't already have one). No `pip install`, no `make install`, no venv
setup by hand.

```bash
git clone https://github.com/YOUR_USERNAME/samanage-mcp.git ~/samanage-mcp
```

Then add this to your Warp MCP server config (Settings → AI → Manage MCP
servers, or edit your `mcp_servers.json`):

```json
{
  "mcpServers": {
    "samanage": {
      "command": "/Users/YOU/samanage-mcp/bin/samanage-mcp",
      "env": {
        "SAMANAGE_API_TOKEN": "YOUR_TOKEN_HERE",
        "SAMANAGE_BASE_URL": "https://api.samanage.com"
      }
    }
  }
}
```

`bin/samanage-mcp` is a small wrapper that, on first invocation, creates a
`.venv` in the repo and installs the project. Subsequent launches skip the
install and just exec the server (<1s). To force a re-install, `touch`
`pyproject.toml` or delete `.venv`. All bootstrap output goes to `stderr`
so it never corrupts the MCP stdio stream.

To use a specific Python interpreter (e.g. 3.12 from Homebrew):

```json
"env": {
  "SAMANAGE_MCP_PYTHON": "/opt/homebrew/bin/python3.12",
  "SAMANAGE_API_TOKEN": "..."
}
```

## Install (dev)

```bash
make install           # creates .venv + installs dev extras
# or manually:
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

## Configuration

All settings arrive through environment variables. There are three supported
sources, in priority order:

1. **MCP client `env` block (recommended).** Every MCP client (Warp, Claude
   Desktop, Cursor, Codeium, …) lets you set environment variables for the
   stdio server subprocess. The token never touches disk in this project.
2. **`SAMANAGE_API_TOKEN_FILE`** — absolute path to a file whose contents are
   the token. Handy for Docker secrets, Kubernetes secret volumes, systemd
   `LoadCredential`, or 1Password / Vault CLI injection.
3. **`.env` next to the CWD** (development convenience only; see "Local dev
   with .env" below).

Supported variables:

- `SAMANAGE_API_TOKEN` — personal API token with read/write permissions.
- `SAMANAGE_API_TOKEN_FILE` — alternative to `SAMANAGE_API_TOKEN`.
- `SAMANAGE_BASE_URL` — typically `https://api.samanage.com`.
- `SAMANAGE_DRY_RUN` — `true` to log write calls without hitting the API.
- `SAMANAGE_DEFAULT_REQUESTER` — fallback requester email for create tools.
- `LOG_LEVEL` — default `INFO`.

On startup the server logs which source the token came from, e.g.
`samanage-mcp credentials loaded from env; base_url=...`.
### Attachment safety (SSRF / path-traversal guards)
- `ATTACHMENT_MAX_BYTES` — hard cap for both URL downloads and local-file reads (default 25 MiB).
- `ATTACHMENT_URL_ALLOWED_HOSTS` — comma-separated hostname allowlist for URL attachments. The Samanage base URL host is always permitted; other hosts must be listed here.
- `ATTACHMENT_ALLOW_PRIVATE_IPS` — default `false`; URLs that resolve to private / loopback / link-local / reserved / multicast IPs are rejected (blocks cloud metadata, localhost, internal networks).
- `ATTACHMENT_MAX_REDIRECTS` — default `3`; each redirect hop is re-validated against the host + IP policy.
- `ATTACHMENT_ALLOW_LOCAL_PATHS` — default `false`; must be `true` to attach from local disk.
- `ATTACHMENT_ROOT` — required when local paths are enabled. Any path must resolve under this directory; symlinks and path-escape attempts are rejected.

## Run

Stdio (default, for Warp / Claude Desktop / Cursor / MCP Inspector):

```bash
samanage-mcp
```

Streamable HTTP:

```bash
samanage-mcp --http --host 127.0.0.1 --port 8765
```

Inspect interactively:

```bash
npx @modelcontextprotocol/inspector samanage-mcp
```

## MCP client config (passing the API key from your agent)

Every MCP client spawns the stdio server as a subprocess and lets you set
environment variables on it. Put the token there — no `.env` needed. The
token stays in your agent's config store (Warp Drive, Claude Desktop, etc.)
instead of on disk next to the code.

Warp / Claude Desktop / Cursor / Codeium all use the same JSON shape:

```json
{
  "mcpServers": {
    "samanage": {
      "command": "samanage-mcp",
      "env": {
        "SAMANAGE_API_TOKEN": "YOUR_TOKEN_HERE",
        "SAMANAGE_BASE_URL": "https://api.samanage.com"
      }
    }
  }
}
```

If your agent is not on `PATH`, use the absolute path (e.g.
`/Users/you/projects/samanage-mcp/.venv/bin/samanage-mcp`).

To dry-run every write call from the agent without touching Samanage, add
`"SAMANAGE_DRY_RUN": "true"` to the same `env` block.

### Local dev with `.env` (optional)

For a quick local run outside an MCP client, copy `.env.example` to `.env`
and fill it in. Values in `.env` are only loaded when the matching environment
variable is **not** already set, so the MCP-client `env` block always wins.
`chmod 600 .env` and never commit it (`.env` is already in `.gitignore`).

## Tools

### Incidents

- `create_incident(name, description, priority?, category?, subcategory?, requester?, assignee?, state?, attachments?, resolve_requester_from_text?, extra?)`
- `update_incident(id, note?, state?, priority?, assignee?, close?, extra?)`
- `list_incidents(state?, priority?, assignee?, requester?, name_contains?, created_from?, created_to?, updated_days?, sort_by?, sort_order?, per_page?, max_pages?, extra_params?)`
- `get_incident(id)`
- `delete_incident(id)` — destructive; respects dry-run.
- `list_comments(incident_id)` / `add_comment(incident_id, body, is_private?)`
- `add_attachment_to_incident(incident_id, source)` — local path or URL.
- `summarize_incidents_this_month()` — total + per-state counts.

### Users

- `list_users(query?, limit?, full?)`
- `find_user_by_email(email)`
- `resolve_user(candidate, fallback?)`
- `create_user(name, email, role?, department?, site?, extra?)`
- `update_user(id, name?, email?, role?, disabled?, extra?)`
- `delete_user(id)` — destructive.

### Catalog

Each resource below has `list_*(query?, limit?)`, `get_*(id)`, `create_*(name, extra?)`, `update_*(id, name?, extra?)`, `delete_*(id)`:

- Categories
- Departments
- Sites
- Groups (plus `add_group_member(id, email)`)
- Solutions (`create_solution` also requires `description`; `update_solution` supports `description`)

### Filtering cheatsheet

Samanage only honors its full filter surface when the request sends
`Accept: application/vnd.samanage.v2.1+json`. This server does that by
default (override with `SAMANAGE_ACCEPT_HEADER` if your tenant needs a
different version). With the plain `application/json` header, almost every
filter except `state[]` is silently ignored — which is why filtering may
"only work on state" against naive clients.

Samanage expects array-valued keys with a `[]` suffix and uses the same key
multiple times for multi-value filters:

- `state[]`, `priority[]`, `assignee[]`, `requester[]`, `category[]`,
  `site[]`, `department[]`, `group[]`, `tags[]`
- `name.contains` — substring match on incident name.
- `created[]` — pass twice for a date range; or use `created_gt` /
  `created_lt` for open-ended ranges.
- `updated` — number of days back (integer).
- `sort_by`, `sort_order` — field name and `ASC`/`DESC`.
- Custom fields — use the literal field name (with spaces) as the key, e.g.
  `"Hardware Type": "Laptop"`.

Every `list_*` tool in this server takes a `filters` dict that is passed
verbatim to Samanage, so you can always access the full filter surface even
when no named argument exists for the field:

```json
{
  "state": ["Active"],
  "assignee": "alice@example.com",
  "filters": {
    "Escalation Level": "Tier 2",
    "tags[]": ["vip", "payroll"]
  }
}
```

The `list_incidents` response includes `applied_filters` so you can verify
the exact query string that was built.

### Response templates (canned responses)

- `list_response_templates(query?, limit?, full?)` — slim view by default.
- `get_response_template(id? | name?)` — lookup by id or exact name.
- `create_response_template(name, body, extra?)`
- `update_response_template(id, name?, body?, extra?)`
- `delete_response_template(id)` — destructive.
- `apply_response_template_to_incident(incident_id, template_id? | template_name?, is_private?, append_text?)` — fetch the template body and post it as a comment.

Default endpoint is `/response_templates.json`. If your tenant exposes it under
a different path, override with `SAMANAGE_RESPONSE_TEMPLATE_RESOURCE` (and
`SAMANAGE_RESPONSE_TEMPLATE_SINGULAR` for the JSON wrapper key).

All write tools (create / update / delete on any resource, plus
`delete_incident`, `add_comment`, `add_attachment_to_incident`) honor
`SAMANAGE_DRY_RUN=true`: they log the payload and return a synthetic result
instead of calling the API. Destructive tools are not gated behind a separate
flag — use dry-run or a scoped API token to limit blast radius.

## Development

```bash
make lint              # ruff check
make format            # ruff format + autofix
make test              # pytest (respx mocks the Samanage API)
make run               # stdio server
make run-http          # streamable HTTP on 127.0.0.1:8765
make inspect           # launch MCP Inspector pointing at the stdio server
```

Tests live under `tests/` and never hit the real Samanage API:

- `tests/test_client.py` — `SamanageClient` unit tests (respx-mocked httpx).
- `tests/test_tools.py` — end-to-end tool calls via `FastMCP.call_tool`, covering dry-run writes, filter-building reads, and error surfacing.

## Docker (HTTP transport)

```bash
docker compose up --build
```

The container serves streamable HTTP on `:8765` using the `.env` file for
credentials. Point your remote MCP client at `http://<host>:8765/mcp`.

## Examples

Dry-run create (no API call is made):

```bash
SAMANAGE_DRY_RUN=true samanage-mcp
```

Then from your MCP client, call `create_incident`:

```json
{
  "name": "wifi down at Site A",
  "description": "APs offline since 14:00",
  "priority": "high",
  "requester": "user@example.com"
}
```

List recent high-priority incidents:

```json
{ "priority": "High", "updated_days": 7, "max_pages": 2 }
```

Add a note and close:

```json
{ "id": 12345, "note": "user confirmed fixed after reboot", "close": true }
```

## Roadmap

- Assets: hardwares, mobiles, other_assets, configuration_items
- ITIL: changes, problems, releases
- Misc: custom_fields, tasks, time_tracks

## Contributing

Pull requests welcome. Run `make lint test` before submitting.

## License

[MIT](LICENSE)
