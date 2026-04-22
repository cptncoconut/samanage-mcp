# Security

## Reporting a vulnerability

Please open a GitHub issue tagged **security** or email the maintainer directly.
Do not include exploit details in public issues.

## Known limitations

### HTTP transport has no authentication

When started with `--http` (or via Docker), the MCP server exposes its full
Samanage API surface over HTTP with **no built-in authentication**. Anyone who
can reach the port can call any tool.

**Mitigations:**
- The default bind address is `127.0.0.1` (localhost only). Never bind to
  `0.0.0.0` without a reverse proxy that enforces authentication.
- The Docker Compose file binds to `127.0.0.1:8765` by default. If you change
  this, place an authenticating reverse proxy (nginx, Traefik, Caddy) in front.
- The stdio transport (default, used by Warp / Claude Desktop / Cursor) is not
  affected — it has no network listener.

### Attachment URL fetching: DNS rebinding

The SSRF guard in `attachments.py` validates a URL's resolved IPs **before**
opening the connection. A DNS rebinding attack can cause the hostname to
re-resolve to a private IP between the check and the actual connection,
bypassing the allowlist.

**Mitigations:**
- URL attachments are disabled by default and only enabled via explicit
  `ATTACHMENT_URL_ALLOWED_HOSTS` config.
- Keep `ATTACHMENT_ALLOW_PRIVATE_IPS=false` (default).
- Do not add untrusted hostnames to `ATTACHMENT_URL_ALLOWED_HOSTS`.
- A future release will pin DNS resolution to the checked IP.

### Incident/resource ID injection

Resource IDs passed to tools are interpolated directly into API URLs. A
maliciously crafted ID containing `/` or `..` could reach an unintended
Samanage API endpoint on the same host.

**Mitigation:** Only pass numeric or known-safe IDs. Input validation for
`id` fields will be added in a future release.

## Secure deployment checklist

- [ ] Pass `SAMANAGE_API_TOKEN` via the MCP client `env` block or a secrets
  manager — never commit it or write it to disk in plain text.
- [ ] Use a scoped API token (read-only where possible) to limit blast radius.
- [ ] Keep `SAMANAGE_DRY_RUN=true` during initial setup to verify tool
  behaviour without mutating data.
- [ ] If running the HTTP transport, bind to `127.0.0.1` and put an
  authenticated reverse proxy in front before exposing to a network.
- [ ] Set `ATTACHMENT_ALLOW_LOCAL_PATHS=false` (default) unless you need
  local-file attachments, and always set `ATTACHMENT_ROOT` when enabling it.
- [ ] Protect `.env` with `chmod 600` if you use file-based config.
