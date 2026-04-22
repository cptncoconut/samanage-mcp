# Configuration

All settings are delivered via environment variables. Three sources are
supported, in priority order:

1. **MCP client `env` block (recommended)** — every MCP client (Warp, Claude
   Desktop, Cursor, Codeium, …) lets you set env vars on the stdio subprocess.
   The token never touches disk.
2. **`SAMANAGE_API_TOKEN_FILE`** — absolute path to a file whose sole contents
   are the token. Suitable for Docker secrets, Kubernetes secret volumes,
   systemd `LoadCredential`, or 1Password / Vault CLI injection.
3. **`.env` file** — development convenience only. Copy `.env.example` to
   `.env`, fill it in, and `chmod 600 .env`. Values in `.env` are only loaded
   when the matching env var is **not** already set, so the MCP-client block
   always wins. Never commit `.env` (it is in `.gitignore`).

On startup the server logs which source the credential came from:
```
samanage-mcp credentials loaded from env; base_url=https://api.samanage.com
```

## Environment variables

### Core

| Variable | Default | Description |
|---|---|---|
| `SAMANAGE_API_TOKEN` | — | API token with read/write permissions. |
| `SAMANAGE_API_TOKEN_FILE` | — | Path to a file containing the token (alternative to above). |
| `SAMANAGE_BASE_URL` | `https://api.samanage.com` | API base URL. |
| `SAMANAGE_DRY_RUN` | `false` | Log all write calls without hitting the API. |
| `SAMANAGE_DEFAULT_REQUESTER` | — | Fallback requester email used by `create_incident` when none is provided. |
| `SAMANAGE_ACCEPT_HEADER` | `application/vnd.samanage.v2.1+json` | Override only if your tenant requires a different API version. |
| `LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

### HTTP & retry

| Variable | Default | Description |
|---|---|---|
| `HTTP_TIMEOUT_SECONDS` | `30.0` | Per-request timeout for single-resource calls (get/post/put/delete). |
| `LIST_TIMEOUT_SECONDS` | `20.0` | Per-page timeout for paginated list calls. |
| `HTTP_MAX_RETRIES` | `3` | Max retries on HTTP 429 / 500 / 502 / 503 / 504 and network errors. Set to `0` to disable. |
| `HTTP_RETRY_BACKOFF_FACTOR` | `1.0` | Back-off multiplier. Wait before attempt n = `factor × 2ⁿ` seconds. `Retry-After` headers are honoured when present. |

### Response templates

| Variable | Default | Description |
|---|---|---|
| `SAMANAGE_RESPONSE_TEMPLATE_RESOURCE` | `response_templates` | API resource path for canned responses. Override if your tenant exposes it under a different name. |
| `SAMANAGE_RESPONSE_TEMPLATE_SINGULAR` | `response_template` | JSON body wrapper key for template requests. |

### Attachment safety

URL and local-file attachments are off or tightly restricted by default.
See [SECURITY.md](../SECURITY.md) for the threat model.

| Variable | Default | Description |
|---|---|---|
| `ATTACHMENT_MAX_BYTES` | `26214400` (25 MiB) | Hard cap on bytes read from any URL download or local file. |
| `ATTACHMENT_URL_ALLOWED_HOSTS` | `""` | Comma-separated hostname allowlist for URL attachments. The Samanage base URL host is always permitted; all other hosts must be listed here explicitly. |
| `ATTACHMENT_ALLOW_PRIVATE_IPS` | `false` | When `false`, URLs that resolve to private / loopback / link-local / reserved / multicast IPs are rejected (SSRF guard). |
| `ATTACHMENT_MAX_REDIRECTS` | `3` | Maximum redirect hops; each hop is re-validated against the host and IP policy. |
| `ATTACHMENT_ALLOW_LOCAL_PATHS` | `false` | Must be `true` to attach local filesystem paths. |
| `ATTACHMENT_ROOT` | — | Required when local paths are enabled. Attachments must resolve under this directory; symlinks and path-escape attempts are rejected. |

## MCP client config examples

### Warp / Claude Desktop / Cursor

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

If `samanage-mcp` is not on `PATH`, use the absolute path to the binary (e.g.
`/Users/you/samanage-mcp/.venv/bin/samanage-mcp` or the `bin/samanage-mcp`
self-bootstrapping wrapper).

Add `"SAMANAGE_DRY_RUN": "true"` to test without mutating any data.

### Using the token-file approach (Docker / k8s)

```json
{
  "mcpServers": {
    "samanage": {
      "command": "samanage-mcp",
      "env": {
        "SAMANAGE_API_TOKEN_FILE": "/run/secrets/samanage_token",
        "SAMANAGE_BASE_URL": "https://api.samanage.com"
      }
    }
  }
}
```
