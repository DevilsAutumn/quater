# MCP Access

Use MCP when the user gives a Quater MCP URL or asks an agent to call Quater
tools through an MCP-capable runtime. Do not hand-write JSON-RPC requests with
Node, Python, curl, or custom HTTP unless the user explicitly asks for protocol
debugging.

Full docs: https://quater.devilsautumn.com/en/stable/mcp

Quater's MCP endpoint is normally:

```text
https://example.com/mcp
```

Local development may use:

```text
http://127.0.0.1:8000/mcp
```

## Auth Rules

Configure the MCP client to send bearer auth on every MCP HTTP request:

```json
{
  "headers": {
    "Authorization": "Bearer <token>"
  }
}
```

Do not treat `initialize` as login. Quater does not create an MCP session from
`initialize`. If the token expires, the next request fails.

If the user has not configured the MCP client yet, ask for:

- the MCP URL, usually `https://example.com/mcp`
- the bearer token
- the client they are using, because MCP config shape varies by client

The generic shape is:

```json
{
  "mcpServers": {
    "frustratedAI": {
      "url": "https://example.com/mcp",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

After setup, use the MCP tools exposed by the host agent. Do not tell the user
about JSON-RPC internals during normal operation.

## Trusted Metadata

Do not add operational metadata to tool arguments unless the tool schema
explicitly requires it as normal app data.

Quater sets trusted MCP context inside the framework:

- `request.context.source`: `mcp`
- `request.context.entrypoint`: `server`
- `request.context.tool_name`: the selected tool name
- `request.auth.subject`: the identity returned by the app's auth hook

The user cannot safely provide those values. Do not add fields such as
`agent_name`, `source`, `entrypoint`, `request_context`, or `auth_subject` to
tool arguments unless they appear in the discovered tool schema and the app
clearly treats them as ordinary business input.

If the app needs non-tamperable agent identity, it should derive that identity
from the bearer token or auth hook on the server. The MCP skill cannot make a
user-provided argument tamper-proof.

If the tool schema explicitly requires client-provided attribution fields, do
not invent a custom source. For MCP tool calls:

- `agent_name`: human-readable product name, such as `Codex`
- `source`: always `mcp`

The source is the access surface, not the agent name, skill name, command name,
or current session. Do not use `codex-mcp`, `codex-cli`, `quater-apps`, or
`codex` as `source`.

## Discovery Before Call

Use `tools/list` first. Then call only tool names returned by the server.
When the user asks what the app can do, summarize the tool descriptions in
plain language instead of dumping raw schemas.

Tool schemas are generated from the route handler's public inputs:

- path parameters
- query parameters
- header and cookie parameters
- JSON body parameters
- form fields

Injected resources, request objects, auth state, app state, and framework
internals are not caller arguments.

## Calling Tools

Use `tools/call` with arguments that match the discovered `inputSchema`.

Do not add extra fields. Quater schemas use `additionalProperties: false` where
possible.

## Approval

For approval-protected tools, send the approval token in `_meta`:

```json
{
  "name": "update_order_status",
  "arguments": {
    "order_id": "ord_1001",
    "status": "shipped"
  },
  "_meta": {
    "approvalToken": "<approval-token>"
  }
}
```

If the server returns `approval_required`, report the action name and argument
hash. Do not guess approval tokens.

## Files

Quater does not expose `File` parameters as MCP tools in this release. Use HTTP
for file upload routes.

## Error Handling

- `401 Unauthorized`: auth failed at the MCP surface or route auth layer.
  Ask for a fresh token and update the MCP client config. Do not retry with a
  guessed token.
- `Invalid MCP Origin`: browser origin is not allowed.
- `Unsupported protocol version`: retry with a supported MCP protocol version or
  omit the version header.
- `Tool not found`: rediscover tools and check the route is exposed.
- `Tool response too large`: ask the user whether to narrow the query or use a
  different endpoint.
