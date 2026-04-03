"""CLI commands for multi-agent management."""

from __future__ import annotations

import asyncio
from collections import deque
import json
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from mano.agents.init import initialize_manobot
from mano.agents.onboard import onboard_agent
from mano.agents.registry import (
    get_agent_config_path,
    is_registered,
    list_registered_agent_ids,
    load_registered_agent_config,
    resolve_default_registered_agent_id,
    set_default_registered_agent,
    unregister_agent,
)
from mano.core.scope import build_agent_scope, normalize_agent_id

console = Console()
agents_app = typer.Typer(
    name="agents",
    help="""Manage multiple AI agents

Commands to create, configure, and manage multiple agents with isolated
workspaces, memories, session histories, and standalone configs.
""",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _load_scope(agent_id: str):
    """Load one registered agent's config and resolved scope."""
    config = load_registered_agent_config(agent_id)
    scope = build_agent_scope(config, agent_id)
    if scope is None:
        raise RuntimeError(f"Cannot resolve scope for agent '{agent_id}'")
    return config, scope


def _resolve_agent_log_path(agent_id: str) -> Path:
    """Resolve the runner log path for one registered agent."""
    from mano.core.state import load_state

    normalized_id = normalize_agent_id(agent_id)
    if not is_registered(normalized_id):
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    runtime_state = load_state().agents.get(normalized_id)
    if runtime_state and runtime_state.log_path:
        return Path(runtime_state.log_path).expanduser()

    return get_agent_config_path(normalized_id).parent / "logs" / "runner.log"


def _tail_log_lines(log_path: Path, line_count: int = 100) -> list[str]:
    """Read the last N lines from a log file."""
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, maxlen=line_count))


def _follow_log_file(log_path: Path) -> None:
    """Stream new log lines until interrupted."""
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, 2)
        try:
            while True:
                line = handle.readline()
                if line:
                    typer.echo(line, nl=False)
                    continue
                time.sleep(0.25)
        except KeyboardInterrupt:
            raise typer.Exit(0) from None


@agents_app.command("list")
def list_agents(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON instead of table"),
):
    """List all configured agents."""
    initialize_manobot()

    agent_ids = list_registered_agent_ids()
    default_id = resolve_default_registered_agent_id()

    if json_output:
        agents_data = []
        for agent_id in agent_ids:
            _, scope = _load_scope(agent_id)
            agents_data.append({
                "id": scope.agent_id,
                "name": scope.name,
                "model": scope.model,
                "workspace": str(scope.workspace),
                "config_path": str(get_agent_config_path(agent_id)),
                "is_default": agent_id == default_id,
            })
        typer.echo(json.dumps(agents_data, indent=2, default=str))
        return

    table = Table(title="Configured Agents")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Model", style="yellow")
    table.add_column("Config", style="blue", overflow="fold")
    table.add_column("Default", style="magenta")

    for agent_id in agent_ids:
        _, scope = _load_scope(agent_id)
        table.add_row(
            scope.agent_id,
            scope.name or "-",
            scope.model or "-",
            str(get_agent_config_path(agent_id)),
            "✓" if agent_id == default_id else "",
        )

    console.print(table)
    if agent_ids:
        console.print("\n[bold]Config Paths:[/bold]")
        for agent_id in agent_ids:
            _, scope = _load_scope(agent_id)
            console.print(f"  {scope.agent_id}: {get_agent_config_path(agent_id)}", soft_wrap=True)
    console.print(f"\nTotal: {len(agent_ids)} agent(s)")


@agents_app.command("logs")
def logs_agent_cmd(
    agent_id: str = typer.Argument(..., help="Agent ID whose log should be shown"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow the log output"),
):
    """Show an agent's runner log."""
    initialize_manobot()

    log_path = _resolve_agent_log_path(agent_id)
    if not log_path.exists():
        console.print(f"[red]Log file not found for agent '{agent_id}'[/red]")
        console.print(f"Expected: {log_path}", soft_wrap=True)
        console.print("Start the agent first to create the runner log.")
        raise typer.Exit(1)

    console.print(f"[bold]Log:[/bold] {log_path}", soft_wrap=True)

    tail_lines = _tail_log_lines(log_path)
    if tail_lines:
        typer.echo("".join(tail_lines), nl=not tail_lines[-1].endswith("\n"))
    else:
        console.print("[dim]Log file is empty.[/dim]")

    if follow:
        console.print("\n[dim]Following log output. Press Ctrl+C to stop.[/dim]")
        _follow_log_file(log_path)


@agents_app.command("show")
def show_agent(
    agent_id: str = typer.Argument(..., help="Agent ID to display"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON instead of formatted text"),
):
    """Show detailed information about a specific agent."""
    initialize_manobot()
    from mano.core.state import load_state

    normalized_id = normalize_agent_id(agent_id)
    if not is_registered(normalized_id):
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    config_path = get_agent_config_path(normalized_id)
    _, scope = _load_scope(normalized_id)
    runtime_state = load_state().agents.get(normalized_id)

    workspace_exists = scope.workspace.exists()
    memory_exists = scope.memory_dir.exists()
    sessions_exists = scope.sessions_dir.exists()
    if workspace_exists and memory_exists:
        status = "[green]ready[/green]"
    elif workspace_exists:
        status = "[yellow]partial[/yellow]"
    else:
        status = "[red]not initialized[/red]"

    agent_config = {
        "id": scope.agent_id,
        "name": scope.name,
        "status": "ready" if workspace_exists and memory_exists else ("partial" if workspace_exists else "not_initialized"),
        "config_path": str(config_path),
        "model": scope.model,
        "provider": scope.provider,
        "max_tokens": scope.max_tokens,
        "temperature": scope.temperature,
        "context_window_tokens": scope.context_window_tokens,
        "workspace_path": str(scope.workspace),
        "memory_path": str(scope.memory_dir),
        "sessions_path": str(scope.sessions_dir),
        "is_default": normalized_id == resolve_default_registered_agent_id(),
        "skills": scope.skills,
        "identity": scope.identity,
        "runtime_status": runtime_state.status if runtime_state else None,
        "pid": runtime_state.pid if runtime_state else None,
        "port": runtime_state.port if runtime_state else None,
        "error_message": runtime_state.error_message if runtime_state else None,
        "log_path": runtime_state.log_path if runtime_state else None,
    }

    if json_output:
        typer.echo(json.dumps(agent_config, indent=2, default=str))
        return

    console.print(f"\n[bold cyan]Agent: {normalized_id}[/bold cyan]")
    console.print(f"  Status:     {status}")
    console.print(f"  Name:       {agent_config.get('name') or '-'}")
    console.print(f"  Default:    {'Yes' if agent_config['is_default'] else 'No'}")
    console.print("\n[bold]Config:[/bold]")
    console.print(f"  Config:     {config_path}")
    console.print(f"  Model:      {agent_config.get('model') or '-'}")
    console.print(f"  Provider:   {agent_config.get('provider') or 'auto'}")
    console.print(f"  Max Tokens: {agent_config.get('max_tokens') or '-'}")
    console.print(f"  Context:    {agent_config.get('context_window_tokens') or '-'} tokens")
    console.print(f"  Temperature:{agent_config.get('temperature') or '-'}")
    console.print("\n[bold]Paths:[/bold]")
    console.print(f"  Workspace:  {agent_config['workspace_path']} {'[green]✓[/green]' if workspace_exists else '[red]✗[/red]'}")
    console.print(f"  Memory:     {agent_config['memory_path']} {'[green]✓[/green]' if memory_exists else '[red]✗[/red]'}")
    console.print(f"  Sessions:   {agent_config['sessions_path']} {'[green]✓[/green]' if sessions_exists else '[dim]✗[/dim]'}")
    if runtime_state:
        console.print("\n[bold]Runtime:[/bold]")
        console.print(f"  Status:     {agent_config['runtime_status']}")
        console.print(f"  PID:        {agent_config['pid']}")
        console.print(f"  Port:       {agent_config['port']}")
        if agent_config.get("error_message"):
            console.print(f"  Last Error: {agent_config['error_message']}")
        if agent_config.get("log_path"):
            console.print(f"  Log:        {agent_config['log_path']}")

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
    agent_id: str = typer.Argument(..., help="Unique agent ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Display name for the agent"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Custom workspace directory path"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM model to use"),
    default: bool = typer.Option(False, "--default", "-d", help="Set as the default agent"),
):
    """Add a new independent agent or update an existing one."""
    initialize_manobot()

    normalized_id = normalize_agent_id(agent_id)
    existing = is_registered(normalized_id)
    mode = "refresh"

    if existing:
        console.print(f"Agent '{normalized_id}' already exists")
        _, existing_scope = _load_scope(normalized_id)
        console.print(f"  Current name: {existing_scope.name or '-'}")
        console.print(f"  Current model: {existing_scope.model or '-'}")
        console.print(f"  Current workspace: {existing_scope.workspace}")
        console.print("")
        console.print("  [bold]y[/bold] = reset to defaults (existing values will be overwritten)")
        console.print("  [bold]N[/bold] = refresh config, keeping existing values and merging new fields")
        console.print("")

        choice = typer.prompt("Overwrite?", default="N", show_default=False)
        if choice.lower() == "y":
            mode = "reset"
        elif choice.lower() != "n":
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    result = onboard_agent(
        normalized_id,
        workspace=workspace,
        mode=mode,
        name=name,
        model=model,
        set_default=True if default else None,
    )

    if existing:
        action = "Reset" if mode == "reset" else "Updated"
        console.print(f"[green]✓[/green] {action} agent: {normalized_id}")
    else:
        console.print(f"[green]✓[/green] Added agent: {normalized_id}")

    console.print(f"  Config:    {result.agent_config_path}")
    console.print(f"  Workspace: {result.scope.workspace}")
    if default:
        console.print("  Default:   Yes")

    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. View agent details: manobot show {normalized_id}")
    console.print("  2. Start gateway:      manobot gateway")


@agents_app.command("delete")
def delete_agent(
    agent_id: str = typer.Argument(..., help="Agent ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Delete an agent from the registry."""
    initialize_manobot()

    normalized_id = normalize_agent_id(agent_id)
    if not is_registered(normalized_id):
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    if not force:
        confirm = typer.confirm(f"Delete agent '{normalized_id}'?")
        if not confirm:
            console.print("Cancelled")
            raise typer.Exit(0)

    unregister_agent(normalized_id)
    console.print(f"[green]✓[/green] Deleted agent: {normalized_id}")
    console.print("Standalone files were left on disk.")


@agents_app.command("set-default")
def set_default(
    agent_id: str = typer.Argument(..., help="Agent ID to set as default"),
):
    """Set an agent as the default."""
    initialize_manobot()

    normalized_id = normalize_agent_id(agent_id)
    if not is_registered(normalized_id):
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    set_default_registered_agent(normalized_id)
    console.print(f"[green]✓[/green] Set default agent: {normalized_id}")


@agents_app.command("start")
def start_agent_cmd(
    agent_id: str = typer.Argument(..., help="Agent ID to start"),
    base_port: int = typer.Option(18791, "--base-port", "-p", help="Base port for agent subprocess"),
):
    """Start a single agent subprocess."""
    from mano.core.process_manager import ProcessManager

    initialize_manobot()
    normalized_id = normalize_agent_id(agent_id)

    if not is_registered(normalized_id):
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    manager = ProcessManager(base_port=base_port)

    async def _start():
        result = await manager.start_agent(normalized_id)
        if result.status == "running":
            console.print(f"[green]OK[/green] Agent '{normalized_id}' running on port {result.port} (pid={result.pid})")
            if result.log_path:
                console.print(f"[dim]log: {result.log_path}[/dim]", soft_wrap=True)
        else:
            console.print(f"[red]FAIL[/red] Agent '{normalized_id}': {result.error_message}")
            if result.log_path:
                console.print(f"[dim]log: {result.log_path}[/dim]", soft_wrap=True)
            raise typer.Exit(1)

    asyncio.run(_start())


@agents_app.command("stop")
def stop_agent_cmd(
    agent_id: str = typer.Argument(..., help="Agent ID to stop"),
    timeout: float = typer.Option(10.0, "--timeout", "-t", help="Shutdown timeout in seconds"),
):
    """Stop a running agent subprocess."""
    from mano.core.process_manager import ProcessManager

    initialize_manobot()
    normalized_id = normalize_agent_id(agent_id)
    manager = ProcessManager()

    async def _stop():
        stopped = await manager.stop_agent(normalized_id, timeout=timeout)
        if stopped:
            console.print(f"[green]OK[/green] Agent '{normalized_id}' stopped")
        else:
            console.print(f"[yellow]Agent '{normalized_id}' was not running[/yellow]")

    asyncio.run(_stop())


@agents_app.command("restart")
def restart_agent_cmd(
    agent_id: str = typer.Argument(..., help="Agent ID to restart"),
    base_port: int = typer.Option(18791, "--base-port", "-p", help="Base port for agent subprocess"),
):
    """Restart a running agent subprocess."""
    from mano.core.process_manager import ProcessManager

    initialize_manobot()
    normalized_id = normalize_agent_id(agent_id)

    if not is_registered(normalized_id):
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        raise typer.Exit(1)

    manager = ProcessManager(base_port=base_port)

    async def _restart():
        console.print(f"Restarting agent '{normalized_id}'...")
        result = await manager.restart_agent(normalized_id)
        if result.status == "running":
            console.print(f"[green]OK[/green] Agent '{normalized_id}' running on port {result.port} (pid={result.pid})")
            if result.log_path:
                console.print(f"[dim]log: {result.log_path}[/dim]", soft_wrap=True)
        else:
            console.print(f"[red]FAIL[/red] Agent '{normalized_id}': {result.error_message}")
            if result.log_path:
                console.print(f"[dim]log: {result.log_path}[/dim]", soft_wrap=True)
            raise typer.Exit(1)

    asyncio.run(_restart())
