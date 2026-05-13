# Deployment

This page is the deployment home for Quater apps. The short version is:

```bash
quater run main:app --host 0.0.0.0 --port 8000
```

`quater run` uses Granian, keeps reload off, enables access logs, and runs
production safety checks before it starts serving traffic.

## Recommended Server

Use `quater run` unless you have a specific reason to manage the server process
yourself.

```bash
quater run main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4
```

The default interface is RSGI, which is Quater's primary path through Granian.
You can still choose another interface when your deployment needs it:

```bash
quater run main:app --interface asgi
quater run main:app --interface wsgi
```

Use `quater dev` only for local development. It enables reload by default and
binds to `127.0.0.1`.

## Production Checks

Before `quater run` starts Granian, it calls:

```python
app.validate_production()
```

That does two things:

- compiles routes, so route conflicts fail before serving.
- checks production settings that are easy to get wrong.

The current production checks require:

- `debug=False`
- `security="strict"`
- `allowed_hosts` is configured
- `allowed_hosts` does not contain `*`

Use `--allow-insecure` only in a controlled environment where you intentionally
want to skip these checks:

```bash
quater run main:app --allow-insecure
```

## Direct Server Usage

You can run Quater through Granian, Uvicorn, Gunicorn, or another server
directly. When you do that, call `app.validate_production()` in your app module
after all routes are declared:

```python
from quater import Quater

app = Quater(allowed_hosts=["api.example.com"])


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


app.validate_production()
```

This makes unsafe config fail during import, before the server accepts traffic.
Do not put this call before route declarations, because route conflicts can only
be found after routes exist.

For Granian directly:

```bash
granian main:app --interface rsgi --host 0.0.0.0 --port 8000
```

For ASGI-compatible servers, expose `app.asgi` if the server wants an explicit
ASGI callable:

```python
from quater import Quater

app = Quater(allowed_hosts=["api.example.com"])

# routes...

app.validate_production()
asgi_app = app.asgi
```

For WSGI-compatible servers, expose `app.wsgi`:

```python
wsgi_app = app.wsgi
```

## Hosts

`allowed_hosts` protects your app from unexpected Host headers:

```python
app = Quater(allowed_hosts=["api.example.com"])
```

In strict mode, the development default `allowed_hosts=()` no longer means
"allow every host". It accepts local hosts only:

- `localhost`
- `127.0.0.1`
- `::1`
- `testserver`

That keeps local development and the in-process test client easy, while making a
deployed app reject unexpected external hosts unless you configure them.

If you truly want runtime allow-all behavior, make it explicit:

```python
app = Quater(allowed_hosts=["*"])
```

`app.validate_production()` rejects `allowed_hosts=["*"]`, so this is for
controlled local, preview, or embedded use only.

## Reverse Proxies

Only configure `trusted_proxies` for proxy IPs or CIDR ranges you control:

```python
app = Quater(
    allowed_hosts=["api.example.com"],
    trusted_proxies=["10.0.0.0/8"],
)
```

Quater ignores forwarded host and scheme headers unless the request comes from a
trusted proxy. That prevents random clients from spoofing
`X-Forwarded-Host` or `X-Forwarded-Proto`.

## Docs Endpoints

Quater enables these docs endpoints by default:

- `/docs`
- `/openapi.json`
- `/mcp/docs`

That is useful for development. In production, decide intentionally.

Disable public HTTP docs when route metadata should not be exposed:

```python
app = Quater(
    allowed_hosts=["api.example.com"],
    docs_path=None,
    openapi_path=None,
)
```

`/mcp/docs` is protected by `mcp_auth` when tools are exposed, because Quater
requires `mcp_auth` as soon as any route has `tool=True`.

## MCP And Remote CLI

Hosted MCP and remote CLI calls are normal HTTP requests to your app:

- MCP uses `POST /mcp`
- remote action discovery uses `GET /.well-known/quater-actions.json`
- remote action calls use `POST /__quater__/actions/call`

If you expose MCP tools, configure `mcp_auth`. If you expose CLI actions,
configure `cli_auth`.

```python
app = Quater(
    allowed_hosts=["api.example.com"],
    mcp_auth=authenticate,
    cli_auth=authenticate,
)
```

These protocol endpoints still go through request checks, body limits, Host
validation, and their own auth boundary.

## Common Mistakes

- Running production traffic with `debug=True`.
- Forgetting `allowed_hosts` before deploying behind a real domain.
- Using `allowed_hosts=["*"]` in production.
- Trusting every proxy instead of only your proxy IPs.
- Leaving `/docs` and `/openapi.json` public when route metadata is sensitive.
- Assuming direct Granian/Uvicorn/Gunicorn startup runs `quater run` checks.

When in doubt, use `quater run`. If you do not use it, call
`app.validate_production()` yourself.
