# Quater Agent Skills

This folder contains portable agent skills for Quater.

- `quater-apps`: operate deployed or local Quater applications through MCP, CLI
  actions, or HTTP.
- `quater-framework`: build, test, and deploy applications with the Quater
  Python framework.

The full Quater documentation lives at:

```text
https://quater.devilsautumn.com/en/stable/
```

Use the docs as the canonical reference. The skill references are intentionally
short so agents can load the exact operating guidance they need without pulling
the whole manual into context.

Each skill is a standalone folder with `SKILL.md` and optional references. Skill
aware agents can install the folder directly from this repository. Other agents
can use the same `SKILL.md` content as project or system instructions.

Example install paths for skill-aware agents:

```text
https://github.com/DevilsAutumn/quater/tree/main/agent-skills/quater-apps
https://github.com/DevilsAutumn/quater/tree/main/agent-skills/quater-framework
```

For agents that do not have a formal skill system, copy the relevant
`SKILL.md` into the agent's project instructions and let the agent read files
from that skill's `references/` folder only when needed.

Do not put credentials in these skills. Provide MCP URLs, tokens, remotes, and
environment variables through the agent runtime or the user's secure config.
