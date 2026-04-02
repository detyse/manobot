# Manobot

> **This is a wrapper project for [nanobot](https://github.com/HKUDS/nanobot).**
>
> Manobot extends nanobot with multi-instance management capabilities. The core agent functionality
> comes from the upstream [nanobot](https://github.com/HKUDS/nanobot) project. Please refer to the
> upstream repository for the core features, documentation, and contributions.

Manobot manages multiple nanobot agent instances as isolated subprocesses. Each agent runs as an independent nanobot process with its own workspace, memory, sessions, logs, and standalone config. Manobot handles agent onboarding, registry management, process lifecycle, health monitoring, and CLI interaction.

## How It Works

```text
manobot gateway
  |
  +-- registry (~/.manobot/agents/registry.json)
  |
  +-- agent "assistant" (subprocess, port 18791)
  |     config: ~/.manobot/agents/assistant/config.json
  |     nanobot agent loop + channels + HTTP API
  |
  +-- agent "coder" (subprocess, port 18792)
  |     config: ~/.manobot/agents/coder/config.json
  |     nanobot agent loop + channels + HTTP API
  |
  +-- health monitor (auto-restart on crash)
```

- `manobot gateway` acts as a supervisor: it spawns each registered agent as a separate `python -m mano.core.runner` process.
- `~/.manobot/agents/registry.json` stores the registered agent IDs and the default agent selection.
- Each agent reads its own config from `~/.manobot/agents/<id>/config.json`.
- Each runner writes logs to `~/.manobot/agents/<id>/logs/runner.log`.
- Agents expose an HTTP API (`/api/health`, `/api/chat`, `/api/stop`) on `127.0.0.1`.
- The CLI communicates with running agents via HTTP, or can run an agent directly in-process with `--direct`.

## Repository Layout

```text
manobot/
├── agent/                    # Upstream nanobot runtime package used at runtime
├── mano/                     # Multi-agent management layer
│   ├── agents/               # Registry, bootstrap, onboarding helpers
│   ├── core/                 # Runner, process manager, scope, state
│   └── cli/                  # Top-level CLI, agent commands, channel commands
├── bridge/                   # WhatsApp bridge (Node.js)
├── nanobot/                  # Upstream repository mirror/reference
├── scripts/
│   └── sync-upstream.sh      # Upstream sync helper
└── tests/
```

## Requirements

- Python >= 3.11
- `uv` (recommended) or `pip`
- Node.js 20 (only needed for WhatsApp bridge / Docker image build)

## Install (Development)

```bash
git clone <your-fork-or-repo-url>
cd manobot

# recommended
uv sync --extra dev

# or editable install
uv pip install -e .
```

## Quick Start

1. Initialize manobot:

```bash
manobot init
```

2. Inspect the default agent and edit its credentials:

```bash
manobot show assistant
# then edit ~/.manobot/agents/assistant/config.json
```

3. Create or refresh more isolated agents:

```bash
manobot onboard coder --workspace ~/projects
manobot add writer --name "Writer" --model openai/gpt-4o-mini
manobot default coder
```

4. Start the supervisor:

```bash
manobot gateway
```

5. Check status and logs:

```bash
manobot status
manobot logs coder
manobot logs coder --follow
```

6. Chat with agents:

```bash
# via HTTP to a running subprocess (requires gateway)
manobot agent -m "Hello"
manobot agent --agent coder -m "Write a hello world"
manobot coder -m "Write a hello world"

# interactive picker / direct chat
manobot tui
manobot tui coder

# in-process mode (no gateway needed)
manobot agent --direct -m "Hello"
```

7. Manage one agent's channels:

```bash
manobot channels status --agent coder
manobot channels login --agent coder
manobot coder channels status
manobot coder channels login
```

## Configuration

Each isolated agent keeps its own config in `~/.manobot/agents/<id>/config.json`.

Typical layout:

```text
~/.manobot/
└── agents/
    ├── registry.json
    ├── assistant/
    │   ├── config.json
    │   ├── workspace/
    │   ├── memory/
    │   ├── sessions/
    │   └── logs/runner.log
    └── coder/
        ├── config.json
        ├── workspace/
        ├── memory/
        ├── sessions/
        └── logs/runner.log
```

Notes:

- `registry.json` is the source of truth for which agents exist and which one is the default.
- Each standalone config file contains exactly one entry in `agents.list`.
- `manobot onboard <id>` and `manobot add <id>` refresh missing defaults and sync workspace templates such as `AGENTS.md` and `memory/MEMORY.md`.

Minimal standalone agent config example:

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.manobot/agents/assistant/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192
    },
    "list": [
      {
        "id": "assistant",
        "default": true,
        "name": "Main Assistant",
        "agentDir": "~/.manobot/agents/assistant",
        "workspace": "~/.manobot/agents/assistant/workspace",
        "memoryDir": "~/.manobot/agents/assistant/memory",
        "sessionsDir": "~/.manobot/agents/assistant/sessions"
      }
    ]
  },
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-..."
    }
  },
  "channels": {
    "feishu": {
      "enabled": false,
      "appId": "",
      "appSecret": "",
      "allowFrom": [],
      "groupPolicy": "mention",
      "replyToMessage": false,
      "streaming": true
    }
  }
}
```

### Channel Configuration

For isolated configs, the simplest pattern is to put channel settings in the top-level `channels` section of that agent's own config file.

- Top-level `channels` applies to that standalone agent config.
- `agents.list[0].channels` can still override the sole agent entry when needed.
- `manobot channels status --agent <id>` and `manobot <id> channels status` show the resolved channel config for one agent.
- Feishu now supports `groupPolicy`, `replyToMessage`, and `streaming` in the schema used by each isolated config.

## Agent Isolation

Each agent subprocess has fully isolated:

- **Process**: Separate OS process with its own event loop
- **Registry**: Registered independently in `~/.manobot/agents/registry.json`
- **Config**: Standalone `config.json` under `~/.manobot/agents/<id>/`
- **Logs**: Runner log at `~/.manobot/agents/<id>/logs/runner.log`
- **Memory**: `~/.manobot/agents/<id>/memory/`
- **Sessions**: `~/.manobot/agents/<id>/sessions/`
- **Workspace**: Configurable per-agent
- **Channels**: Per-agent configuration with config-wide defaults inside the same file

## CLI Reference

### Common top-level commands

```bash
manobot version
manobot init
manobot onboard <id> [--workspace PATH]
manobot list [--json]
manobot show <id> [--json]
manobot add <id> [--name ...] [--workspace ...] [--model ...] [--default]
manobot default <id>
manobot delete <id> [--force]
manobot start <id>
manobot stop <id>
manobot restart <id>
manobot logs <id> [--follow]
manobot status
manobot gateway [--base-port 18791]
manobot gateway --agent coder
manobot agent [-a <id>] [-m "message"] [--direct]
manobot <agent-id> -m "message"
manobot channels status [--agent <id>]
manobot channels login [--agent <id>]
manobot <agent-id> channels status
manobot tui [agent-id]
manobot sync
```

### Compatibility subcommands

The nested `manobot agents ...` commands remain available:

```bash
manobot agents list [--json]
manobot agents show <id> [--json]
manobot agents add <id> [--name ...] [--workspace ...] [--model ...] [--default]
manobot agents delete <id> [--force]
manobot agents set-default <id>
manobot agents start <id>
manobot agents stop <id>
manobot agents restart <id>
manobot agents logs <id> [--follow]
```

## Upstream Sync

Recommended remotes:

- `manobot`: your fork
- `upstream`: `https://github.com/HKUDS/nanobot.git`

Check and merge upstream updates:

```bash
bash scripts/sync-upstream.sh
```

## Test and Lint

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
```

## Docker

```bash
docker build -t manobot .
docker run -d --name manobot -v ~/.manobot:/root/.manobot manobot gateway
```

## Known Limitations

- Per-agent MCP server configuration is not yet supported.
- Cron jobs always execute through the default agent.

## License

MIT. See `LICENSE`.
