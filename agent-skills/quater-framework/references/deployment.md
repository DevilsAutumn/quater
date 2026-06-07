# Deployment

Use Quater's CLI for local development and production startup.

Full docs:

- Deployment: https://quater.devilsautumn.com/en/stable/deployment
- Security: https://quater.devilsautumn.com/en/stable/security

## Development

```bash
quater dev main.py
```

`quater dev` uses Granian with RSGI by default, enables reload, and sets
`QUATER_ENV=development` while loading the app.

## Production

```bash
quater run main.py \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 2 \
  --no-reload
```

`quater run` performs production safety checks unless `--allow-insecure` is
used. Do not use `--allow-insecure` for real production traffic.

## Server Interface

Prefer RSGI unless the platform requires ASGI or WSGI:

```bash
quater run main.py --interface rsgi
quater run main.py --interface asgi
quater run main.py --interface wsgi
```

## Environment Variables

Useful runtime variables:

- `QUATER_APP`: app import path when no target is supplied.
- `QUATER_ENV`: set by `quater dev` or `quater run`.
- `QUATER_MAX_BODY_SIZE`: maximum request body size.
- `QUATER_MAX_FORM_PARTS`: maximum number of form fields and file parts.
- `QUATER_MAX_FORM_FIELD_SIZE`: maximum size for one string form field.
- `QUATER_MAX_FILE_SIZE`: maximum size for one uploaded file.
- `QUATER_UPLOAD_SPOOL_SIZE`: upload spool threshold.
- `QUATER_MAX_TOOL_RESPONSE_SIZE`: maximum MCP tool response body size.
- `QUATER_MAX_ACTION_RESPONSE_SIZE`: maximum CLI action response body size.

Size values accept `b`, `kb`, `mb`, and `gb`.

## Production Checklist

- Set `allowed_hosts` to deployed hostnames.
- Keep `debug=False`.
- Keep `security="strict"` unless there is a narrow local reason.
- Configure CORS only for browser clients that need it.
- Configure `mcp_allowed_origins` for browser MCP clients.
- Protect `tool=True` routes with `mcp_auth`.
- Protect `cli=True` routes with `cli_auth`.
- Keep sensitive handlers protected with route or group `auth=`.
- Turn off reload in production.
