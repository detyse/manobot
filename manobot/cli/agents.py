"""CLI commands for multi-agent management.

Provides commands to list, add, delete, and manage agents.
"""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from manobot.agents.scope import (
    list_agent_ids,
    normalize_agent_id,
    resolve_agent_config,
    resolve_agent_memory_dir,
    resolve_agent_sessions_dir,
    resolve_agent_workspace,
    resolve_default_agent_id,
)

# Valid peer_type values matching the schema
VALID_PEER_TYPES = {"direct", "group", "channel"}

console = Console()
agents_app = typer.Typer(
    name="agents",
    help="""Manage multiple AI agents

Commands to create, configure, and manage multiple agents with isolated
workspaces, memories, and session histories.

Common workflows:
  • manobot agents list              # View all agents
  • manobot agents add coder --name "Code Assistant"   # Add new agent
  • manobot agents show coder        # View agent details
  • manobot agents bind coder --channel telegram --peer-id -100123   # Bind channel
  • manobot agents set-default coder # Set default agent
""",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _load_config():
    """Load configuration from nanobot."""
    from nanobot.config.loader import load_config
    return load_config()


@agents_app.command("list")
def list_agents(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON instead of table"),
):
    """List all configured agents.

    Displays a table of all agents with their IDs, names, models,
    workspaces, and default status. Use --json for programmatic access.

    Examples:
        manobot agents list         # Display as formatted table
        manobot agents list --json  # Output as JSON
    """
    config = _load_config()

    agent_ids = list_agent_ids(config)
    default_id = resolve_default_agent_id(config)

    if json_output:
        agents_data = []
        for agent_id in agent_ids:
            agent_config = resolve_agent_config(config, agent_id)
            if agent_config:
                agent_config["is_default"] = agent_id == default_id
                agents_data.append(agent_config)
        console.print(json.dumps(agents_data, indent=2, default=str))
        return

    # Rich table output
    table = Table(title="Configured Agents")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Model", style="yellow")
    table.add_column("Workspace", style="blue")
    table.add_column("Default", style="magenta")

    for agent_id in agent_ids:
        agent_config = resolve_agent_config(config, agent_id)
        if agent_config:
            is_default = "✓" if agent_id == default_id else ""
            table.add_row(
                agent_config.get("id", agent_id),
                agent_config.get("name") or "-",
                agent_config.get("model") or "-",
                str(agent_config.get("workspace") or "-")[:40],
                is_default,
            )

    console.print(table)
    console.print(f"\nTotal: {len(agent_ids)} agent(s)")


@agents_app.command("show")
def show_agent(
    agent_id: str = typer.Argument(..., help="Agent ID to display (e.g., 'assistant', 'coder')"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON instead of formatted text"),
):
    """Show detailed information about a specific agent.

    Displays comprehensive details including configuration, paths
    (workspace, memory, sessions), and identity settings.

    Examples:
        manobot agents show assistant       # Show details for 'assistant'
        manobot agents show coder --json    # Output as JSON
    """
    config = _load_config()

    normalized_id = normalize_agent_id(agent_id)
    agent_config = resolve_agent_config(config, normalized_id)

    if not agent_config:
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    # Add path information
    agent_config["workspace_path"] = str(resolve_agent_workspace(config, normalized_id))
    agent_config["memory_path"] = str(resolve_agent_memory_dir(config, normalized_id))
    agent_config["sessions_path"] = str(resolve_agent_sessions_dir(config, normalized_id))
    agent_config["is_default"] = normalized_id == resolve_default_agent_id(config)

    if json_output:
        console.print(json.dumps(agent_config, indent=2, default=str))
        return

    console.print(f"\n[bold cyan]Agent: {normalized_id}[/bold cyan]")
    console.print(f"  Name:       {agent_config.get('name') or '-'}")
    console.print(f"  Model:      {agent_config.get('model') or '-'}")
    console.print(f"  Provider:   {agent_config.get('provider') or 'auto'}")
    console.print(f"  Max Tokens: {agent_config.get('max_tokens') or '-'}")
    console.print(f"  Temperature:{agent_config.get('temperature') or '-'}")
    console.print(f"  Default:    {'Yes' if agent_config['is_default'] else 'No'}")
    console.print("\n[bold]Paths:[/bold]")
    console.print(f"  Workspace:  {agent_config['workspace_path']}")
    console.print(f"  Memory:     {agent_config['memory_path']}")
    console.print(f"  Sessions:   {agent_config['sessions_path']}")

    if agent_config.get("skills"):
        console.print(f"\n[bold]Skills:[/bold] {', '.join(agent_config['skills'])}")

    if agent_config.get("identity"):
        console.print("\n[bold]Identity:[/bold]")
        identity = agent_config["identity"]
        if identity.get("name"):
            console.print(f"  Display Name: {identity['name']}")
        if identity.get("description"):
            console.print(f"  Description:  {identity['description']}")


@agents_app.command("add")
def add_agent(
    agent_id: str = typer.Argument(..., help="Unique agent ID (alphanumeric with hyphens, e.g., 'coder', 'writer-v2')"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Display name for the agent"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Custom workspace directory path"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model to use (e.g., 'anthropic/claude-sonnet-4-20250514')"),
    default: bool = typer.Option(False, "--default", "-d", help="Set as the default agent"),
):
    """Add a new agent to the configuration.

    Creates a new agent with its own isolated workspace, memory, and sessions.
    The agent ID must be unique and can only contain alphanumeric characters
    and hyphens.

    Note: This command modifies the config file. You need to restart
    the gateway for changes to take effect.

    Examples:
        manobot agents add coder --name "Code Assistant"
        manobot agents add writer --model "openai/gpt-4o" --workspace ~/writing
        manobot agents add assistant-v2 --default
    """
    from nanobot.config.loader import get_config_path

    config = _load_config()
    normalized_id = normalize_agent_id(agent_id)

    # Check if agent already exists
    existing_ids = list_agent_ids(config)
    existing_agent = None
    existing_idx = None

    if normalized_id in existing_ids and normalized_id != "default":
        # Agent exists - show interactive prompt
        console.print(f"Agent '{normalized_id}' already exists")
        existing_config = resolve_agent_config(config, normalized_id)
        if existing_config:
            console.print(f"  Current name: {existing_config.get('name') or '-'}")
            console.print(f"  Current model: {existing_config.get('model') or '-'}")
            console.print(f"  Current workspace: {existing_config.get('workspace') or '-'}")
        console.print("")
        console.print("  [bold]y[/bold] = overwrite with new values (existing config will be replaced)")
        console.print("  [bold]N[/bold] = update config, keeping existing values and merging new fields")
        console.print("")

        choice = typer.prompt("Overwrite?", default="N", show_default=False)

        if choice.lower() == "y":
            # Overwrite mode - will replace the existing agent
            existing_agent = "overwrite"
        elif choice.lower() == "n":
            # Update mode - merge new values with existing
            existing_agent = "update"
        else:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    # Load and modify config file
    config_path = get_config_path()
    if not config_path.exists():
        console.print("[red]Config file not found[/red]")
        raise typer.Exit(1)

    with open(config_path, "r") as f:
        config_data = json.load(f)

    # Ensure agents.list exists
    if "agents" not in config_data:
        config_data["agents"] = {}
    if "list" not in config_data["agents"]:
        config_data["agents"]["list"] = []

    # Find existing agent index if updating
    for idx, agent in enumerate(config_data["agents"]["list"]):
        if normalize_agent_id(agent.get("id", "")) == normalized_id:
            existing_idx = idx
            break

    # Build new agent entry
    if existing_agent == "update" and existing_idx is not None:
        # Update mode: merge with existing config
        new_agent = config_data["agents"]["list"][existing_idx].copy()
        if name:
            new_agent["name"] = name
        if workspace:
            new_agent["workspace"] = workspace
        if model:
            new_agent["model"] = model
        if default:
            new_agent["default"] = True
    else:
        # New or overwrite mode: start fresh
        new_agent = {
            "id": normalized_id,
        }
        if name:
            new_agent["name"] = name
        if workspace:
            new_agent["workspace"] = workspace
        if model:
            new_agent["model"] = model
        if default:
            new_agent["default"] = True

    # If setting as default, unset other defaults
    if default:
        for agent in config_data["agents"]["list"]:
            agent["default"] = False

    # Update or append agent
    if existing_idx is not None:
        config_data["agents"]["list"][existing_idx] = new_agent
    else:
        config_data["agents"]["list"].append(new_agent)

    # Write back
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    if existing_agent:
        # Update/overwrite mode - brief output
        action = "Updated" if existing_agent == "update" else "Replaced"
        console.print(f"[green]✓[/green] {action} agent: {normalized_id}")
        if name:
            console.print(f"  Name: {name}")
        if workspace:
            console.print(f"  Workspace: {workspace}")
        if model:
            console.print(f"  Model: {model}")
        if default:
            console.print("  Set as default")
        console.print("\n[yellow]Note: Restart the gateway for changes to take effect[/yellow]")
    else:
        # New agent - show welcome message like nanobot onboard
        console.print(f"[green]✓[/green] Agent '{normalized_id}' added to config")
        console.print("")
        console.print(f"[bold]🤖 Agent '{normalized_id}' is ready![/bold]")
        console.print("")
        console.print("[bold]Configuration:[/bold]")
        console.print(f"  ID:        {normalized_id}")
        console.print(f"  Name:      {name or '(not set)'}")
        console.print(f"  Model:     {model or '(uses default)'}")
        console.print(f"  Workspace: {workspace or '(uses default)'}")
        console.print(f"  Default:   {'Yes' if default else 'No'}")
        console.print("")
        console.print("[bold]Next steps:[/bold]")
        console.print(f"  1. View agent details: manobot agents show {normalized_id}")
        console.print(f"  2. Bind to a channel:  manobot agents bind {normalized_id} --channel telegram --peer-id <chat_id>")
        console.print("  3. Start gateway:      manobot gateway")
        console.print("")
        console.print("[dim]Docs: https://github.com/HKUDS/nanobot[/dim]")


@agents_app.command("delete")
def delete_agent(
    agent_id: str = typer.Argument(..., help="Agent ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Delete an agent from the configuration.

    Removes the agent from the configuration file. This action cannot be undone.
    The agent's workspace, memory, and session files are NOT deleted - you must
    remove them manually if needed.

    Note: You need to restart the gateway for changes to take effect.

    Examples:
        manobot agents delete old-agent          # Delete with confirmation
        manobot agents delete old-agent --force  # Delete without confirmation
    """
    from nanobot.config.loader import get_config_path

    config = _load_config()
    normalized_id = normalize_agent_id(agent_id)

    # Check if agent exists
    agent_config = resolve_agent_config(config, normalized_id)
    if not agent_config:
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    # Confirm deletion
    if not force:
        confirm = typer.confirm(f"Delete agent '{normalized_id}'?")
        if not confirm:
            console.print("Cancelled")
            raise typer.Exit(0)

    # Load and modify config file
    config_path = get_config_path()
    with open(config_path, "r") as f:
        config_data = json.load(f)

    # Remove agent from list
    if "agents" in config_data and "list" in config_data["agents"]:
        config_data["agents"]["list"] = [
            a for a in config_data["agents"]["list"]
            if normalize_agent_id(a.get("id", "")) != normalized_id
        ]

    # Write back
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    console.print(f"[green]✓[/green] Deleted agent: {normalized_id}")
    console.print("\n[yellow]Note: Restart the gateway for changes to take effect[/yellow]")


@agents_app.command("set-default")
def set_default(
    agent_id: str = typer.Argument(..., help="Agent ID to set as default"),
):
    """Set an agent as the default.

    The default agent receives all messages that don't match any
    specific binding rules. There can only be one default agent.

    Examples:
        manobot agents set-default assistant
        manobot agents set-default coder
    """
    from nanobot.config.loader import get_config_path

    config = _load_config()
    normalized_id = normalize_agent_id(agent_id)

    # Check if agent exists
    if normalized_id not in list_agent_ids(config):
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    # Load and modify config file
    config_path = get_config_path()
    with open(config_path, "r") as f:
        config_data = json.load(f)

    # Update default flags
    if "agents" in config_data and "list" in config_data["agents"]:
        for agent in config_data["agents"]["list"]:
            agent_id_norm = normalize_agent_id(agent.get("id", ""))
            agent["default"] = agent_id_norm == normalized_id

    # Write back
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    console.print(f"[green]✓[/green] Set default agent: {normalized_id}")


@agents_app.command("bindings")
def list_bindings(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON instead of table"),
):
    """List all channel-to-agent bindings.

    Bindings route messages from specific channels/chats to designated agents.
    For example, you can route all messages from a Telegram group to a
    specialized 'support' agent.

    Examples:
        manobot agents bindings         # Display as formatted table
        manobot agents bindings --json  # Output as JSON
    """
    config = _load_config()
    bindings = config.agents.bindings

    if json_output:
        bindings_data = [
            {
                "agent_id": b.agent_id,
                "channel": b.match.channel,
                "peer_type": b.match.peer_type,
                "peer_id": b.match.peer_id,
                "comment": b.comment,
            }
            for b in bindings
        ]
        console.print(json.dumps(bindings_data, indent=2))
        return

    if not bindings:
        console.print("[yellow]No bindings configured[/yellow]")
        console.print("\nAll messages will be routed to the default agent.")
        return

    table = Table(title="Agent Bindings")
    table.add_column("#", style="dim")
    table.add_column("Agent", style="cyan")
    table.add_column("Channel", style="green")
    table.add_column("Peer Type", style="yellow")
    table.add_column("Peer ID", style="blue")
    table.add_column("Comment", style="dim")

    for idx, binding in enumerate(bindings):
        table.add_row(
            str(idx),
            binding.agent_id,
            binding.match.channel,
            binding.match.peer_type or "-",
            binding.match.peer_id or "-",
            binding.comment or "-",
        )

    console.print(table)
    console.print(f"\nTotal: {len(bindings)} binding(s)")


@agents_app.command("bind")
def add_binding(
    agent_id: str = typer.Argument(..., help="Target agent ID to route messages to"),
    channel: str = typer.Option(..., "--channel", "-c", help="Channel name (telegram, discord, slack, etc.)"),
    peer_type: Optional[str] = typer.Option(None, "--peer-type", "-t", help="Peer type: direct, group, or channel"),
    peer_id: Optional[str] = typer.Option(None, "--peer-id", "-p", help="Peer/chat ID (e.g., Telegram chat ID)"),
    comment: Optional[str] = typer.Option(None, "--comment", help="Optional description for this binding"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip validation checks"),
):
    """Add a new channel-to-agent binding.

    Creates a routing rule that directs messages from a specific channel
    or chat to a designated agent. This enables multi-agent setups where
    different agents handle different contexts.

    Note: You need to restart the gateway for changes to take effect.

    Examples:
        # Route all Telegram messages to 'assistant' agent
        manobot agents bind assistant --channel telegram

        # Route specific Telegram group to 'coder' agent
        manobot agents bind coder --channel telegram --peer-type group --peer-id -100123456789

        # Route Discord DMs to 'support' agent
        manobot agents bind support --channel discord --peer-type direct --comment "Support requests"
    """
    from nanobot.config.loader import get_config_path

    config = _load_config()
    normalized_id = normalize_agent_id(agent_id)

    # Validate agent exists
    agent_ids = list_agent_ids(config)
    if normalized_id not in agent_ids and normalized_id != "default":
        if not force:
            console.print(f"[red]Error: Agent '{normalized_id}' not found[/red]")
            console.print(f"Available agents: {', '.join(agent_ids)}")
            console.print("\nUse --force to add binding anyway")
            raise typer.Exit(1)
        console.print(f"[yellow]Warning: Agent '{normalized_id}' not found in config[/yellow]")

    # Validate peer_type
    if peer_type and peer_type not in VALID_PEER_TYPES:
        console.print(f"[red]Error: Invalid peer_type '{peer_type}'[/red]")
        console.print(f"Valid values: {', '.join(sorted(VALID_PEER_TYPES))}")
        raise typer.Exit(1)

    # Build binding
    new_binding = {
        "agentId": normalized_id,
        "match": {
            "channel": channel,
        }
    }
    if peer_type:
        new_binding["match"]["peerType"] = peer_type
    if peer_id:
        new_binding["match"]["peerId"] = peer_id
    if comment:
        new_binding["comment"] = comment

    # Load and modify config file
    config_path = get_config_path()
    with open(config_path, "r") as f:
        config_data = json.load(f)

    # Ensure agents.bindings exists
    if "agents" not in config_data:
        config_data["agents"] = {}
    if "bindings" not in config_data["agents"]:
        config_data["agents"]["bindings"] = []

    config_data["agents"]["bindings"].append(new_binding)

    # Write back
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    console.print(f"[green]✓[/green] Added binding: {channel} -> {normalized_id}")
    console.print("\n[yellow]Note: Restart the gateway for changes to take effect[/yellow]")
