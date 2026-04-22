"""Settings loaded from environment / .env for the samanage-mcp server.

Loading order (first non-empty wins):
  1. `SAMANAGE_API_TOKEN` environment variable (the supported path when the
     token is delivered by an MCP client's server config `env` block).
  2. Contents of the file named by `SAMANAGE_API_TOKEN_FILE` (for docker/k8s
     secrets, systemd `LoadCredential`, 1Password CLI injection, etc.).
  3. `SAMANAGE_API_TOKEN` in a local `.env` file (development convenience).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Samanage / SWSD API
    samanage_api_token: str | None = None
    # Optional: path to a file containing the API token (preferred over plain
    # env when using secret managers / docker secrets / k8s volumes).
    samanage_api_token_file: str | None = None
    samanage_base_url: str = "https://api.samanage.com"

    # Resource path (without `.json`) for response templates. The Samanage API
    # doesn't publicly document this endpoint; override if your tenant exposes
    # it under a different name (e.g. "comment_templates").
    samanage_response_template_resource: str = "response_templates"
    # Singular JSON wrapper key for response-template request bodies.
    samanage_response_template_singular: str = "response_template"

    # Accept header. The versioned form (v2.1+json) is required for Samanage
    # to honor the full filter surface on list endpoints; plain application/json
    # silently drops many filters. Override only for tenants pinned to an older
    # API version.
    samanage_accept_header: str = "application/vnd.samanage.v2.1+json"

    # Dry-run: write tools log and return synthetic results instead of hitting the API
    samanage_dry_run: bool = False

    # Fallback requester email used when create_incident isn't given one
    samanage_default_requester: str | None = None

    # HTTP timeouts
    http_timeout_seconds: float = 30.0
    list_timeout_seconds: float = 20.0
    # Retry on 429 / 5xx. Set http_max_retries=0 to disable.
    http_max_retries: int = 3
    http_retry_backoff_factor: float = 1.0

    # Users cache TTL for requester resolution
    users_cache_ttl_seconds: int = 600

    # --- Attachment safety (applies to add_attachment_to_incident + create_incident attachments)
    # Max bytes to read from any local file or remote URL. Default 25 MiB.
    attachment_max_bytes: int = 25 * 1024 * 1024
    # Comma-separated hostname allowlist for URL attachments. Empty means
    # "only the Samanage host" (derived from SAMANAGE_BASE_URL).
    attachment_url_allowed_hosts: str = ""
    # When false (default), URLs resolving to private / loopback / link-local /
    # reserved / multicast IPs are rejected (SSRF guard).
    attachment_allow_private_ips: bool = False
    # Maximum redirect hops honored when fetching URL attachments.
    attachment_max_redirects: int = 3
    # Explicit opt-in required for attaching local filesystem paths.
    attachment_allow_local_paths: bool = False
    # If local paths are allowed, they must resolve under this absolute root.
    attachment_root: str | None = None

    # Logging
    log_level: str = "INFO"


def _load_token_from_file(settings: "Settings") -> tuple[str | None, str]:
    """Resolve the effective API token and report its source.

    Returns `(token, source)` where `source` is one of
    `"env"`, `"token_file"`, `"dotenv"`, or `"unset"`.
    """
    import os

    raw = (settings.samanage_api_token or "").strip()
    if raw:
        # Could be from the process env OR from .env. Detect which.
        if (os.environ.get("SAMANAGE_API_TOKEN") or "").strip() == raw:
            return raw, "env"
        return raw, "dotenv"

    path = (settings.samanage_api_token_file or "").strip()
    if path:
        try:
            contents = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return None, "unset"
        if contents:
            return contents, "token_file"

    return None, "unset"


settings = Settings()

# Resolve token-from-file once at import so the rest of the app can just read
# `settings.samanage_api_token`.
_token, token_source = _load_token_from_file(settings)
if _token and not (settings.samanage_api_token or "").strip():
    settings.samanage_api_token = _token
