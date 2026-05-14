# Actions And CLI

This page explains how Quater exposes selected backend operations as local and
remote CLI actions.

## Prerequisites

Read the [Quickstart](/en/latest/quickstart) first. You need an app with at
least one route declared with `cli=True` and a `cli_auth` hook on `Quater(...)`.

## Why Actions Exist

Production work does not always happen through the product UI. During an
incident, a rollout, or a support case, someone often needs to run a backend
operation directly.

Teams usually solve that with admin scripts. Over time those scripts become a
second version of the app: another auth path, another argument parser, and
another place for business logic to drift.

Quater actions keep the operation on the route. The CLI surface handles
discovery, argument parsing, dry-run, approval, and remote transport. The route
handler still performs the work.

Actions are not a replacement for shell scripts that manage your machine. They
are for app operations that already belong to your backend and should be safe to
run locally, remotely, or from an agent-controlled workflow.

## A Runnable Action

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

Run local discovery:

```bash
export QUATER_APP=main:app
export QUATER_TOKEN=admin-token
quater actions list
```

Expected output:

```text
get_order
  Fetch one order by id.
```

Run the action:

```bash
quater call get_order --order-id ord_1001
```

Expected output:

```json
{
  "order_id": "ord_1001",
  "subject": "admin",
  "source": "cli",
  "entrypoint": "local"
}
```

## CLI Command Reference

Global options must appear before the command.

| Command | Flags | What it does |
| --- | --- | --- |
| `quater dev [target]` | `--host`, `--port`, `--interface`, `--loop`, `--workers`, `--reload/--no-reload`, `--access-log/--no-access-log`, `--log-level`, `--factory`, `--working-dir` | Runs the app for development with reload enabled by default. |
| `quater run [target]` | Same as `dev`, plus `--allow-insecure` | Runs the app with production-style defaults and production checks. |
| `quater actions list [remote]` | `--app`, `--token`, `--header`, `--json` | Lists action names and descriptions. |
| `quater actions search [remote] <query>` | `--app`, `--token`, `--header`, `--json` | Searches action names, descriptions, methods, and paths. |
| `quater actions describe [remote] <action>` | `--app`, `--token`, `--header`, `--json` | Shows the selected action schema and usage. |
| `quater call [remote] <action>` | `--dry-run`, `--approval`, action flags, plus global auth flags | Calls one local or remote action. |
| `quater connect <name> <url>` | `--token`, `--json` | Saves a remote app. |
| `quater login <name>` | `--token`, `--json` | Replaces a remote token. |
| `quater remotes list` | `--json` | Lists saved remotes. |

Local commands use `--app` or `QUATER_APP`. Local bearer tokens use `--token` or
`QUATER_TOKEN`.

```bash
quater --app main:app --token admin-token actions list
```

You can pass custom headers when `cli_auth` does not use bearer tokens:

```bash
quater --app main:app --header "X-Operator: admin" actions list
```

Quater rejects `--token` together with an explicit `Authorization` header:

```text
Use either --token or an Authorization header
```

## Local Vs Remote Flow

Local actions import the app in process. Remote actions call a hosted Quater app
over HTTP.

```mermaid
flowchart TB
    local["local CLI\nquater call get_order"]
    import_app["framework: import app\nQUATER_APP or --app"]
    remote["remote CLI\nquater call store get_order"]
    manifest["framework: GET /.well-known/quater-actions.json"]
    rpc["framework: POST /__quater__/actions/call"]
    cli_auth["your code: cli_auth"]
    registry["framework: action registry"]
    route_auth["your code: route auth="]
    bind["framework: bind action args"]
    approval["your code: approval hook\nwhen needed"]
    handler["your code: handler"]
    output["framework: JSON output"]

    local --> import_app --> cli_auth --> registry
    remote --> manifest --> cli_auth
    remote --> rpc --> cli_auth --> registry
    registry --> route_auth --> bind --> approval --> handler --> output
```

`cli_auth` protects local action discovery, local calls, remote manifest
discovery, and remote calls.

## Progressive Discovery

`actions list` and `actions search` return only action names and descriptions.
That keeps a large app readable for humans and smaller for agents.

```bash
quater actions search order
```

```text
get_order
  Fetch one order by id.
update_order_status
  Update an order status.
```

Use `describe` after you choose one action:

```bash
quater actions describe update_order_status
```

```text
update_order_status
  PATCH /orders/{order_id}/status
  Update an order status.
  protected action: yes
  arguments:
    --order-id <string>  required
    --status <string>  required
  usage:
    quater call update_order_status --order-id example --status example
  dry run:
    quater call update_order_status --dry-run --order-id example --status example
  approval:
    quater call update_order_status --approval <token> --order-id example --status example
```

Machine-readable output:

```bash
quater --json actions describe update_order_status
```

```json
{
  "name": "update_order_status",
  "method": "PATCH",
  "path": "/orders/{order_id}/status",
  "needs_approval": true,
  "arguments": [
    {"name": "order_id", "required": true, "type": "string"},
    {"name": "status", "required": true, "type": "string"}
  ]
}
```

## Argument Binding

CLI argument names come from the action schema. Quater renders Python
`snake_case` names as kebab-case flags:

```python
async def get_order(order_id: str) -> dict[str, str]: ...
```

```bash
quater call get_order --order-id ord_1001
```

Scalars use normal values. Objects and arrays use JSON:

```bash
quater call create_order \
  --order '{"customer_id":"cust_123","sku":"sku-coffee","quantity":2}'
```

HTTP aliases stay on the HTTP side for `Path`, `Query`, `Header`, and `Cookie`.
`Body(alias=...)` changes the CLI and MCP body argument name because the body has
no HTTP query or header name.

## Dry Run And Argument Hashes

Dry-run exists on every action. You do not write a separate dry-run handler.

```bash
quater call update_order_status \
  --dry-run \
  --order-id ord_1001 \
  --status shipped
```

Expected output:

```text
Dry run OK: update_order_status
  PATCH /orders/ord_1001/status
  arguments hash: sha256:23c4caa787b3348045a4844ec4d45422cc07a9daea3e90cf1fa1a1ab68a9c63b
  protected action: yes
  approval token: missing
```

Quater computes the argument hash from the action name and canonical JSON
arguments. JSON object key order does not change it. Use the hash when an
approval system grants permission for one exact call, not for every call with
the same action name.

## Approval

Auth identifies the caller. Approval confirms that a sensitive operation should
run for that caller and those exact arguments.

```python
from quater import ApprovalRequest, AuthContext, AuthRequest, Quater


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    if ctx.headers.get("authorization") != "Bearer admin-token":
        return None
    return AuthContext(subject="admin")


async def approve_action(ctx: ApprovalRequest) -> bool:
    return ctx.token == "approve-ord_1001"


app = Quater(cli_auth=authenticate, action_approval=approve_action)


@app.patch(
    "/orders/{order_id}/status",
    cli=True,
    needs_approval=True,
    description="Update an order status.",
)
async def update_order_status(order_id: str, status: str) -> dict[str, str]:
    return {"order_id": order_id, "status": status}
```

Call with approval:

```bash
quater call update_order_status \
  --approval approve-ord_1001 \
  --order-id ord_1001 \
  --status shipped
```

Expected output:

```json
{
  "order_id": "ord_1001",
  "status": "shipped"
}
```

If the token is missing, Quater returns:

```json
{
  "ok": false,
  "error": {
    "code": "approval_required",
    "message": "Approval required",
    "action": "update_order_status",
    "arguments_hash": "sha256:..."
  }
}
```

## Remote Actions

Connect once:

```bash
quater connect store https://api.example.com --token admin-token
```

Expected output:

```text
Connected remote store: https://api.example.com
```

Then call the remote:

```bash
quater actions list store
quater actions describe store get_order
quater call store get_order --order-id ord_1001
```

Remote URLs must use HTTPS unless they target localhost. Quater rejects
credentials, query strings, fragments, whitespace, and malformed URLs.

Quater stores remote config at `~/.quater/remotes.json` by default with `0600`
file permissions. Set `QUATER_HOME` to use another directory.

## What Can Go Wrong

`--app is required unless QUATER_APP is set`
: Local commands need an app import path.

`Unknown CLI action`
: The action name does not exist or the route does not have `cli=True`.

`Missing value for action argument --order-id`
: Pass a value after the flag.

`Invalid JSON value for --order`
: Object and array arguments must be valid JSON.

`Approval token must not be empty`
: Pass a non-empty `--approval` value or omit the flag.

`Remote URL must use HTTPS unless it targets localhost`
: Use an HTTPS URL for deployed apps.

`Quater remote config is invalid`
: Delete or repair the file under `QUATER_HOME` or `~/.quater/remotes.json`.

## Also See

- [MCP](/en/latest/mcp): expose the same route to AI tools.
- [Security](/en/latest/security): review auth ordering and action discovery.
- [Deployment](/en/latest/deployment): understand hosted action endpoints.
- [Testing](/en/latest/testing): test actions through the in-process client.
