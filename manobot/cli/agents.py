"""CLI commands for multi-agent management.

Provides commands to list, add, delete, and manage agents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from manobot.agents.scope import (
    list_agent_entries,
    list_agent_ids,
    normalize_agent_id,
    resolve_agent_config,
    resolve_agent_memory_dir,
    resolve_agent_sessions_dir,
    resolve_agent_workspace,
    resolve_default_agent_id,
)

console = Console()
agents_app = typer.Typer(
    name="agents",
    help="Manage multiple agents",
    no_args_is_help=True,
)


def _load_config():
    """Load configuration from nanobot."""
    from nanobot.config.loader import load_config
    return load_config()


@agents_app.command("list")
def list_agents(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List all configured agents."""
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
    agent_id: str = typer.Argument(..., help="Agent ID to show"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show detailed information about an agent."""
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
    console.print(f"\n[bold]Paths:[/bold]")
    console.print(f"  Workspace:  {agent_config['workspace_path']}")
    console.print(f"  Memory:     {agent_config['memory_path']}")
    console.print(f"  Sessions:   {agent_config['sessions_path']}")
    
    if agent_config.get("skills"):
        console.print(f"\n[bold]Skills:[/bold] {', '.join(agent_config['skills'])}")
    
    if agent_config.get("identity"):
        console.print(f"\n[bold]Identity:[/bold]")
        identity = agent_config["identity"]
        if identity.get("name"):
            console.print(f"  Display Name: {identity['name']}")
        if identity.get("description"):
            console.print(f"  Description:  {identity['description']}")


@agents_app.command("add")
def add_agent(
    agent_id: str = typer.Argument(..., help="Agent ID (alphanumeric with hyphens)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Display name"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model to use"),
    default: bool = typer.Option(False, "--default", "-d", help="Set as default agent"),
):
    """Add a new agent to the configuration.
    
    Note: This command modifies the config file. You may need to restart
    the gateway for changes to take effect.
    """
    from nanobot.config.loader import get_config_path
    
    config = _load_config()
    normalized_id = normalize_agent_id(agent_id)
    
    # Check if agent already exists
    existing_ids = list_agent_ids(config)
    if normalized_id in existing_ids and normalized_id != "default":
        console.print(f"[red]Agent '{normalized_id}' already exists[/red]")
        raise typer.Exit(1)
    
    # Build new agent entry
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
    
    # If setting as default, unset other defaults
    if default:
        for agent in config_data["agents"]["list"]:
            agent["default"] = False
    
    config_data["agents"]["list"].append(new_agent)
    
    # Write back
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)
    
    console.print(f"[green]✓[/green] Added agent: {normalized_id}")
    if name:
        console.print(f"  Name: {name}")
    if workspace:
        console.print(f"  Workspace: {workspace}")
    if model:
        console.print(f"  Model: {model}")
    if default:
        console.print(f"  Set as default")
    
    console.print("\n[yellow]Note: Restart the gateway for changes to take effect[/yellow]")


@agents_app.command("delete")
def delete_agent(
    agent_id: str = typer.Argument(..., help="Agent ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete an agent from the configuration.
    
    Note: This does not delete the agent's workspace, memory, or sessions.
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
    """Set an agent as the default."""
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
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List all channel-to-agent bindings."""
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
    agent_id: str = typer.Argument(..., help="Target agent ID"),
    channel: str = typer.Option(..., "--channel", "-c", help="Channel name (telegram, discord, etc.)"),
    peer_type: Optional[str] = typer.Option(None, "--peer-type", "-t", help="Peer type (direct, group, channel)"),
    peer_id: Optional[str] = typer.Option(None, "--peer-id", "-p", help="Peer/chat ID"),
    comment: Optional[str] = typer.Option(None, "--comment", help="Optional description"),
):
    """Add a new channel-to-agent binding."""
    from nanobot.config.loader import get_config_path
    
    config = _load_config()
    normalized_id = normalize_agent_id(agent_id)
    
    # Check if agent exists
    if normalized_id not in list_agent_ids(config) and normalized_id != "default":
        console.print(f"[yellow]Warning: Agent '{normalized_id}' not found in config[/yellow]")
    
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
