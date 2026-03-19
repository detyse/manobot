# Manobot

> **This is a wrapper project for [nanobot](https://github.com/HKUDS/nanobot).**
>
> Manobot extends nanobot with multi-instance management capabilities. The core agent functionality
> comes from the upstream [nanobot](https://github.com/HKUDS/nanobot) project. Please refer to the
> upstream repository for the core features, documentation, and contributions.

Manobot manages multiple nanobot agent instances as isolated subprocesses. Each agent runs as an independent nanobot process with its own workspace, memory, sessions, and channel configuration. Manobot handles configuration generation, process lifecycle, health monitoring, and CLI interaction.

## How It Works

```
manobot gateway
  |
  +-- agent "assistant" (subprocess, port 18791)
  |     nanobot agent loop + channels + HTTP API
  |
  +-- agent "coder" (subprocess, port 18792)
  |     nanobot agent loop + channels + HTTP API
  |
  +-- health monitor (auto-restart on crash)
```

- `manobot gateway` acts as a supervisor: it spawns each configured agent as a separate `python -m mano.core.runner` process.
- Each agent gets a generated nanobot-format config with its own channel configuration.
- Agents expose an HTTP API (`/api/health`, `/api/chat`, `/api/stop`) on `127.0.0.1`.
- The CLI communicates with running agents via HTTP, or can run an agent directly in-process with `--direct`.

## Repository Layout

```text
manobot/
├── nanobot/                  # Upstream nanobot core (synced from upstream)
├── mano/                     # Multi-instance management layer
│   ├── agents/               # Agent init/migration helpers
│   ├── core/                 # Core infrastructure
│   │   ├── state.py          # Process state persistence (~/.manobot/state/)
│   │   ├── config_gen.py     # Per-agent config generator
│   │   ├── runner.py         # Subprocess entry point (nanobot + HTTP API)
│   │   ├── process_manager.py# Subprocess lifecycle management
│   │   ├── health.py         # Health monitor with auto-restart
│   │   └── scope.py          # Agent scope resolution
│   └── cli/                  # CLI commands
│       ├── main.py           # Top-level commands (gateway, agent, status)
│       └── agents.py         # Agent management subcommands
├── bridge/                   # WhatsApp bridge (Node.js)
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

1. Initialize manobot (creates `~/.manobot` state and migrates config if needed):

```bash
manobot init
```

2. Configure your model/provider credentials in `~/.nanobot/config.json`.

3. Manage agents:

```bash
manobot agents list
manobot agents add coder --name "Code Assistant" --model deepseek/deepseek-coder
manobot agents set-default coder
```

4. Start the supervisor (launches all agents as subprocesses):

```bash
manobot gateway
```

5. Check status:

```bash
manobot status
```

6. Chat with a running agent:

```bash
# via HTTP to a running subprocess (requires gateway)
manobot agent -m "Hello"
manobot agent --agent coder -m "Write a hello world"

# interactive mode
manobot agent

# in-process mode (no gateway needed)
manobot agent --direct -m "Hello"
```

## Configuration

Manobot extends nanobot config in `~/.nanobot/config.json`.

Minimal example:

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.manobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192
    },
    "list": [
      {
        "id": "assistant",
        "default": true,
        "name": "Main Assistant"
      },
      {
        "id": "coder",
        "name": "Code Assistant",
        "workspace": "~/projects",
        "model": "deepseek/deepseek-coder",
        "channels": {
          "telegram": {
            "enabled": true,
            "token": "CODER_BOT_TOKEN",
            "allowFrom": []
          }
        }
      }
    ]
  },
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-..."
    }
  }
}
```

### Per-Agent Channels

Each agent can have its own `channels` configuration with independent credentials:

- If an agent has a `channels` field, it uses that config exclusively (its own bot tokens).
- If an agent has no `channels` field, it inherits the global `channels` config.
- Same-token multi-instance is not supported; each agent that needs a channel must use its own bot/token.

## Agent Isolation

Each agent subprocess has fully isolated:

- **Process**: Separate OS process with its own event loop
- **Config**: Generated nanobot-format `config.json` under `~/.manobot/agents/<id>/`
- **Memory**: `~/.manobot/agents/<id>/memory/`
- **Sessions**: `~/.manobot/agents/<id>/sessions/`
- **Workspace**: Configurable per-agent
- **Channels**: Per-agent configuration or inherited from global

## CLI Reference

### Top-level

```bash
manobot version                           # Show version info
manobot init [--force]                    # Initialize manobot environment
manobot status                            # Show supervisor and agent process status
manobot gateway [--base-port 18791]       # Start supervisor (all agents)
manobot gateway --agent coder             # Start single agent only
manobot agent -m "message"                # Chat via HTTP (requires gateway)
manobot agent --direct -m "message"       # Chat in-process (no gateway needed)
manobot sync                              # Sync with upstream nanobot
```

### Agent management

```bash
manobot agents list [--json]
manobot agents show <id> [--json]
manobot agents add <id> [--name ...] [--workspace ...] [--model ...] [--default]
manobot agents delete <id> [--force]
manobot agents set-default <id>
manobot agents start <id>                 # Start single agent subprocess
manobot agents stop <id>                  # Stop agent subprocess
manobot agents restart <id>               # Restart agent subprocess
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

- Per-agent MCP server configuration is not yet supported (all agents share the global MCP config).
- Cron jobs always execute through the default agent.

## License

MIT. See `LICENSE`.
