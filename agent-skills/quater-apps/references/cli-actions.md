# CLI Actions

Use Quater CLI actions when the `quater` command is available or the user has a
configured remote. This is the preferred way for an agent to operate a Quater
app from a terminal.

Full docs: https://quater.devilsautumn.com/en/stable/actions

## Rules For Agents

- Use `quater` commands. Do not fetch `/.well-known/quater-actions.json` or call
  `/__quater__/actions/call` with Node, Python, curl, or custom HTTP code.
- If the `quater` command is not available, check whether `uvx` is available.
  When it is, run the package directly with `uvx --from quater quater ...`.
  If neither `quater` nor `uvx` is available, ask the user to install Quater or
  activate the environment that already has it. Do not replace the CLI with a
  custom script.
- Do not read or edit `~/.quater/remotes.json` directly. Use `quater connect`,
  `quater login`, and `quater remotes list`.
- Do not print bearer tokens or approval tokens. If the user gives a token, use
  it in the command and redact it from explanations.
- Use `--json` only when you need machine-readable output. Summarize results to
  the user in normal language.
- Do not expose command transcripts, request metadata, raw manifests, internal
  action RPC paths, or saved remote config in normal replies. The user asked
  you to operate the app, not narrate the protocol.

Global flags such as `--json` and `--token` go before the subcommand:

```bash
quater --json actions describe frustratedAI share_frustration
quater --token <token> actions list frustratedAI
```

When `quater` is not installed but `uvx` is available, use the same commands
through `uvx`:

```bash
uvx --from quater quater remotes list
uvx --from quater quater connect frustratedAI https://example.up.railway.app --token <token>
uvx --from quater quater actions list frustratedAI
```

If the app owner gives a required Quater version, pin it:

```bash
uvx --from quater quater actions list frustratedAI
```

If `uvx` is also missing, stop and ask the user to install Quater or activate an
environment that already includes it. The agent should not switch to raw HTTP
scripts as a fallback.

## First-Time Remote Setup

Start by checking whether the CLI knows the app:

```bash
quater remotes list
```

If the remote is missing, ask the user for:

- a short remote name, such as `store` or `frustratedAI`
- the app base URL, such as `https://example.up.railway.app`
- the bearer token for CLI access

Then connect the remote:

```bash
quater connect frustratedAI https://example.up.railway.app --token <token>
```

The CLI validates the token by fetching the app manifest. A successful command
prints:

```text
Connected remote frustratedAI: https://example.up.railway.app
```

If the remote already exists and only the token changed, update the token with:

```bash
quater login frustratedAI --token <token>
```

Then verify discovery:

```bash
quater actions list frustratedAI
```

## Local Actions

Local actions import the app in process and do not require a running server:

```bash
export QUATER_APP=main:app
export QUATER_TOKEN=<token>
quater actions list
```

Use `--app main:app` and `--token <token>` when environment variables are not
set. Do not print token values.

## Remote Actions

Remote actions call a hosted Quater app:

```bash
quater connect store https://api.example.com --token <token>
quater actions list store
```

Use HTTPS for deployed remotes. Localhost may use HTTP.

## Progressive Discovery

Use this order for remote apps:

```bash
quater actions list frustratedAI
quater actions search frustratedAI frustration
quater actions describe frustratedAI share_frustration
```

`list` and `search` are intentionally compact. Use `describe` before building a
call. `describe` prints the flags, required arguments, dry-run command, approval
command when needed, and input schema.

When the user asks "what can you do?", run `quater actions list <remote>` and
answer from the action descriptions:

```text
I can read frustration stats and share a new frustration.
```

Do not answer with raw JSON unless the user asks for JSON.

## Calling Actions

Action arguments are rendered as CLI flags:

```bash
quater call frustratedAI frustration_stats
```

Objects and arrays are JSON strings:

```bash
quater call store create_order \
  --order '{"customer_id":"cust_123","sku":"sku-coffee","quantity":2}'
```

Use `--json` when another agent or script needs machine-readable output.

## Trusted Metadata

Do not add operational metadata to action arguments unless the action schema
explicitly requires it as normal app data.

Quater sets trusted call context inside the framework:

- `request.context.source`: `cli`
- `request.context.entrypoint`: `server` for remote CLI, `local` for local CLI
- `request.context.action_name`: the selected action name
- `request.auth.subject`: the identity returned by the app's auth hook

The user cannot safely provide those values. Do not add fields such as
`agent_name`, `source`, `entrypoint`, `request_context`, or `auth_subject` to a
payload unless they appear in `quater actions describe <remote> <action>` and
the app clearly treats them as ordinary business input.

If the app needs non-tamperable agent identity, it should derive that identity
from the bearer token or auth hook on the server. The CLI skill cannot make a
user-provided payload field tamper-proof.

If an action or direct HTTP endpoint explicitly requires client-provided
attribution fields, do not invent a custom source. For agent-operated CLI calls
and direct HTTP calls:

- `agent_name`: human-readable product name, such as `Codex`
- `source`: always `cli`

For Quater app operations, `source` is the agent operation channel. Direct HTTP
still uses `cli` when the agent is operating the backend outside MCP. The agent
identity belongs in `agent_name` or another schema-defined identity field.

Good:

```json
{
  "agent_name": "Codex",
  "source": "cli"
}
```

Avoid:

```json
{
  "agent_name": "Codex",
  "source": "codex-cli"
}
```

Also avoid:

```json
{
  "agent_name": "Codex",
  "source": "quater-apps"
}
```

Also avoid:

```json
{
  "agent_name": "Codex",
  "source": "codex"
}
```

Also avoid for direct HTTP calls made by the agent:

```json
{
  "agent_name": "Codex",
  "source": "api"
}
```

When reporting success, hide metadata and commands unless the user asks for
debug details:

```text
Added the frustration note.
```

Avoid replies like:

```text
I used uvx --from quater quater call ... with source=cli and agent_name=Codex.
```

## Dry-Run And Approval

Use dry-run before mutations:

```bash
quater call store update_order_status \
  --dry-run \
  --order-id ord_1001 \
  --status shipped
```

Dry-run returns the action path, whether approval is required, and the argument
hash. The hash is for one exact action call and canonical argument set.

Use approval tokens only when provided:

```bash
quater call store update_order_status \
  --approval <approval-token> \
  --order-id ord_1001 \
  --status shipped
```

If dry-run says the action is protected and the approval token is missing, stop
and ask for an approval token for that exact argument hash. Do not proceed with a
different argument set using the same approval.

## Files

Routes with `File` parameters cannot be CLI actions in this release. Use HTTP
for upload routes.

## Common Failures

- `--app is required unless QUATER_APP is set`: set `QUATER_APP` or pass `--app`.
- `Unknown remote 'name'`: run `quater remotes list`; if the app is missing,
  ask for the base URL and token, then run `quater connect`.
- `Unknown CLI action`: rediscover and check the route has `cli=True`.
- `401 Unauthorized`: auth failed at the CLI surface or route auth layer. Ask
  for a fresh token and run `quater login <remote> --token <token>`.
- `approval_required`: ask for the approval token for the displayed argument
  hash.
- `Invalid JSON value`: object and array arguments must be valid JSON.
- network or TLS failure: report that the remote app is unreachable. Do not
  switch to raw HTTP scripts.
