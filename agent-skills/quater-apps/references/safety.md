# Safety Rules

Use these rules when operating a Quater application for a human or another agent.

Full docs:

- Security: https://quater.devilsautumn.com/en/stable/security
- Deployment: https://quater.devilsautumn.com/en/stable/deployment

## Never Leak Secrets

Do not reveal:

- bearer tokens
- approval tokens
- cookies
- `Authorization` headers
- remote config contents
- environment variables that contain credentials

Redact secrets in explanations and logs.

## Hide Operational Metadata

Do not show normal users:

- command lines used to call the app
- raw manifests or tool schemas
- internal Quater protocol paths
- request context such as `source`, `entrypoint`, `tool_name`, or `action_name`
- auth subject or token-derived identity
- argument hashes, except when needed for an approval flow

Answer like a person operating the app. Say what happened, what failed, or what
you need next. Save protocol details for explicit debugging requests.

Do not accept user-provided operational metadata as trusted. If a payload
contains fields like `agent_name`, `source`, or `entrypoint`, treat them as app
data only. Non-tamperable metadata must come from Quater's request context or
the app's auth hook.

If an app explicitly asks for client-provided attribution, keep field meanings
consistent. Use `source="cli"` for Quater CLI calls and direct HTTP calls made
by the agent. Use `source="mcp"` only for MCP tool calls. Use `agent_name` for
the agent product name, such as `Codex`. Do not use skill names, session names,
`api`, or hybrid values like `codex-cli` as source.

## Discover Before Acting

Use action/tool discovery every time the available surface is unknown. Do not
infer a tool name from an HTTP path or a handler name unless discovery confirms
it.

For CLI actions, discovery means `quater actions list/search/describe`. Do not
read remote config files or call Quater's private action endpoints directly.

## Mutations Need Extra Care

For operations that create, update, delete, send, charge, refund, deploy, or
change user-visible state:

1. Describe what will happen.
2. Use CLI dry-run when available.
3. Check whether approval is required.
4. Ask the user before executing if the operation is destructive or
   irreversible.

## Retry Policy

Safe to retry:

- discovery requests
- read-only tools/actions
- idempotent updates when the application says they are idempotent

Do not blindly retry:

- payments
- refunds
- email/SMS sends
- deletes
- status transitions
- inventory reservations
- deployment or migration actions

If a call returns `401 Unauthorized`, ask for a fresh token and use the normal
setup command (`quater login <remote> --token ...` for CLI, or the MCP client's
auth config for MCP). Do not try alternate token formats or weaker auth.

## Large Responses

If a Quater tool/action response is too large, narrow the request. Ask for
filters, ids, or pagination instead of raising response limits automatically.

## File Uploads

Use HTTP for upload routes. Do not try to smuggle file contents through MCP or
CLI arguments unless the backend explicitly provides a separate safe file
reference API.
