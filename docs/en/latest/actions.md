# Actions and CLI

Quater actions are derived from route metadata and can be called outside normal
HTTP while still using the same handler. The CLI and MCP surfaces have their own
transport auth and protocol errors, but the action call reuses handler binding,
route-level auth, response normalization, and the generated input schema.

You opt in one route at a time:

```python
from quater import AuthContext, AuthRequest, Quater, Request


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer admin-token":
        return None
    return AuthContext(subject="admin")


app = Quater(cli_auth=authenticate)


@app.get(
    "/orders/{order_id}",
    cli=True,
    description="Fetch one order by id.",
)
async def get_order(order_id: str, request: Request) -> dict[str, object]:
    assert request.auth is not None
    return {
        "order_id": order_id,
        "subject": request.auth.subject,
        "source": request.context.source,
        "entrypoint": request.context.entrypoint,
    }
```

The route is still an HTTP route:

```text
GET /orders/ord_1001
```

It also becomes a Quater action that the CLI can discover and call.

Action descriptions are required. Use `description=` or the first line of the
handler docstring. The description is what people and agents see when they list
or search actions, so write what the action is for, not just what it is named.

::: tip Why actions exist
MCP tools solve one kind of agent access, but teams also need a safe operational
CLI for the same backend workflows. Quater actions give both humans and agents a
single declared operation instead of forcing you to maintain separate admin
scripts, HTTP endpoints, and tool handlers for the same business logic.
:::

## Action Call Flow

Local and remote CLI calls reach the app differently, but after discovery they
both execute through the action registry and the same route handler.

```mermaid
flowchart TB
    local_call["Local CLI"]
    local_import["import app"]
    remote_call["Remote CLI"]
    remote_rpc["action RPC"]
    registry["action registry"]
    auth["cli_auth"]
    route_auth["route auth"]
    binding["bind args"]
    handler["handler"]

    local_call --> local_import
    remote_call --> remote_rpc
    local_import --> registry
    remote_rpc --> registry
    registry --> auth
    auth --> route_auth
    route_auth --> binding
    binding --> handler
```

## CLI Shape

The same `quater` command is used for local development, remote operations, and
server startup. The important distinction is whether the command needs to import
your app or talk to a hosted app.

| Command | What it does |
| --- | --- |
| `quater dev [target]` | Run the app locally with reload enabled. |
| `quater run [target]` | Run the app for production-style serving. |
| `quater actions list [remote]` | Show action names and descriptions. |
| `quater actions search [remote] <query>` | Search action names, descriptions, methods, and paths. |
| `quater actions describe [remote] <action>` | Show flags, schema, dry-run command, and approval command. |
| `quater call [remote] <action> [--flags]` | Execute one action. |
| `quater connect <name> <url> --token <token>` | Save a hosted app as a named remote. |
| `quater login <name> --token <token>` | Replace the stored token for a remote. |
| `quater remotes list` | Show saved remotes. |

Global options go before the command:

```bash
quater --json actions list
quater --app main:app actions list
quater --token admin-token actions list
quater --header "X-Operator: admin" actions list
```

`--json` is useful for scripts and agents. Human output is intentionally compact;
JSON output keeps the same information machine-readable.

## Local Actions

Local CLI calls import the app and run in the same Python process. They do not
need a running server, but they still go through `cli_auth`.

Set the app and token once when you are working locally:

```bash
export QUATER_APP=main:app
export QUATER_TOKEN=admin-token
quater actions list
```

`QUATER_APP` tells Quater what app to import. `QUATER_TOKEN` becomes an
`Authorization: Bearer ...` header for local CLI calls. Use this when you are
running several local commands in the same terminal.

Sample output:

```text
get_order
  Fetch one order by id.
update_order_status
  Update an order status.
```

If you prefer one-off commands, pass both values inline:

```bash
quater --app main:app --token admin-token actions list
```

You can also pass custom headers. This is useful when your `cli_auth` hook does
not use bearer tokens:

```bash
quater --app main:app --header "X-Operator: admin" actions list
```

Do not pass `--token` and an `Authorization` header together. Quater rejects
that because it would be unclear which credential should win.

Use `actions search` when the app has many actions:

```bash
quater actions search order
```

Sample output:

```text
get_order
  Fetch one order by id.
update_order_status
  Update an order status.
```

`actions list` and `actions search` intentionally return only the action name
and description. That keeps discovery readable for people and small enough for
AI agents to choose a relevant action without being flooded by schemas.

Use `--json` when another program will read the output:

```bash
quater --json actions list
```

```json
{
  "actions": [
    {
      "name": "get_order",
      "description": "Fetch one order by id."
    }
  ]
}
```

Once you know the action you want, describe it:

```bash
quater actions describe get_order
```

Sample output:

```text
get_order
  GET /orders/{order_id}
  Fetch one order by id.
  protected action: no
  arguments:
    --order-id <string>  required
  usage:
    quater call get_order --order-id example
  dry run:
    quater call get_order --dry-run --order-id example
  input schema:
{
  "type": "object",
  "properties": {
    "order_id": {
      "type": "string"
    }
  },
  "additionalProperties": false,
  "required": [
    "order_id"
  ]
}
```

`actions describe` is the detailed view. It shows the HTTP method and route,
required flags, optional flags, input schema, dry-run command, and approval
command when the action is protected.

Call the action with kebab-case flags:

```bash
quater call get_order --order-id ord_1001
```

Action argument names come from the generated input schema. Use kebab-case on
the command line even when the Python parameter is snake_case:

```python
async def get_order(order_id: str) -> dict[str, str]: ...
```

```bash
quater call get_order --order-id ord_1001
```

Boolean, number, object, and array values are parsed as JSON when possible. If an
argument is a JSON body object or array, pass it as valid JSON:

```bash
quater call create_order \
  --order '{"customer_id":"cust_123","sku":"sku-coffee","quantity":2}'
```

Unknown arguments, duplicate arguments, and missing argument values fail before
the handler runs.

::: warning Local CLI is trusted local execution
Local actions import your Python app, so app import side effects run just like
they do when starting a server. Use local CLI commands from a trusted checkout
and environment.
:::

## Remote Actions

Remote actions call a hosted Quater app through Quater's action protocol.

First connect a remote:

```bash
quater connect store https://api.example.com --token admin-token
```

Sample output:

```text
Connected remote store: https://api.example.com
```

Quater stores the remote config in the user's Quater config directory with
restricted file permissions. The token is sent as a bearer token on remote
manifest and action requests.

By default the file is:

```text
~/.quater/remotes.json
```

Set `QUATER_HOME` if you want a separate config directory for CI, tests, or a
throwaway environment:

```bash
QUATER_HOME=.quater-ci quater connect store https://api.example.com --token admin-token
```

List configured remotes:

```bash
quater remotes list
```

Sample output:

```text
store  https://api.example.com authenticated
```

Refresh or replace a stored token:

```bash
quater login store --token new-admin-token
```

Override the stored token for one command:

```bash
quater --token temporary-token actions list store
quater --token temporary-token call store get_order --order-id ord_1001
```

Discover remote actions:

```bash
quater actions list store
quater actions search store order
quater actions describe store get_order
```

Call a remote action:

```bash
quater call store get_order --order-id ord_1001
```

Sample output:

```json
{
  "ok": true,
  "status_code": 200,
  "body": {
    "order_id": "ord_1001",
    "subject": "admin",
    "source": "cli",
    "entrypoint": "server"
  }
}
```

Remote calls use the same argument style as local calls. Scalars are passed as
plain flag values. JSON body arguments are passed as JSON strings.

Machine-readable output is available with `--json`:

```bash
quater --json actions describe store get_order
```

::: tip Progressive discovery
For agents, a good flow is: list or search first, describe only the selected
action, then call it. This avoids giving the model every schema in a large
application when it only needs one action.
:::

## Remote Protocol

When an app has at least one `cli=True` route, Quater adds two internal
endpoints:

- `GET /.well-known/quater-actions.json`
- `POST /__quater__/actions/call`

Both are protected by `cli_auth`. These endpoints are what the Quater CLI uses
for remote discovery and execution.

You usually do not call those endpoints by hand. Use `quater actions ...` and
`quater call ...` so argument encoding, dry-run, approval tokens, and response
handling stay consistent.

Remote URLs must be absolute `https://` URLs unless they target localhost. Quater
also rejects remote URLs with embedded credentials, query strings, fragments, or
whitespace. Keep credentials in `--token`, not in the URL.

## Request Context

Handlers and auth hooks can tell how the route was called:

```python
@app.get("/orders/{order_id}", cli=True, description="Fetch one order by id.")
async def get_order(order_id: str, request: Request) -> dict[str, object]:
    return {
        "order_id": order_id,
        "source": request.context.source,
        "entrypoint": request.context.entrypoint,
        "action": request.context.action_name,
    }
```

Normal HTTP calls use:

```python
request.context.source == "api"
request.context.action_name is None
```

Local CLI action calls use:

```python
request.context.source == "cli"
request.context.entrypoint == "local"
request.context.action_name == "get_order"
```

Remote CLI action calls use:

```python
request.context.source == "cli"
request.context.entrypoint == "server"
request.context.action_name == "get_order"
```

`AuthRequest.context` receives the same source and entrypoint before the handler
runs. That lets one auth hook accept different credentials for normal API
calls, local operator calls, and hosted remote CLI calls.

## Dry Run

Every action supports dry-run automatically. You do not add a separate dry-run
handler.

```bash
quater call store update_order_status \
  --dry-run \
  --order-id ord_1001 \
  --status shipped
```

Sample output:

```text
Dry run OK: update_order_status
  PATCH /orders/ord_1001/status
  arguments hash: sha256:23c4caa787b3348045a4844ec4d45422cc07a9daea3e90cf1fa1a1ab68a9c63b
  protected action: yes
  approval token: missing
```

Dry-run does the safety-critical work before execution:

- runs the relevant auth hooks
- validates and binds path, query, and body arguments
- renders the HTTP method and path that would be called
- computes the action argument hash
- reports whether an approval token is needed

It does not call the handler, and it does not call the approval hook.

::: info Argument hashes
The argument hash is based on the action name and canonical JSON arguments. It
is stable for reordered JSON object keys, which makes it useful when approval is
granted out of band for one exact action call.
:::

## Approval-Protected Actions

Use `needs_approval=True` for actions that should not run just because a caller
is authenticated.

```python
from quater import ApprovalRequest, Quater


async def approve_action(ctx: ApprovalRequest) -> bool:
    return ctx.token == "approve-local"


app = Quater(
    cli_auth=authenticate,
    action_approval=approve_action,
)


@app.patch(
    "/orders/{order_id}/status",
    cli=True,
    needs_approval=True,
    description="Update an order status.",
)
async def update_order_status(order_id: str, status: str) -> dict[str, str]:
    return {"order_id": order_id, "status": status}
```

Run a dry-run first:

```bash
quater call store update_order_status \
  --dry-run \
  --order-id ord_1001 \
  --status shipped
```

Then call with an approval token:

```bash
quater call store update_order_status \
  --approval approve-local \
  --order-id ord_1001 \
  --status shipped
```

Quater does not issue approval tokens. Your `action_approval` hook decides
whether the submitted token is valid for the action, argument hash, authenticated
subject, and request context.

## CLI Auth

Any app with a `cli=True` route must be created with `cli_auth`.

```python
app = Quater(cli_auth=authenticate)
```

`cli_auth` protects:

- local action listing and local action calls
- remote action manifest discovery
- remote action calls

Use `QUATER_TOKEN` or `--token` for local bearer tokens:

```bash
export QUATER_APP=main:app
export QUATER_TOKEN=admin-token
quater actions list
```

For local actions, if your `cli_auth` hook expects another header, pass it
explicitly:

```bash
QUATER_APP=main:app quater --header "X-Operator: admin" actions list
```

For remote actions, `quater connect ... --token ...` stores the token for that
remote. Pass `--token` to a remote command only when you want to override the
stored token for that one command.

`QUATER_TOKEN` is for local CLI calls. Remote calls use the token saved for that
remote unless you pass `--token` explicitly.

Route `auth=` still protects the handler. If `cli_auth` and route `auth=` are
the same function, Quater still runs route auth against the handler route. Use
two functions when the CLI token and route-level user or scope check should be
separate.

::: warning Do not treat action discovery as public metadata
Action names, descriptions, paths, and schemas can reveal operational
capabilities. Quater requires `cli_auth` as soon as one route is exposed with
`cli=True` so that discovery is protected too.
:::

## Running The App

Quater includes a small server CLI around Granian.

During development:

```bash
quater dev
```

`quater dev` auto-discovers common app files, uses RSGI by default, enables
reload by default, and enables access logs.

In production:

```bash
quater run --host 0.0.0.0 --port 8000
```

`quater run` keeps reload off by default and runs production safety checks before
handing off to Granian. Production startup fails if debug is enabled, strict
security is off, or `allowed_hosts` is missing or contains `*`.

You can still be explicit:

```bash
quater dev main.py --port 8010
quater run main:app --interface rsgi --workers 4
```

Server targets can be:

- `main:app`
- `main.py`
- a module name such as `main`
- omitted, in which case Quater searches common files such as `main.py` and
  `app.py`

If your app is created by a factory function, use `--factory`:

```bash
quater dev main:create_app --factory
```

Use `--working-dir` when the app should be imported from another directory:

```bash
quater dev --working-dir ./sample_projects/test_app
```

Common server options:

| Option | Use |
| --- | --- |
| `--host` | Bind address. Development defaults to `127.0.0.1`. |
| `--port` | Bind port. Defaults to `8000`. |
| `--interface` | `rsgi`, `asgi`, or `wsgi`; default is `rsgi`. |
| `--workers` | Number of worker processes. |
| `--reload` / `--no-reload` | Enable or disable reload. `dev` enables it by default; `run` disables it. |
| `--access-log` / `--no-access-log` | Enable or disable request access logs. |
| `--log-level` | `debug`, `info`, `warning`, `error`, or `critical`. |
| `--loop` | Granian loop choice: `auto`, `asyncio`, `rloop`, `uvloop`, or `winloop`. |

Use `--allow-insecure` only for a controlled environment where you intentionally
want to skip production safety checks.

For direct Granian, ASGI, WSGI, reverse-proxy, and docs endpoint guidance, read
[Deployment](/en/latest/deployment).

## Related Pages

- [Quickstart](/en/latest/quickstart)
- [Deployment](/en/latest/deployment)
- [Public API](/en/latest/api)
- [MCP](/en/latest/mcp)
- [Security](/en/latest/security)
