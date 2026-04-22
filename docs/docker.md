# Docker / HTTP transport

> **Security warning:** The HTTP transport has **no built-in authentication**.
> Anyone who can reach the port can call any tool. Read the mitigations below
> before exposing the server beyond `127.0.0.1`. See [SECURITY.md](../SECURITY.md)
> for the full threat model.

## Quick start

```bash
cp .env.example .env        # fill in SAMANAGE_API_TOKEN (and other vars as needed)
docker compose up --build
```

The container binds to `127.0.0.1:8765` by default. Point your MCP client at:
```
http://127.0.0.1:8765/mcp
```

## Running without Docker Compose

```bash
docker build -t samanage-mcp .
docker run --rm \
  -e SAMANAGE_API_TOKEN=your_token \
  -e SAMANAGE_BASE_URL=https://api.samanage.com \
  -p 127.0.0.1:8765:8765 \
  samanage-mcp
```

## Exposing beyond localhost

If you need to reach the server from another machine (e.g. a remote MCP client),
put an authenticating reverse proxy in front **before** opening the port.

Example with Caddy:

```
reverse_proxy /mcp* localhost:8765
basicauth /mcp* {
    your_user JDJhJDE0...hashed_password
}
```

Then in `docker-compose.yml`, change the ports binding from
`127.0.0.1:8765:8765` to `127.0.0.1:8765:8765` and let the proxy handle
external traffic.

## Environment variables

All variables from [configuration.md](configuration.md) work in Docker.
The most common ones to set:

```dotenv
SAMANAGE_API_TOKEN=your_token_here
SAMANAGE_BASE_URL=https://api.samanage.com
SAMANAGE_DRY_RUN=false
LOG_LEVEL=INFO
```

The `HOST` and `PORT` env vars control the bind address inside the container
(defaults `0.0.0.0` and `8765`). The Docker Compose file maps this to
`127.0.0.1:8765` on the host.

## Using Docker secrets (recommended for production)

```yaml
services:
  samanage-mcp:
    build: .
    secrets:
      - samanage_token
    environment:
      SAMANAGE_API_TOKEN_FILE: /run/secrets/samanage_token
      SAMANAGE_BASE_URL: https://api.samanage.com
    ports:
      - "127.0.0.1:8765:8765"

secrets:
  samanage_token:
    file: ./secrets/samanage_token.txt
```
