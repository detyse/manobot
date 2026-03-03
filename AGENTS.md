# Manobot - Multi-Agent Management Layer

This project extends [nanobot](https://github.com/HKUDS/nanobot) with multi-agent management capabilities.

## Project Structure

```
manobot/
├── nanobot/                  # Original nanobot core (inherited from upstream)
│   ├── agent/                # Agent loop and tools
│   ├── channels/             # Message platform integrations
│   ├── config/               # Configuration schema (extended)
│   └── ...
│
├── manobot/                  # Multi-agent management layer
│   ├── agents/               # Agent management
│   │   ├── scope.py          # Agent scope resolution
│   │   ├── registry.py       # Agent registry
│   │   └── pool.py           # Agent pool manager
│   ├── bindings/             # Message routing
│   │   └── router.py         # Channel-to-agent routing
│   └── cli/                  # Extended CLI commands
│       ├── agents.py         # Agent management commands
│       └── main.py           # Main CLI entry point
│
└── bridge/                   # WhatsApp bridge (Node.js)
```

---

## Git Upstream Sync Guide

Manobot is designed to stay in sync with the original nanobot repository while maintaining your custom multi-agent extensions.

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
# Should show:
#   manobot   git@github.com:YOUR_USERNAME/manobot.git (fetch)
#   manobot   git@github.com:YOUR_USERNAME/manobot.git (push)
#   upstream  https://github.com/HKUDS/nanobot.git (fetch)
#   upstream  https://github.com/HKUDS/nanobot.git (push)
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

# 4. Resolve conflicts if any (usually in nanobot/ directory)
# Your manobot/ directory should have no conflicts

# 5. Push to your manobot remote
git push manobot main
```

### Handling Merge Conflicts

Most conflicts will be in files you've modified in `nanobot/`:

| File | Strategy |
|------|----------|
| `nanobot/config/schema.py` | Keep your multi-agent extensions, merge upstream changes carefully |
| `nanobot/**/*.py` (other) | Usually accept upstream changes |
| `manobot/**/*.py` | No conflicts (your code only) |
| `pyproject.toml` | Merge both entry points |

**Example conflict resolution:**

```bash
# After git merge upstream/main shows conflicts

# 1. Check conflicted files
git status

# 2. Edit conflicted files, keep both upstream changes and your additions
# Look for <<<<<<< HEAD and >>>>>>> upstream/main markers

# 3. Mark as resolved
git add <resolved-files>

# 4. Complete merge
git commit
```

### Branch Strategy (Recommended)

```
main (your development)
│
├── upstream-sync     # Track upstream/main exactly
│
└── feature/*         # Your feature branches
```

**Workflow:**

```bash
# Create upstream tracking branch
git checkout -b upstream-sync upstream/main

# When syncing:
git checkout upstream-sync
git pull upstream main

# Merge into main
git checkout main
git merge upstream-sync
```

### Automated Sync Script

Create `scripts/sync-upstream.sh`:

```bash
#!/bin/bash
set -e

echo "Fetching upstream nanobot..."
git fetch upstream

echo "Checking for new commits..."
NEW_COMMITS=$(git rev-list HEAD..upstream/main --count)

if [ "$NEW_COMMITS" -eq 0 ]; then
    echo "Already up to date!"
    exit 0
fi

echo "Found $NEW_COMMITS new commit(s)"
echo ""
echo "New changes:"
git log HEAD..upstream/main --oneline
echo ""

read -p "Merge these changes? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git merge upstream/main
    echo "Merged successfully!"
else
    echo "Merge cancelled."
fi
```

---

## Multi-Agent Configuration

### Config Schema

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.manobot/workspace",
      "model": "anthropic/claude-sonnet-4-20250514",
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
  }
}
```

### Agent Isolation

Each agent has isolated:
- **Memory**: `~/.manobot/agents/{agent_id}/memory/`
- **Sessions**: `~/.manobot/agents/{agent_id}/sessions/`
- **Workspace**: Configurable per-agent

---

## Deployment

### Auto-Initialization

When manobot starts, it automatically ensures a default agent exists:

```bash
# First run - auto-creates default agent from nanobot config
manobot gateway

# The default agent inherits nanobot's original configuration:
# - workspace: from agents.defaults.workspace
# - model: from agents.defaults.model
# - All existing nanobot settings preserved
```

### Docker Deployment

```bash
# Build image
docker build -t manobot .

# Run with config volume
docker run -d \
  --name manobot-gateway \
  -p 18790:18790 \
  -v ~/.manobot:/root/.manobot \
  manobot gateway

# Or use docker-compose
docker-compose up -d
```

### Migration from Nanobot

If you have an existing nanobot installation:

```bash
# 1. Backup existing config
cp ~/.nanobot/config.json ~/.nanobot/config.json.backup

# 2. Initialize manobot (auto-migrates config)
manobot init

# 3. Your existing nanobot becomes the default agent
manobot agents list
# Shows: assistant (default) - migrated from nanobot
```

---

## CLI Commands

```bash
# Initialize manobot (auto-creates default agent)
manobot init

# List agents
manobot agents list

# Show agent details
manobot agents show <agent_id>

# Add new agent
manobot agents add <agent_id> --name "Display Name" --workspace ~/path

# Delete agent
manobot agents delete <agent_id>

# Set default agent
manobot agents set-default <agent_id>

# List bindings
manobot agents bindings

# Add binding
manobot agents bind <agent_id> --channel telegram --peer-id -100123456789

# Start gateway
manobot gateway --port 18790
```

---

## Development Guidelines

- **Do not modify** files in `nanobot/` directly unless necessary
- All multi-agent extensions go in `manobot/`
- Maintain backwards compatibility with nanobot config format
- Use `nanobot` CLI for single-agent mode, `manobot` CLI for multi-agent
- Run `scripts/sync-upstream.sh` regularly to stay updated
