"""Main CLI entry point for manobot.

Uses subprocess-based architecture: each agent runs as an independent process.
"""

import asyncio
import click
import os
import select
import signal
import subprocess
import sys
from pathlib import Path

import typer
from typer.core import TyperGroup
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from mano import __version__
from mano.cli.agents import (
    add_agent,
    agents_app,
    delete_agent,
    list_agents,
    logs_agent_cmd,
    restart_agent_cmd,
    set_default,
    show_agent,
    start_agent_cmd,
    stop_agent_cmd,
)

console = Console()


class ManobotGroup(TyperGroup):
    """Typer group that lets unknown first args fall through to the shortcut handler."""

    def invoke(self, ctx):
        args = [*ctx._protected_args, *ctx.args]
        if args:
            cmd_name = args[0]
            cmd = self.get_command(ctx, cmd_name)

            if cmd is None and ctx.token_normalize_func is not None:
                cmd = self.get_command(ctx, ctx.token_normalize_func(cmd_name))

            if cmd is None:
                ctx.args = args
                ctx._protected_args = []
                with ctx:
                    return click.Command.invoke(self, ctx)

        return super().invoke(ctx)

# Create main app
app = typer.Typer(
    cls=ManobotGroup,
    name="manobot",
    help="""manobot - Multi-Agent Management

Manobot provides multi-agent capabilities, allowing you to:
  - Run multiple AI agents as isolated subprocesses
  - Route messages from different channels to specific agents
  - Manage agents through a simple CLI interface

Quick Start:
  1. manobot init              Initialize manobot environment
  2. manobot onboard assistant Initialize or refresh an agent
  3. manobot list              View configured agents
  4. manobot assistant -m "Hi" Chat with one agent directly
  5. manobot assistant channels status
                               Inspect one agent's channel config
  6. manobot tui               Pick an agent and open a simple chat UI
  7. manobot gateway           Start the gateway (supervisor)
""",
    no_args_is_help=True,
    rich_markup_mode="rich",
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)

# Add agents subcommand
app.add_typer(agents_app, name="agents")
app.command("list")(list_agents)
app.command("show")(show_agent)
app.command("add")(add_agent)
app.command("delete")(delete_agent)
app.command("default")(set_default)
app.command("start")(start_agent_cmd)
app.command("stop")(stop_agent_cmd)
app.command("restart")(restart_agent_cmd)
app.command("logs")(logs_agent_cmd)

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
_AGENT_SCOPED_SHORTCUTS = {"channels"}


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


def _print_agent_response(response: object, render_markdown: bool, agent_id: str = "manobot") -> None:
    """Render assistant response with consistent terminal styling."""
    content = getattr(response, "content", response)
    if content is None:
        content = ""
    elif not isinstance(content, str):
        content = str(content)
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{agent_id}[/cyan]")
    console.print(body)
    console.print()


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


def _build_agent_scoped_shortcut_argv(agent_id: str, scoped_args: list[str]) -> list[str] | None:
    """Map agent-scoped shortcuts like `<agent-id> channels ...` to real commands."""
    if not scoped_args:
        return None

    scope_cmd = scoped_args[0]
    if scope_cmd not in _AGENT_SCOPED_SHORTCUTS:
        return None

    if len(scoped_args) == 1 or scoped_args[1].startswith("-"):
        return [scope_cmd, *scoped_args[1:]]

    return [scope_cmd, scoped_args[1], "--agent", agent_id, *scoped_args[2:]]


def _build_agent_shortcut_argv(raw_args: list[str]) -> list[str] | None:
    """Map top-level shorthand invocations to agent or agent-scoped commands."""
    if not raw_args:
        return None

    first = raw_args[0]
    if first.startswith("-"):
        return ["agent", *raw_args]

    scoped_shortcut = _build_agent_scoped_shortcut_argv(first, raw_args[1:])
    if scoped_shortcut is not None:
        return scoped_shortcut

    return ["agent", "--agent", first, *raw_args[1:]]


def _load_agent_runtime_context(agent_id: str):
    """Load one registered agent's standalone config and resolved scope."""
    from mano.agents.registry import load_registered_agent_config
    from mano.core import build_agent_scope

    config = load_registered_agent_config(agent_id)
    scope = build_agent_scope(config, agent_id)
    if scope is None:
        raise RuntimeError(f"Cannot resolve scope for agent '{agent_id}'")
    return config, scope


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
    isolated agent when no agent config exists yet. It is automatically
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
        console.print(f"[green]OK[/green] Registry: {result['registry_path']}")

        if result["created_default_agent"]:
            console.print("[green]OK[/green] Created default agent config")

        if result["default_agent"]:
            console.print(f"[green]OK[/green] Default agent: {result['default_agent']}")

        console.print("\n[bold green]Manobot initialized successfully![/bold green]")
        console.print("\nNext steps:")
        console.print("  1. Run 'manobot list' to see configured agents")
        console.print("  2. Run 'manobot add <id>' to add more agents")
        console.print("  3. Run 'manobot gateway' to start the gateway")
    else:
        console.print("[red]Initialization failed:[/red]")
        for error in result["errors"]:
            console.print(f"  - {error}")
        raise typer.Exit(1)


@app.command()
def onboard(
    agent_id: str = typer.Argument(..., help="Agent ID to initialize or refresh"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
):
    """Initialize or refresh a specific agent's config and workspace."""
    from mano.agents.init import initialize_manobot
    from mano.agents.registry import is_registered, load_registered_agent_config
    from mano.agents.onboard import onboard_agent
    from mano.core.scope import build_agent_scope, normalize_agent_id

    init_result = initialize_manobot()
    normalized_id = normalize_agent_id(agent_id)
    existing_ids: set[str] = set()
    if is_registered(normalized_id):
        existing_ids.add(normalized_id)
    mode = "refresh"
    auto_created_target = (
        init_result["created_default_agent"]
        and init_result["default_agent"] == normalized_id
    )

    if normalized_id in existing_ids and not auto_created_target:
        console.print(f"[yellow]Agent '{normalized_id}' already exists[/yellow]")
        existing_scope = build_agent_scope(load_registered_agent_config(normalized_id), normalized_id)
        if existing_scope:
            console.print(f"  Current model: {existing_scope.model or '-'}")
            console.print(f"  Current workspace: {existing_scope.workspace}")
        console.print("")
        console.print("  [bold]y[/bold] = reset to defaults (existing values will be overwritten)")
        console.print("  [bold]N[/bold] = refresh config, keeping existing values and adding new fields")
        console.print("")

        choice = typer.prompt("Overwrite?", default="N", show_default=False)
        if choice.lower() == "y":
            mode = "reset"
        elif choice.lower() != "n":
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    result = onboard_agent(normalized_id, workspace=workspace, mode=mode)

    effective_action = result.action
    if (
        normalized_id not in existing_ids
        or auto_created_target
    ) and result.action == "refreshed":
        effective_action = "created"

    action_label = {
        "created": "Onboarded",
        "refreshed": "Refreshed",
        "reset": "Reset",
    }[effective_action]
    console.print(f"[green]✓[/green] {action_label} agent '{result.agent_id}'")
    console.print(f"  Registry:      {result.registry_path}")
    console.print(f"  Agent config:  {result.agent_config_path}")
    console.print(f"  Workspace:     {result.scope.workspace}")
    console.print(f"  Memory:        {result.scope.memory_dir}")
    console.print(f"  Sessions:      {result.scope.sessions_dir}")

    if result.templates_added:
        console.print(f"[green]✓[/green] Synced workspace templates ({len(result.templates_added)} new file(s))")
    else:
        console.print("[green]✓[/green] Workspace templates already up to date")

    console.print("\nNext steps:")
    console.print(f"  1. Run 'manobot show {result.agent_id}' to inspect the agent")
    console.print("  2. Run 'manobot gateway' to start the supervisor")


@app.command()
def status():
    """Show status of manobot agents (configured + running).

    Reads the process state file to show which agents are running,
    their ports, PIDs, and uptime.

    Example:
        manobot status
    """
    from mano.agents.init import initialize_manobot
    from mano.agents.registry import list_registered_agent_ids, resolve_default_registered_agent_id
    from mano.core.state import cleanup_stale, is_supervisor_alive, load_state, save_state

    initialize_manobot()
    agent_ids = list_registered_agent_ids()
    default_id = resolve_default_registered_agent_id()

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
        log_paths = [(aid, agent_state.log_path) for aid, agent_state in state.agents.items() if agent_state.log_path]
        if log_paths:
            console.print("\n[bold]Agent Logs:[/bold]")
            for aid, log_path in log_paths:
                console.print(f"  {aid}: {log_path}", soft_wrap=True)
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

    from mano.agents.init import initialize_manobot
    from mano.agents.registry import is_registered
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

    if agent and not is_registered(agent):
        console.print(f"[red]Agent '{agent}' not found[/red]")
        raise typer.Exit(1)

    manager = ProcessManager(base_port=base_port)
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
                    if result.log_path:
                        console.print(f"[dim]  log: {result.log_path}[/dim]", soft_wrap=True)
                    raise typer.Exit(1)
            else:
                console.print("Starting all agents...")
                results = await manager.start_all()
                for aid, result in results.items():
                    if result.status == "running":
                        console.print(f"  [green]OK[/green] {aid} -> port {result.port} (pid={result.pid})")
                    else:
                        console.print(f"  [red]FAIL[/red] {aid}: {result.error_message}")
                        if result.log_path:
                            console.print(f"    [dim]log: {result.log_path}[/dim]", soft_wrap=True)

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

    from mano.agents.init import initialize_manobot
    from mano.agents.registry import (
        list_registered_agent_ids,
        resolve_default_registered_agent_id,
    )

    if logs:
        logger.enable("agent")
        logger.enable("manobot")
    else:
        logger.disable("agent")

    # Auto-initialize
    initialize_manobot()

    # Resolve target agent
    configured = list_registered_agent_ids()
    default_id = resolve_default_registered_agent_id()
    target_id = agent_id or default_id

    if target_id not in configured:
        console.print(f"[red]Agent '{target_id}' not found[/red]")
        console.print(f"Available agents: {', '.join(configured)}")
        raise typer.Exit(1)

    try:
        config, scope = _load_agent_runtime_context(target_id)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if direct:
        _agent_chat_direct(config, scope, target_id, message, session_id, markdown, logs)
    else:
        _agent_chat_http(config, scope, target_id, message, session_id, markdown)


@app.command()
def tui(
    agent_id: str | None = typer.Argument(None, help="Agent ID to chat with"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show runtime logs during chat"),
):
    """Launch a simple prompt_toolkit-based chat UI."""
    from mano.agents.init import initialize_manobot
    from mano.agents.registry import list_registered_agent_ids, resolve_default_registered_agent_id
    from mano.core import normalize_agent_id

    initialize_manobot()

    configured = list_registered_agent_ids()
    default_id = resolve_default_registered_agent_id()
    target_id = normalize_agent_id(agent_id) if agent_id else None

    if target_id and target_id not in configured:
        console.print(f"[red]Agent '{agent_id}' not found[/red]")
        console.print(f"Available agents: {', '.join(configured)}")
        raise typer.Exit(1)

    if target_id is None:
        from prompt_toolkit.shortcuts import radiolist_dialog

        target_id = radiolist_dialog(
            title="manobot tui",
            text="Select an agent",
            values=[
                (aid, f"{aid} (default)" if aid == default_id else aid)
                for aid in configured
            ],
        ).run()
        if not target_id:
            raise typer.Exit(0)

    agent_chat(
        message=None,
        agent_id=target_id,
        session_id=session_id,
        markdown=markdown,
        direct=True,
        logs=logs,
    )


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

    # Resolve config-wide channels and providers for this isolated agent.
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
def main(ctx: typer.Context):
    """Manobot - Multi-Agent Management Layer."""
    if ctx.invoked_subcommand is not None or ctx.resilient_parsing:
        return

    shortcut_argv = _build_agent_shortcut_argv(list(ctx.args))
    if shortcut_argv is None:
        console.print(ctx.get_help())
        raise typer.Exit()

    result = subprocess.run([sys.argv[0], *shortcut_argv], check=False)
    raise typer.Exit(result.returncode)


if __name__ == "__main__":
    app()
