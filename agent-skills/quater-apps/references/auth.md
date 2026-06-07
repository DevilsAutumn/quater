# Auth Model

Quater has layered auth. Keep the layers separate.

Full docs:

- Auth model: https://quater.devilsautumn.com/en/stable/auth-model
- Security: https://quater.devilsautumn.com/en/stable/security

## MCP

`mcp_auth` protects the MCP surface:

- `initialize`
- `tools/list`
- `tools/call`
- `/mcp/docs`

Route `auth=` protects the selected handler after a tool call resolves to a
route.

Both gates can run for one tool call. If either denies, do not call the handler.

## CLI

`cli_auth` protects local and remote CLI discovery and calls:

- `actions list`
- `actions search`
- `actions describe`
- dry-run
- action execution

Route `auth=` still protects the handler.

For remote CLI access, configure or refresh the token through the CLI:

```bash
quater connect <remote> <url> --token <token>
quater login <remote> --token <token>
```

Do not edit `~/.quater/remotes.json` by hand. The CLI stores only remote
connection details with restricted file permissions and fetches discovery data
when actions are inspected.

## HTTP

Normal HTTP routes are public unless the route or route group declares `auth=`.
Do not assume MCP or CLI auth protects normal HTTP requests.

## Approval

Auth identifies the caller. Approval confirms a specific sensitive operation
should run for that caller and argument set.

`needs_approval=True` is an extra gate for MCP tools and CLI actions. It is not a
replacement for auth.

## Agent Rules

- Send credentials only through the configured auth mechanism.
- Do not log or summarize tokens.
- Do not downgrade from route auth to surface auth.
- If auth fails, report denial and stop.
- If the user asks to bypass auth, refuse the bypass and suggest configuring the
  backend correctly.
