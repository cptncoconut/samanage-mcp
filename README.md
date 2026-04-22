# samanage-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that exposes SolarWinds Service Desk
(Samanage / SWSD) operations as tools, letting AI agents in Warp, Claude Desktop,
Cursor, and other MCP clients create, update, query, and close incidents — as well as
manage users, categories, departments, groups, and response templates.

## Quickstart

Requires Python 3.11+. No `pip install` or venv setup needed.

```bash
git clone https://github.com/cptncoconut/samanage-mcp.git ~/samanage-mcp
```

Add to your MCP client config (Warp: Settings → AI → Manage MCP servers):

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

`bin/samanage-mcp` auto-creates a `.venv` and installs the project on first run
(<10s). Subsequent launches skip straight to the server (<1s).

> Need pip install instead? `pip install -e .` then run `samanage-mcp`.

## Tools

### Incidents

- `create_incident(name, description, priority?, category?, subcategory?, requester?, assignee?, state?, attachments?, resolve_requester_from_text?, extra?)`
- `update_incident(id, note?, state?, priority?, assignee?, category?, subcategory?, close?, extra?)`
- `list_incidents(state?, priority?, assignee?, requester?, category?, site?, department?, group?, name_contains?, created_from?, created_to?, updated_days?, sort_by?, sort_order?, per_page?, max_pages?, filters?, slim?)`
- `get_incident(id)`
- `delete_incident(id)` — destructive; respects `SAMANAGE_DRY_RUN`.
- `list_comments(incident_id)` / `add_comment(incident_id, body, is_private?)`
- `add_attachment_to_incident(incident_id, source)` — local path or URL.
- `summarize_incidents_this_month()` — total + per-state counts for the current calendar month.

### Users

- `list_users(query?, limit?, full?, filters?)`
- `find_user_by_email(email)`
- `resolve_user(candidate, fallback?)`
- `create_user(name, email, role?, department?, site?, extra?)`
- `update_user(id, name?, email?, role?, disabled?, extra?)`
- `delete_user(id)` — destructive.

### Catalog

Each resource has `list_*(query?, limit?, filters?)`, `get_*(id)`,
`create_*(name, extra?)`, `update_*(id, name?, extra?)`, `delete_*(id)`:

- Categories
- Departments
- Sites
- Groups (plus `add_group_member(id, email)`)
- Solutions (`create_solution` also requires `description`; `update_solution` supports `description`)

### Response templates

- `list_response_templates(query?, limit?, full?)`
- `get_response_template(id? | name?)`
- `create_response_template(name, body, extra?)`
- `update_response_template(id, name?, body?, extra?)`
- `delete_response_template(id)` — destructive.
- `apply_response_template_to_incident(incident_id, template_id? | template_name?, is_private?, append_text?)`

### Filtering

All `list_*` tools accept a `filters` dict passed verbatim to the Samanage API.
The `list_incidents` response includes `applied_filters` for debugging.

```json
{
  "state": ["New", "Assigned"],
  "assignee": "alice@example.com",
  "filters": {
    "Escalation Level": "Tier 2",
    "tags[]": ["vip"]
  }
}
```

Samanage only honours the full filter surface with
`Accept: application/vnd.samanage.v2.1+json` — this server sends that header
by default.

### Dry-run

All write tools honour `SAMANAGE_DRY_RUN=true`: they log the payload and return
a synthetic result without calling the API.

## Examples

Create an incident:

```json
{
  "name": "wifi down at Site A",
  "description": "APs offline since 14:00",
  "priority": "High",
  "requester": "user@example.com"
}
```

Add a note and close:

```json
{ "id": 12345, "note": "confirmed fixed after reboot", "close": true }
```

List recent high-priority incidents:

```json
{ "priority": "High", "updated_days": 7, "max_pages": 2 }
```

Update category:

```json
{ "id": 12345, "category": "Devops", "subcategory": "Backup Notifications" }
```

## Documentation

- [Configuration](docs/configuration.md) — all environment variables, token sources, attachment safety
- [Docker / HTTP transport](docs/docker.md) — container deployment, reverse proxy, Docker secrets
- [Development](docs/development.md) — dev setup, make targets, test guide, project structure
- [Security](SECURITY.md) — known limitations and secure deployment checklist

## Roadmap

- Assets: hardwares, mobiles, other_assets, configuration_items
- ITIL: changes, problems, releases
- Misc: custom_fields, tasks, time_tracks

## Contributing

Pull requests welcome. Run `make lint test` before submitting.

## License

[MIT](LICENSE)
