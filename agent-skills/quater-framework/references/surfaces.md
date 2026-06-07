# HTTP, MCP, And CLI Surfaces

Quater routes are normal HTTP routes first. MCP and CLI exposure are explicit
opt-ins.

Full docs:

- Surfaces: https://quater.devilsautumn.com/en/stable/surfaces
- MCP tools: https://quater.devilsautumn.com/en/stable/mcp
- CLI actions: https://quater.devilsautumn.com/en/stable/actions
- Auth model: https://quater.devilsautumn.com/en/stable/auth-model

```python
@app.get(
    "/orders/{order_id}",
    tool=True,
    cli=True,
    auth=authenticate,
    description="Fetch one order by id.",
)
async def get_order(order_id: str) -> dict[str, str]:
    return {"order_id": order_id}
```

## HTTP

HTTP routes are public unless the route or group declares `auth=`.

## MCP

Use `tool=True` to expose a route as an MCP tool. Tool routes require:

- `mcp_auth` on `Quater(...)`
- a useful `description=...` or handler docstring

`mcp_auth` protects the MCP transport. Route `auth=` still protects the handler.
Both can run for one tool call.

## CLI

Use `cli=True` to expose a route as a CLI action. CLI routes require:

- `cli_auth` on `Quater(...)`
- a useful `description=...` or handler docstring

`cli_auth` protects local and remote action discovery and execution. Route
`auth=` still protects the handler.

## Approval

Use `needs_approval=True` for sensitive MCP/CLI mutations:

```python
app = Quater(
    mcp_auth=authenticate,
    cli_auth=authenticate,
    action_approval=approve_action,
)
```

Approval is not auth. Auth identifies the caller. Approval confirms one exact
operation and argument set should run.

## File Upload Rule

Routes with `File` parameters cannot be exposed as MCP tools or CLI actions in
this release. Keep uploads HTTP-only or split the workflow:

1. HTTP upload stores a file and returns a file reference.
2. MCP/CLI action operates on the file reference.

## Common Setup Errors

- `MCP tools require mcp_auth`: add `mcp_auth=...`.
- `CLI actions require cli_auth`: add `cli_auth=...`.
- `Externally callable routes require a name`: name anonymous handlers before
  exposing them.
- `needs_approval requires tool=True or cli=True`: approval only applies to
  external tool/action surfaces.
