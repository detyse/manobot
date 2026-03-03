"""Main CLI entry point for manobot.

Extends nanobot CLI with multi-agent management capabilities.
"""

import typer
from rich.console import Console

from manobot import __version__
from manobot.cli.agents import agents_app

console = Console()

# Create main app
app = typer.Typer(
    name="manobot",
    help="🤖 manobot - Multi-Agent Management for Nanobot",
    no_args_is_help=True,
)

# Add agents subcommand
app.add_typer(agents_app, name="agents")


@app.command()
def version():
    """Show manobot version."""
    from nanobot import __version__ as nanobot_version
    
    console.print(f"manobot version: {__version__}")
    console.print(f"nanobot version: {nanobot_version}")


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Force re-initialization"),
):
    """Initialize manobot environment.
    
    Creates the manobot state directory and ensures a default agent
    exists based on your existing nanobot configuration.
    
    This command is automatically run on first 'manobot gateway' start.
    """
    from manobot.agents.init import initialize_manobot, get_manobot_state_dir
    
    state_dir = get_manobot_state_dir()
    
    if state_dir.exists() and not force:
        console.print(f"[yellow]Manobot already initialized at {state_dir}[/yellow]")
        console.print("Use --force to re-initialize")
        return
    
    console.print("[bold]🤖 Initializing Manobot...[/bold]\n")
    
    result = initialize_manobot()
    
    if result["success"]:
        console.print(f"[green]✓[/green] State directory: {result['state_dir']}")
        console.print(f"[green]✓[/green] Config path: {result['config_path']}")
        
        if result["migrated"]:
            console.print(f"[green]✓[/green] Migrated existing nanobot config")
        
        if result["default_agent"]:
            console.print(f"[green]✓[/green] Default agent: {result['default_agent']}")
        
        console.print("\n[bold green]Manobot initialized successfully![/bold green]")
        console.print("\nNext steps:")
        console.print("  1. Run 'manobot agents list' to see configured agents")
        console.print("  2. Run 'manobot agents add <id>' to add more agents")
        console.print("  3. Run 'manobot gateway' to start the gateway")
    else:
        console.print("[red]Initialization failed:[/red]")
        for error in result["errors"]:
            console.print(f"  - {error}")
        raise typer.Exit(1)


@app.command()
def status():
    """Show status of all configured agents."""
    from manobot.agents.init import initialize_manobot
    from manobot.agents.scope import (
        list_agent_ids,
        resolve_default_agent_id,
    )
    from nanobot.config.loader import load_config
    
    # Auto-initialize if needed
    initialize_manobot()
    
    config = load_config()
    agent_ids = list_agent_ids(config)
    default_id = resolve_default_agent_id(config)
    
    console.print("\n[bold]🤖 Manobot Status[/bold]\n")
    console.print(f"Configured agents: {len(agent_ids)}")
    console.print(f"Default agent: {default_id}")
    
    # Show bindings summary
    bindings = config.agents.bindings
    if bindings:
        console.print(f"Active bindings: {len(bindings)}")
    else:
        console.print("Active bindings: 0 (all traffic to default)")
    
    console.print("\n[dim]Run 'manobot agents list' for details[/dim]")


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    agent: str = typer.Option(None, "--agent", "-a", help="Run specific agent only"),
):
    """Start the manobot gateway with multi-agent support.
    
    On first run, automatically initializes manobot and creates a default
    agent from your existing nanobot configuration.
    
    This is an enhanced version of nanobot gateway that supports
    routing messages to multiple agents based on bindings.
    """
    from manobot.agents.init import initialize_manobot, ensure_default_agent
    from manobot.agents.scope import list_agent_ids, resolve_default_agent_id
    
    # Auto-initialize on first run
    console.print("[dim]Checking manobot initialization...[/dim]")
    result = initialize_manobot()
    
    if not result["success"]:
        console.print("[red]Initialization failed. Run 'manobot init' first.[/red]")
        raise typer.Exit(1)
    
    # Load config and show agent info
    from nanobot.config.loader import load_config
    config = load_config()
    
    # Ensure default agent exists
    ensure_default_agent(config)
    
    # Reload config after potential modifications
    config = load_config()
    
    agent_ids = list_agent_ids(config)
    default_id = resolve_default_agent_id(config)
    
    console.print(f"[green]✓[/green] Loaded {len(agent_ids)} agent(s), default: {default_id}")
    
    if agent:
        if agent not in agent_ids:
            console.print(f"[red]Agent '{agent}' not found[/red]")
            raise typer.Exit(1)
        console.print(f"[yellow]Running single agent: {agent}[/yellow]")
    
    # Show bindings
    bindings = config.agents.bindings
    if bindings:
        console.print(f"[green]✓[/green] {len(bindings)} binding(s) configured")
    
    console.print("")
    
    # Delegate to nanobot gateway
    # TODO: Implement full multi-agent gateway with AgentPool routing
    from nanobot.cli.commands import gateway as nanobot_gateway
    
    if len(agent_ids) > 1 or bindings:
        console.print("[yellow]Note: Multi-agent routing is under development.[/yellow]")
        console.print("[yellow]Currently running in single-agent mode with default agent.[/yellow]\n")
    
    nanobot_gateway(port=port, verbose=verbose)


@app.command()
def sync():
    """Sync with upstream nanobot repository.
    
    Fetches and shows changes from the upstream nanobot repository.
    Run scripts/sync-upstream.sh for interactive merge.
    """
    import subprocess
    import sys
    
    script_path = "scripts/sync-upstream.sh"
    
    try:
        # Check if script exists
        from pathlib import Path
        if not Path(script_path).exists():
            console.print(f"[red]Sync script not found: {script_path}[/red]")
            console.print("Run from the manobot repository root directory.")
            raise typer.Exit(1)
        
        # Run the sync script
        result = subprocess.run(
            ["bash", script_path],
            check=False,
        )
        raise typer.Exit(result.returncode)
        
    except FileNotFoundError:
        console.print("[red]bash not found. Run the sync script manually:[/red]")
        console.print(f"  bash {script_path}")
        raise typer.Exit(1)


@app.callback()
def main():
    """Manobot - Multi-Agent Management Layer for Nanobot."""
    pass


if __name__ == "__main__":
    app()
