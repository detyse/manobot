"""Main CLI entry point for manobot.

Uses subprocess-based architecture: each agent runs as an independent process.
"""

import asyncio
import os
import select
import signal
import sys
from pathlib import Path

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from mano import __version__
from mano.cli.agents import agents_app

console = Console()

# Create main app
app = typer.Typer(
    name="manobot",
    help="""manobot - Multi-Agent Management

Manobot provides multi-agent capabilities, allowing you to:
  - Run multiple AI agents as isolated subprocesses
  - Route messages from different channels to specific agents
  - Manage agents through a simple CLI interface

Quick Start:
  1. manobot init              Initialize manobot environment
  2. manobot agents list       View configured agents
  3. manobot agents add <id>   Add a new agent
  4. manobot gateway           Start the gateway (supervisor)
""",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Add agents subcommand
app.add_typer(agents_app, name="agents")

# Register channels and provider subcommands
from mano.cli.channels import channels_app
from mano.cli.providers import provider_app

app.add_typer(channels_app, name="channels")
app.add_typer(provider_app, name="provider")

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios
        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    history_file = Path.home() / ".manobot" / "history" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,   # Enter submits (single line mode)
    )


def _print_agent_response(response: str, render_markdown: bool, agent_id: str = "manobot") -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{agent_id}[/cyan]")
    console.print(body)
    console.print()


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display)."""
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


@app.command()
def version():
    """Show manobot version information."""
    from agent import __logo__ as agent_logo
    from agent import __version__ as agent_version

    console.print(f"[bold cyan]manobot[/bold cyan] version: [green]{__version__}[/green]")
    console.print(f"{agent_logo} [bold cyan]agent[/bold cyan] version: [green]{agent_version}[/green]")


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Force re-initialization, overwriting existing config"),
):
    """Initialize manobot environment and create default agent.

    This command sets up the manobot state directory and creates a default
    agent based on your existing configuration. It is automatically
    run on first 'manobot gateway' start.

    Examples:
        manobot init              # First-time setup
        manobot init --force      # Re-initialize (resets to defaults)
    """
    from mano.agents.init import get_manobot_state_dir, initialize_manobot

    state_dir = get_manobot_state_dir()

    if state_dir.exists() and not force:
        console.print(f"[yellow]Manobot already initialized at {state_dir}[/yellow]")
        console.print("Use --force to re-initialize")
        return

    console.print("[bold]Initializing Manobot...[/bold]\n")

    result = initialize_manobot()

    if result["success"]:
        console.print(f"[green]OK[/green] State directory: {result['state_dir']}")
        console.print(f"[green]OK[/green] Config path: {result['config_path']}")

        if result["migrated"]:
            console.print("[green]OK[/green] Migrated existing config")

        if result["default_agent"]:
            console.print(f"[green]OK[/green] Default agent: {result['default_agent']}")

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
    """Show status of manobot agents (configured + running).

    Reads the process state file to show which agents are running,
    their ports, PIDs, and uptime.

    Example:
        manobot status
    """
    from agent.config.loader import load_config
    from mano.agents.init import initialize_manobot
    from mano.core import list_agent_ids, resolve_default_agent_id
    from mano.core.state import cleanup_stale, is_supervisor_alive, load_state, save_state

    initialize_manobot()
    config = load_config()
    agent_ids = list_agent_ids(config)
    default_id = resolve_default_agent_id(config)

    state = load_state()
    cleanup_stale(state)
    save_state(state)

    supervisor_running = is_supervisor_alive()

    console.print("\n[bold]Manobot Status[/bold]\n")
    console.print(f"[cyan]Supervisor:[/cyan] {'[green]running[/green]' if supervisor_running else '[dim]not running[/dim]'}")
    if state.supervisor_pid and supervisor_running:
        console.print(f"[cyan]Supervisor PID:[/cyan] {state.supervisor_pid}")
    console.print(f"[cyan]Configured agents:[/cyan] {len(agent_ids)}")
    console.print(f"[cyan]Default agent:[/cyan] [green]{default_id}[/green]")

    # Process table
    if state.agents:
        console.print()
        table = Table(title="Agent Processes")
        table.add_column("Agent", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("PID", style="dim")
        table.add_column("Port", style="blue")
        table.add_column("Restarts", style="yellow")
        table.add_column("Error", style="red")

        for aid, agent_state in state.agents.items():
            status_style = {
                "running": "[green]running[/green]",
                "starting": "[yellow]starting[/yellow]",
                "stopping": "[yellow]stopping[/yellow]",
                "stopped": "[dim]stopped[/dim]",
                "crashed": "[red]crashed[/red]",
            }.get(agent_state.status, agent_state.status)

            table.add_row(
                aid,
                status_style,
                str(agent_state.pid),
                str(agent_state.port),
                str(agent_state.restart_count),
                agent_state.error_message or "-",
            )

        console.print(table)
    else:
        console.print("\n[dim]No agent processes recorded. Run 'manobot gateway' to start agents.[/dim]")


@app.command()
def gateway(
    base_port: int = typer.Option(18791, "--base-port", "-p", help="Base port for agent subprocesses"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose debug output"),
    agent: str = typer.Option(None, "--agent", "-a", help="Run only a specific agent by ID"),
    check_interval: float = typer.Option(10.0, "--check-interval", help="Health check interval in seconds"),
):
    """Start the manobot supervisor (gateway).

    Launches all configured agents as isolated subprocesses, each with
    its own HTTP API, channels, and memory. The supervisor monitors
    agent health and auto-restarts failed agents.

    Examples:
        manobot gateway                          # Start all agents
        manobot gateway --agent coder            # Start only 'coder'
        manobot gateway --base-port 19000        # Custom port range
        manobot gateway --verbose                # Debug logging
    """
    from loguru import logger

    from agent.config.loader import load_config
    from mano.agents.init import ensure_default_agent, initialize_manobot
    from mano.core.health import HealthMonitor
    from mano.core.process_manager import ProcessManager
    from mano.core.state import is_supervisor_alive

    if verbose:
        logger.enable("agent")
        logger.enable("manobot")
    else:
        logger.disable("agent")

    # Check if supervisor is already running
    if is_supervisor_alive():
        console.print("[red]Error: A supervisor is already running.[/red]")
        console.print("Use 'manobot status' to check, or stop it first.")
        raise typer.Exit(1)

    # Auto-initialize
    initialize_manobot()
    config = load_config()
    ensure_default_agent(config)
    config = load_config()

    manager = ProcessManager(config, base_port=base_port)
    monitor = HealthMonitor(manager, check_interval=check_interval)

    async def _run_supervisor():
        shutdown_event = asyncio.Event()
        manager.set_supervisor_pid()

        # Signal handling
        loop = asyncio.get_running_loop()
        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, shutdown_event.set)

        try:
            # Start agents
            if agent:
                console.print(f"Starting agent '{agent}'...")
                result = await manager.start_agent(agent)
                if result.status == "running":
                    console.print(f"[green]OK[/green] Agent '{agent}' running on port {result.port} (pid={result.pid})")
                else:
                    console.print(f"[red]FAIL[/red] Agent '{agent}': {result.error_message}")
                    raise typer.Exit(1)
            else:
                console.print("Starting all agents...")
                results = await manager.start_all()
                for aid, result in results.items():
                    if result.status == "running":
                        console.print(f"  [green]OK[/green] {aid} -> port {result.port} (pid={result.pid})")
                    else:
                        console.print(f"  [red]FAIL[/red] {aid}: {result.error_message}")

            # Start health monitor
            await monitor.start()
            console.print("\n[bold]Supervisor running. Press Ctrl+C to stop.[/bold]\n")

            # Wait for shutdown
            if sys.platform == "win32":
                try:
                    while not shutdown_event.is_set():
                        await asyncio.sleep(1)
                except KeyboardInterrupt:
                    shutdown_event.set()
            else:
                await shutdown_event.wait()

        except KeyboardInterrupt:
            pass
        finally:
            console.print("\nShutting down...")
            monitor.stop()
            await manager.stop_all()
            console.print("[green]All agents stopped.[/green]")

    asyncio.run(_run_supervisor())


@app.command("agent")
def agent_chat(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    agent_id: str = typer.Option(None, "--agent", "-a", help="Agent ID to talk to (default: fallback agent)"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    direct: bool = typer.Option(False, "--direct", "-d", help="Run agent in-process (bypass subprocess)"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show runtime logs during chat"),
):
    """Interact with an agent.

    By default, sends messages to a running agent subprocess via HTTP.
    Use --direct to run the agent in-process (no gateway needed).

    In single-message mode (-m), sends one message and prints the response.
    Without -m, starts an interactive REPL session.

    Examples:
        manobot agent -m "What is 2+2?"
        manobot agent --agent coder -m "Write a hello world"
        manobot agent                          # interactive mode (HTTP)
        manobot agent --direct                 # interactive mode (in-process)
    """
    from loguru import logger

    from agent.config.loader import load_config
    from mano.agents.init import ensure_default_agent, initialize_manobot
    from mano.core import (
        build_agent_scope,
        list_agent_ids,
        resolve_default_agent_id,
    )

    if logs:
        logger.enable("agent")
        logger.enable("manobot")
    else:
        logger.disable("agent")

    # Auto-initialize
    initialize_manobot()
    config = load_config()
    ensure_default_agent(config)
    config = load_config()

    # Resolve target agent
    default_id = resolve_default_agent_id(config)
    target_id = agent_id or default_id

    configured = list_agent_ids(config)
    if target_id not in configured:
        console.print(f"[red]Agent '{target_id}' not found[/red]")
        console.print(f"Available agents: {', '.join(configured)}")
        raise typer.Exit(1)

    scope = build_agent_scope(config, target_id)
    if not scope:
        console.print(f"[red]Cannot resolve scope for agent '{target_id}'[/red]")
        raise typer.Exit(1)

    if direct:
        _agent_chat_direct(config, scope, target_id, message, session_id, markdown, logs)
    else:
        _agent_chat_http(config, scope, target_id, message, session_id, markdown)


def _agent_chat_http(config, scope, target_id, message, session_id, markdown):
    """Send messages to a running agent subprocess via HTTP."""
    import httpx

    from mano.core import build_session_key
    from mano.core.state import cleanup_stale, load_state, save_state

    state = load_state()
    cleanup_stale(state)
    save_state(state)

    agent_state = state.agents.get(target_id)
    if not agent_state or agent_state.status != "running":
        console.print(f"[red]Agent '{target_id}' is not running.[/red]")
        console.print("Start the gateway first: manobot gateway")
        console.print("Or use --direct flag to run in-process.")
        raise typer.Exit(1)

    base_url = f"http://127.0.0.1:{agent_state.port}"

    # Build session key
    session_key = build_session_key(target_id, "cli", "direct")
    if ":" in session_id:
        cli_channel, cli_chat_id = session_id.split(":", 1)
        session_key = build_session_key(target_id, cli_channel, cli_chat_id)

    display_name = scope.name or target_id

    if message:
        # Single-message mode via HTTP
        try:
            resp = httpx.post(
                f"{base_url}/api/chat",
                json={"message": message, "session_key": session_key},
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                _print_agent_response(data.get("response", ""), render_markdown=markdown, agent_id=display_name)
            else:
                console.print(f"[red]Error from agent: {resp.text}[/red]")
                raise typer.Exit(1)
        except httpx.ConnectError:
            console.print(f"[red]Cannot connect to agent '{target_id}' on port {agent_state.port}[/red]")
            console.print("The agent may have crashed. Check 'manobot status'.")
            raise typer.Exit(1)
    else:
        # Interactive REPL via HTTP
        _init_prompt_session()
        console.print(f"Interactive mode with [bold]{display_name}[/bold] "
                       f"(via HTTP, port {agent_state.port})")
        console.print("Type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n")

        while True:
            try:
                _flush_pending_tty_input()

                async def _read():
                    return await _read_interactive_input_async()
                user_input = asyncio.run(_read())
                command = user_input.strip()
                if not command:
                    continue
                if _is_exit_command(command):
                    _restore_terminal()
                    console.print("\nGoodbye!")
                    break

                with console.status(f"[dim]{display_name} is thinking...[/dim]", spinner="dots"):
                    resp = httpx.post(
                        f"{base_url}/api/chat",
                        json={"message": command, "session_key": session_key},
                        timeout=120,
                    )

                if resp.status_code == 200:
                    data = resp.json()
                    _print_agent_response(data.get("response", ""), render_markdown=markdown, agent_id=display_name)
                else:
                    console.print(f"[red]Error: {resp.text}[/red]")

            except KeyboardInterrupt:
                _restore_terminal()
                console.print("\nGoodbye!")
                break
            except httpx.ConnectError:
                console.print(f"\n[red]Lost connection to agent '{target_id}'.[/red]")
                break


def _agent_chat_direct(config, scope, target_id, message, session_id, markdown, logs):
    """Run agent in-process for direct interaction (no subprocess needed)."""
    from agent.agent.loop import AgentLoop
    from agent.bus.queue import MessageBus
    from agent.cron.service import CronService
    from agent.session.manager import SessionManager
    from agent.utils.helpers import sync_workspace_templates
    from mano.core import build_session_key
    from mano.core.runner import _make_provider
    from mano.core.scope import resolve_agent_channels, resolve_agent_providers

    sync_workspace_templates(scope.workspace)

    # Resolve per-agent channels and providers (mirrors subprocess config_gen logic)
    resolved_channels = resolve_agent_channels(config, target_id)
    resolved_providers = resolve_agent_providers(config, target_id)

    # Patch config so _make_provider reads per-agent provider credentials
    provider_config = config.model_copy(update={"providers": resolved_providers})

    bus = MessageBus()
    cron_store_path = scope.agent_dir / "cron" / "jobs.json"
    cron_store_path.parent.mkdir(parents=True, exist_ok=True)
    cron = CronService(cron_store_path)

    session_manager = SessionManager(scope.workspace, sessions_dir=scope.sessions_dir)

    # Use runner's provider factory with per-agent providers
    provider = _make_provider(
        provider_config,
        model_override=scope.model,
        provider_override=scope.provider,
        max_tokens_override=scope.max_tokens,
        temperature_override=scope.temperature,
        reasoning_effort_override=scope.reasoning_effort,
    )

    defaults = config.agents.defaults
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=scope.workspace,
        model=scope.model or defaults.model,
        max_iterations=scope.max_tool_iterations or defaults.max_tool_iterations,
        context_window_tokens=scope.context_window_tokens or defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=resolved_channels,
        memory_dir=scope.memory_dir,
    )

    # Build session key
    session_key = build_session_key(target_id, "cli", "direct")
    if ":" in session_id:
        cli_channel, cli_chat_id = session_id.split(":", 1)
        session_key = build_session_key(target_id, cli_channel, cli_chat_id)

    display_name = scope.name or target_id

    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext
            return nullcontext()
        return console.status(f"[dim]{display_name} is thinking...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = resolved_channels
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        console.print(f"  [dim]{content}[/dim]")

    if message:
        async def run_once():
            with _thinking_ctx():
                response = await agent_loop.process_direct(
                    message, session_key, on_progress=_cli_progress,
                )
            _print_agent_response(response, render_markdown=markdown, agent_id=display_name)
            agent_loop.stop()
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        _init_prompt_session()
        console.print(f"Interactive mode with [bold]{display_name}[/bold] (direct, in-process)")
        console.print("Type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n")

        def _exit_on_sigint(signum, frame):
            _restore_terminal()
            console.print("\nGoodbye!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)

        async def run_interactive():
            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue
                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        with _thinking_ctx():
                            response = await agent_loop.process_direct(
                                command, session_key, on_progress=_cli_progress,
                            )
                        _print_agent_response(response, render_markdown=markdown, agent_id=display_name)
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                agent_loop.stop()
                await agent_loop.close_mcp()

        asyncio.run(run_interactive())


@app.command()
def sync():
    """Sync with upstream repository.

    Fetches and shows changes from the upstream repository.
    This helps keep your manobot installation up-to-date with the
    latest features and bug fixes.

    The sync script (scripts/sync-upstream.sh) will:
      1. Fetch latest changes from upstream
      2. Show a summary of new commits
      3. Prompt for confirmation before merging

    Example:
        manobot sync

    Note: You may need to resolve merge conflicts if you've modified
    files in the agent/ directory.
    """
    import subprocess

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
    """Manobot - Multi-Agent Management Layer."""
    pass


if __name__ == "__main__":
    app()
