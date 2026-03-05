# Manobot

Multi-agent management layer built on top of [nanobot](https://github.com/HKUDS/nanobot).

Manobot adds agent registry/configuration, routing rules, and operational tooling while reusing nanobot's core agent loop, channels, tools, and provider stack.

## Project Status

- Agent management CLI is implemented (`manobot agents ...`).
- Agent config/schema extensions are implemented in `nanobot/config/schema.py`.
- Agent/binding resolution utilities are implemented in `manobot/agents/*` and `manobot/bindings/*`.
- Multi-agent runtime routing in `manobot gateway` is wired: agent pool, message router, per-agent sessions/memory, and parallel dispatch are operational.

## Repository Layout

```text
manobot/
├── nanobot/                  # Upstream nanobot core
├── manobot/                  # Multi-agent management layer
│   ├── agents/               # Agent scope, registry, pool, init/migration
│   ├── bindings/             # Channel-to-agent routing logic
│   └── cli/                  # manobot CLI commands
├── bridge/                   # WhatsApp bridge (Node.js)
├── scripts/
│   └── sync-upstream.sh      # Upstream sync helper
└── tests/                    # Upstream nanobot tests
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

This repo installs two CLIs:

- `nanobot` (upstream single-agent CLI)
- `manobot` (multi-agent management CLI)

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

4. Start gateway:

```bash
manobot gateway --port 18790
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
      "provider": "auto",
      "maxTokens": 8192,
      "temperature": 0.1
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
        "model": "deepseek/deepseek-coder"
      }
    ],
    "bindings": [
      {
        "agentId": "coder",
        "match": {
          "channel": "telegram",
          "peerType": "group",
          "peerId": "-100123456789"
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

More complete example: `examples/multi-agent-config.json`.

## Agent Isolation

Per-agent state is stored under:

- `~/.manobot/agents/<agent_id>/memory/`
- `~/.manobot/agents/<agent_id>/sessions/`
- `~/.manobot/agents/<agent_id>/workspace/`

## CLI Reference

### Top-level

```bash
manobot version
manobot init
manobot status
manobot gateway --port 18790
manobot sync
```

### Agent management

```bash
manobot agents list [--json]
manobot agents show <agent_id> [--json]
manobot agents add <agent_id> [--name ...] [--workspace ...] [--model ...] [--default]
manobot agents delete <agent_id> [--force]
manobot agents set-default <agent_id>
manobot agents bindings [--json]
manobot agents bind <agent_id> --channel <channel> [--peer-type ...] [--peer-id ...]
```

## Upstream Sync Workflow

Recommended remotes:

- `manobot`: your fork
- `upstream`: `https://github.com/HKUDS/nanobot.git`

Check and merge upstream updates:

```bash
bash scripts/sync-upstream.sh
```

## Test and Lint

```bash
# run tests
uv run --extra dev pytest

# matrix tests require optional matrix dependencies
uv run --extra dev pytest --ignore=tests/test_matrix_channel.py

# lint
uv run --extra dev ruff check .
```

## Docker

```bash
docker build -t manobot .
docker run -d --name manobot-gateway -p 18790:18790 -v ~/.manobot:/root/.manobot manobot gateway
```

## Known Limitations

- Per-agent MCP server configuration is not yet supported (all agents share the global MCP config).
- Cron jobs always execute through the default agent.

## License

MIT. See `LICENSE`.
