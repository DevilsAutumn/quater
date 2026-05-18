# Deployment

This page explains how to run a Quater app safely in development and production.

## Prerequisites

Read [Security](/en/latest/security) before deploying. You need a Quater app
with routes declared and production hostnames ready.

## Development

Use `quater dev` while building locally:

```bash
quater dev main.py
```

Defaults:

- host: `127.0.0.1`
- port: `8000`
- interface: `rsgi`
- reload: enabled
- access log: enabled
- log level: `debug`

Expected output:

```text
[INFO] Starting granian
[INFO] Listening at: http://127.0.0.1:8000
```

`quater dev` sets `QUATER_ENV=development` while the app starts.

## Production

Use `quater run` unless your platform forces another server entrypoint:

```bash
quater run main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4
```

Defaults:

- interface: `rsgi`
- reload: disabled
- access log: enabled
- log level: `info`
- production safety checks: enabled

`quater run` uses [Granian](https://github.com/emmett-framework/granian).
RSGI is Granian's native interface and Quater's primary serving path.

## Production Checklist

Before going live:

- Set `allowed_hosts` to your real hostnames.
- Keep `debug=False`.
- Keep `security="strict"`.
- Keep reload off.
- Choose a worker count for your CPU and database pool.
- Decide whether `/docs` and `/openapi.json` should stay public.
- Configure `mcp_auth` before exposing MCP tools.
- Configure `cli_auth` before exposing CLI actions.
- Configure `trusted_proxies` only for proxies you control.
- Use HTTPS at the edge.

## Production Checks

`quater run` calls:

```python
app.validate_production()
```

That compiles routes and fails when:

- `debug=True`
- `security` is not `"strict"`
- `allowed_hosts` is empty
- `allowed_hosts` contains `"*"`

Example failure:

```text
Application failed to start

Production safety check failed:
- allowed_hosts must be configured
```

Fix:

```python
app = Quater(allowed_hosts=["api.example.com"])
```

Use `--allow-insecure` only in controlled preview or local environments:

```bash
quater run main:app --allow-insecure
```

## Direct Server Usage

If you run Granian, Uvicorn, Gunicorn, or another server directly, call
`app.validate_production()` after all routes are declared:

```python
from quater import Quater

app = Quater(allowed_hosts=["api.example.com"])


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


app.validate_production()
```

Direct server commands do not run `quater run` checks for you.

Granian direct command:

```bash
granian main:app --interface rsgi --host 0.0.0.0 --port 8000
```

ASGI explicit callable:

```python
asgi_app = app.asgi
```

WSGI explicit callable:

```python
wsgi_app = app.wsgi
```

## Server Options

| Option | Default in `dev` | Default in `run` | Meaning |
| --- | --- | --- | --- |
| `target` | auto-discovery | auto-discovery | App file, module, or `module:attribute`. |
| `--host` | `127.0.0.1` | `127.0.0.1` | Bind address. |
| `--port` | `8000` | `8000` | Bind port. |
| `--interface` | `rsgi` | `rsgi` | `rsgi`, `asgi`, or `wsgi`. |
| `--loop` | `auto` | `auto` | Granian loop: `auto`, `asyncio`, `rloop`, `uvloop`, or `winloop`. |
| `--workers` | `1` | `1` | Worker process count. |
| `--reload` | enabled | disabled | Reload on file changes. |
| `--access-log` | enabled | enabled | Granian access logging. |
| `--log-level` | `debug` | `info` | Server log level. |
| `--factory` | disabled | disabled | Treat the target as an app factory. |
| `--working-dir` | current directory | current directory | Import app from another directory. |

Target examples:

```bash
quater dev main.py
quater dev main:app
quater dev main:create_app --factory
quater dev --working-dir ./apps/store main:app
```

## Environment Variables

| Variable | Used by | Default | Effect |
| --- | --- | --- | --- |
| `QUATER_APP` | local CLI and server commands | unset | App import path when `--app` or target is omitted. |
| `QUATER_TOKEN` | local CLI actions | unset | Bearer token for local `cli_auth`. |
| `QUATER_HOME` | remote CLI config | `~/.quater` | Directory for `remotes.json`. |
| `QUATER_ENV` | server startup | set by `quater dev` or `quater run` | `development` or `production` during server startup. |
| `QUATER_MAX_BODY_SIZE` | app config | `2mb` | Maximum request body size. |
| `QUATER_MAX_FORM_PARTS` | app config | `1000` | Maximum number of form fields and file parts. |
| `QUATER_MAX_FORM_FIELD_SIZE` | app config | `1mb` | Maximum size for one string form field. |
| `QUATER_MAX_FILE_SIZE` | app config | `2mb` | Maximum size for one uploaded file. |
| `QUATER_UPLOAD_SPOOL_SIZE` | app config | `1mb` | Per-file size before upload data rolls to disk. |
| `QUATER_MAX_TOOL_RESPONSE_SIZE` | app config | `1mb` | Maximum MCP tool response body size. |
| `QUATER_MAX_ACTION_RESPONSE_SIZE` | app config | `1mb` | Maximum CLI action response body size. |

Environment limit values accept `b`, `kb`, `mb`, or `gb`, except
`QUATER_MAX_FORM_PARTS`, which must be a positive integer. Constructor keyword
options override environment values. If you pass an explicit `AppConfig`, Quater
uses that config as-is.

## Hosted MCP And Remote CLI

Hosted MCP and remote CLI are HTTP traffic:

- MCP: `POST /mcp`
- remote manifest: `GET /.well-known/quater-actions.json`
- remote calls: `POST /__quater__/actions/call`

These endpoints still use host checks, body limits, request ids, security
headers, and their surface auth hooks.

## What Can Go Wrong

`Could not find a Quater app file`
: Pass a target such as `main.py` or set `QUATER_APP=main:app`.

`App must be specified as module:attribute`
: Local action commands require import syntax like `main:app`.

`Granian is required to run Quater applications`
: Install Quater with server dependencies or install Granian in the environment.

`Application failed to start`
: Read the nested framework error. Quater wraps startup configuration failures
  so they appear before the server accepts traffic.

`Could not import app module 'main'`
: Fix syntax errors, import errors, or the working directory.

## Also See

- [Security](/en/latest/security): host checks, proxies, and production safety.
- [Actions and CLI](/en/latest/actions): local and remote action setup.
- [MCP](/en/latest/mcp): hosted MCP configuration.
- [Reference: Application](/en/latest/reference/application): exact app options.
