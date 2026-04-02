# Manobot - Multi-Agent Management Layer

This project extends [nanobot](https://github.com/HKUDS/nanobot) with multi-agent management capabilities.

## Project Structure

```text
manobot/
├── agent/                    # Upstream nanobot runtime package used at runtime
│   ├── agent/                # Agent loop and tool execution
│   ├── channels/             # Message platform integrations
│   ├── config/               # Configuration schema and loaders
│   └── ...
│
├── mano/                     # Multi-agent management layer
│   ├── agents/
│   │   ├── init.py           # Bootstrap ~/.manobot and the registry
│   │   ├── onboard.py        # Create/refresh standalone agent configs
│   │   └── registry.py       # Registered agent IDs + default selection
│   ├── core/
│   │   ├── process_manager.py# Agent subprocess lifecycle + runner logs
│   │   ├── runner.py         # Subprocess entry point (nanobot + HTTP API)
│   │   ├── scope.py          # Agent scope resolution
│   │   └── state.py          # Process state persistence (~/.manobot/state/)
│   └── cli/
│       ├── main.py           # Top-level CLI entry point and shortcuts
│       ├── agents.py         # Agent management commands
│       └── channels.py       # Per-agent channel helpers
│
├── bridge/                   # WhatsApp bridge (Node.js)
└── nanobot/                  # Upstream repo mirror/reference for sync work
```

---

## Git Upstream Sync Guide

Manobot is designed to stay in sync with the original nanobot repository while maintaining the custom multi-agent layer in `mano/`.

### Initial Setup

```bash
# 1. Clone manobot (your fork)
git clone git@github.com:YOUR_USERNAME/manobot.git
cd manobot

# 2. Rename origin to your own remote
git remote rename origin manobot

# 3. Add nanobot upstream
git remote add upstream https://github.com/HKUDS/nanobot.git

# 4. Verify remotes
git remote -v
```

### Sync with Upstream Nanobot

When nanobot releases new updates:

```bash
# 1. Fetch upstream changes
git fetch upstream

# 2. Check what's new
git log HEAD..upstream/main --oneline

# 3. Merge upstream into your branch
git checkout main
git merge upstream/main

# 4. Resolve conflicts if any

# 5. Push to your manobot remote
git push manobot main
```

### Handling Merge Conflicts

Most conflicts will be in files that adapt nanobot runtime behavior for isolated agents:

| File | Strategy |
|------|----------|
| `agent/config/schema.py` | Keep manobot-specific schema fields while merging upstream schema changes |
| `agent/channels/**/*.py` | Merge carefully when channel behavior diverges from upstream |
| `mano/**/*.py` | Manobot-only code; keep local behavior |
| `README.md`, `AGENTS.md`, `_docs/**/*.md` | Update docs whenever CLI or config flow changes |
| `pyproject.toml` | Preserve both runtime dependencies and the `manobot` entry point |

### Branch Strategy (Recommended)

```text
main (your development)
│
├── upstream-sync     # Track upstream/main exactly
│
└── feature/*         # Your feature branches
```

### Automated Sync Script

Use `scripts/sync-upstream.sh`:

```bash
bash scripts/sync-upstream.sh
```

---

## Multi-Agent Configuration

### Registry + Standalone Configs

Manobot no longer generates temporary per-agent configs on startup. Each agent owns a standalone config file:

- Registry: `~/.manobot/agents/registry.json`
- Config: `~/.manobot/agents/<agent_id>/config.json`
- Logs: `~/.manobot/agents/<agent_id>/logs/runner.log`

Each standalone config contains exactly one `agents.list` entry.

Example:

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.manobot/agents/assistant/workspace",
      "model": "anthropic/claude-sonnet-4-20250514",
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
    "telegram": {
      "enabled": true,
      "token": "BOT_TOKEN",
      "allowFrom": []
    }
  }
}
```

### Agent Isolation

Each agent has isolated:

- **Config**: `~/.manobot/agents/{agent_id}/config.json`
- **Logs**: `~/.manobot/agents/{agent_id}/logs/runner.log`
- **Memory**: `~/.manobot/agents/{agent_id}/memory/`
- **Sessions**: `~/.manobot/agents/{agent_id}/sessions/`
- **Workspace**: Configurable per-agent

---

## Deployment

### Auto-Initialization

When manobot starts, it automatically ensures the registry exists and a default agent is selected:

```bash
# First run - bootstraps ~/.manobot and creates assistant if no agents exist
manobot gateway
```

Behavior:

- If `~/.manobot/agents/registry.json` already exists, manobot uses it.
- If isolated agent configs already exist on disk, manobot registers them automatically.
- If no isolated agent exists yet, manobot creates a default `assistant`.

### Docker Deployment

```bash
docker build -t manobot .

docker run -d \
  --name manobot-gateway \
  -p 18790:18790 \
  -v ~/.manobot:/root/.manobot \
  manobot gateway
```

### Migration from Older Nanobot Setups

Manobot does not auto-import `~/.nanobot/config.json` into isolated agent configs anymore.

If you are moving from an older single-config setup:

```bash
manobot init
manobot onboard assistant
```

Then copy provider/channel settings from the old `~/.nanobot/config.json` into `~/.manobot/agents/assistant/config.json` as needed.

---

## CLI Commands

```bash
# Bootstrap
manobot init
manobot onboard <agent_id>

# Agent management
manobot list
manobot show <agent_id>
manobot add <agent_id> --name "Display Name" --workspace ~/path
manobot default <agent_id>
manobot delete <agent_id>

# Runtime control
manobot start <agent_id>
manobot stop <agent_id>
manobot restart <agent_id>
manobot logs <agent_id> --follow
manobot status
manobot gateway --agent <agent_id>

# Chat shortcuts
manobot agent --agent coder -m "hi"
manobot coder -m "hi"
manobot tui

# Per-agent channel helpers
manobot channels status --agent coder
manobot coder channels status
manobot channels login --agent coder
```

Nested compatibility commands under `manobot agents ...` still exist, including `manobot agents set-default`.

---

## Development Guidelines

- Prefer putting multi-agent behavior in `mano/`
- Modify `agent/` only when the shared nanobot runtime itself needs adaptation for isolated agents
- Keep the standalone config model intact; do not reintroduce generated per-agent config files
- Update `README.md`, `AGENTS.md`, and `_docs/` whenever CLI flows, config paths, or runtime directories change
- Use `nanobot/` as an upstream reference during sync work; runtime imports come from `agent/` and `mano/`
