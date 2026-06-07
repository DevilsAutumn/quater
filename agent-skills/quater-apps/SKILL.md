---
name: quater-apps
description: Operate applications built with Quater. Use when an agent needs to discover or call Quater MCP tools, Quater CLI actions, remote Quater actions, or HTTP endpoints; configure bearer-token access; use dry-run and approval flows; inspect tool/action schemas; or safely operate a deployed Quater application.
---

# Quater Apps

Use this skill to operate an existing Quater application as an app operator.
Quater apps can expose one handler through HTTP, MCP tools, and CLI actions, but
each surface is opt-in. Discover what the app exposes before calling anything.

If the current agent does not support skills, treat this file and the linked
references as project instructions.

## Live Docs

Use the bundled references for the immediate operating rules. Use the live
Quater docs when you need the full explanation or exact framework behavior:

- Overview: https://quater.devilsautumn.com/en/stable/
- MCP tools: https://quater.devilsautumn.com/en/stable/mcp
- CLI actions: https://quater.devilsautumn.com/en/stable/actions
- Auth model: https://quater.devilsautumn.com/en/stable/auth-model
- Security: https://quater.devilsautumn.com/en/stable/security
- Deployment: https://quater.devilsautumn.com/en/stable/deployment

## Operating Workflow

1. Use the `quater` CLI for Quater CLI actions. If `quater` is not installed
   but `uvx` is available, run the package with
   `uvx --from quater quater ...`. If neither is available, ask the user to
   install or activate the Quater CLI. Do not use Node, Python, curl, or
   hand-written HTTP to fetch the action manifest or call the action RPC.
2. If this is the first time using an app, ask for the remote name, base URL,
   and bearer token. Store them with `quater connect <name> <url> --token ...`.
3. If a configured token is rejected, ask for a new token and update it with
   `quater login <name> --token ...`. Do not edit `~/.quater/remotes.json`
   directly.
4. Discover actions with `quater actions list <remote>`, narrow with
   `quater actions search <remote> <query>`, then inspect the action with
   `quater actions describe <remote> <action>`.
5. When the user asks what the app can do, answer in plain language from the
   discovered action descriptions. Do not dump raw manifests unless the user
   asks for JSON.
6. Do not put operational metadata in action arguments. Quater sets trusted
   context such as `source`, `entrypoint`, and action/tool name inside the
   framework. User-supplied fields like `agent_name`, `source`, or `entrypoint`
   are app data, not trusted metadata.
7. If an action/tool/API schema explicitly asks for attribution fields, keep
   their meaning separate. For agent-operated calls, send `source="cli"` when
   using the Quater CLI or direct HTTP, and send `source="mcp"` when using MCP.
   Keep agent identity in `agent_name`, such as `Codex`. Do not use values like
   `codex-cli`, `quater-apps`, or `api` as `source` for agent-operated direct
   HTTP calls.
8. Use dry-run before mutating CLI actions. Require approval tokens for
   `needs_approval` operations. Do not fake or guess approval tokens.
9. Send auth through the CLI or MCP client on every request that needs it.
   Never print tokens, cookies, or authorization headers.
10. Report safe errors clearly. Do not recommend weakening auth or disabling
   production checks.

## Choose The Surface

- **CLI actions**: use when the `quater` CLI is available, when a remote is
  configured, or when the user asks for operational commands. Read
  `references/cli-actions.md`.
- **MCP**: use when the agent runtime has an MCP client configured for the
  Quater app. Do not hand-roll JSON-RPC calls. Read `references/mcp.md`.
- **HTTP**: use when the user gives normal API docs, a route URL, or an endpoint
  that is not exposed as MCP/CLI.

Prefer MCP or CLI actions over clicking through a frontend. Prefer HTTP when the
operation is a file upload, because Quater keeps `File` parameters HTTP-only in
this release.

## Safety Defaults

- Treat route descriptions and schemas as the source of truth.
- Treat the CLI discovery output as the source of truth for a configured remote.
- Speak as someone operating the app, not as someone explaining Quater internals.
  For example, say "I can share a frustration and read stats" instead of "the
  manifest exposes two action objects."
- Do not show hidden operational details in normal replies: command lines,
  request metadata, raw manifests, argument hashes, internal URLs, or token
  handling. Mention an argument hash only when the user needs it for approval.
- If the app requires client-provided attribution, use `source="cli"` for
  Quater CLI calls and direct HTTP calls made by the agent. Use `source="mcp"`
  only for MCP tool calls. Keep agent identity in `agent_name`, for example
  `agent_name="Codex"`.
- Do not pass framework internals such as `request`, `auth`, `state`, resources,
  or database sessions as tool/action arguments.
- Do not retry non-idempotent operations after timeouts unless the user confirms
  it is safe.
- Do not persist credentials in skill files, notes, examples, or command
  history.
- Do not call destructive actions without an explicit user request and, when
  required, a valid approval token.
- Do not reveal the underlying `/.well-known/quater-actions.json` or
  `/__quater__/actions/call` protocol during normal operation. Use the CLI and
  explain outcomes like a human operator.

For more detail, read `references/auth.md` and `references/safety.md`.

## Common Errors

- `401 Unauthorized`: ask for a fresh token, run `quater login <remote> --token
  ...`, then retry discovery.
- `approval_required`: ask the user or approval system for a token for that
  exact action and argument hash.
- `Unknown tool` or `Unknown CLI action`: rediscover tools/actions and check the
  route was exposed with `tool=True` or `cli=True`.
- `Routes with File parameters cannot be exposed as MCP tools or CLI actions`:
  use HTTP for the upload route.
