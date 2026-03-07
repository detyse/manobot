"""Main CLI entry point for manobot.

Extends nanobot CLI with multi-agent management capabilities.
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
from rich.text import Text

from manobot import __version__
from manobot.cli.agents import agents_app

console = Console()

# Create main app
app = typer.Typer(
    name="manobot",
    help="""🤖 manobot - Multi-Agent Management for Nanobot

Manobot extends nanobot with multi-agent capabilities, allowing you to:
  • Run multiple AI agents with isolated workspaces and memories
  • Route messages from different channels to specific agents
  • Manage agents through a simple CLI interface

Quick Start:
  1. manobot init              Initialize manobot environment
  2. manobot agents list       View configured agents
  3. manobot agents add <id>   Add a new agent
  4. manobot gateway           Start the gateway

For more help: https://github.com/HKUDS/nanobot
""",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Add agents subcommand
app.add_typer(agents_app, name="agents")

# Register channels and provider subcommands
from manobot.cli.channels import channels_app
from manobot.cli.providers import provider_app

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
    console.print(f"[cyan]🤖 {agent_id}[/cyan]")
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


def _make_provider_for_model(config, model: str | None = None, provider_override: str | None = None):
    """Create the appropriate LLM provider for a specific model.

    This is a multi-agent aware version of nanobot's _make_provider that
    supports dynamic model selection per agent.

    Args:
        config: Application configuration
        model: Model string (e.g., 'anthropic/claude-sonnet-4-20250514'), uses default if None
        provider_override: Optional provider name from agent config (overrides auto-detection)

    Returns:
        LLMProvider instance
    """
    from nanobot.providers.custom_provider import CustomProvider
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    from nanobot.providers.registry import find_by_name

    effective_model = model or config.agents.defaults.model

    # Use agent-level provider if specified and not "auto", otherwise auto-detect
    if provider_override and provider_override != "auto":
        provider_name = provider_override
        p = getattr(config.providers, provider_name, None)
        if p is None:
            console.print(f"[red]Error: Unknown provider '{provider_name}'.[/red]")
            console.print("Set a valid provider name in agents.list[].provider.")
            raise typer.Exit(1)
    else:
        provider_name = config.get_provider_name(effective_model)
        p = config.get_provider(effective_model)

    api_base = None
    if provider_override and provider_override != "auto":
        api_base = p.api_base if p else None
        spec = find_by_name(provider_name)
        if not api_base and spec and spec.is_gateway and spec.default_api_base:
            api_base = spec.default_api_base
    else:
        api_base = config.get_api_base(effective_model)

    # OpenAI Codex (OAuth)
    if provider_name == "openai_codex" or effective_model.startswith("openai-codex/"):
        return OpenAICodexProvider(default_model=effective_model)

    # Custom: direct OpenAI-compatible endpoint, bypasses LiteLLM
    if provider_name == "custom":
        return CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=api_base or "http://localhost:8000/v1",
            default_model=effective_model,
        )

    spec = find_by_name(provider_name)
    if not effective_model.startswith("bedrock/") and not (p and p.api_key) and not (spec and spec.is_oauth):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers section")
        raise typer.Exit(1)

    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=api_base,
        default_model=effective_model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
    )



@app.command()
def version():
    """Show manobot and nanobot version information."""
    from nanobot import __logo__ as nanobot_logo
    from nanobot import __version__ as nanobot_version

    console.print(f"[bold cyan]manobot[/bold cyan] version: [green]{__version__}[/green]")
    console.print(f"{nanobot_logo} [bold cyan]nanobot[/bold cyan] version: [green]{nanobot_version}[/green]")
    console.print("\n[dim]Manobot extends nanobot with multi-agent management capabilities.[/dim]")


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Force re-initialization, overwriting existing config"),
):
    """Initialize manobot environment and create default agent.

    This command sets up the manobot state directory and creates a default
    agent based on your existing nanobot configuration. It is automatically
    run on first 'manobot gateway' start.

    Examples:
        manobot init              # First-time setup
        manobot init --force      # Re-initialize (resets to defaults)
    """
    from manobot.agents.init import get_manobot_state_dir, initialize_manobot

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
            console.print("[green]✓[/green] Migrated existing nanobot config")

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
    """Show status overview of manobot and configured agents.

    Displays a summary of all configured agents, the default agent,
    and active channel-to-agent bindings.

    Example:
        manobot status
    """
    from manobot.agents.init import initialize_manobot
    from manobot.agents.scope import (
        list_agent_ids,
        resolve_fallback_agent_id,
    )
    from nanobot.config.loader import load_config

    # Auto-initialize if needed
    initialize_manobot()

    config = load_config()
    agent_ids = list_agent_ids(config)
    default_id = resolve_fallback_agent_id(config)

    console.print("\n[bold]🤖 Manobot Status[/bold]\n")
    console.print(f"[cyan]Configured agents:[/cyan] {len(agent_ids)}")
    console.print(f"[cyan]Default agent:[/cyan] [green]{default_id}[/green]")

    # Show bindings summary
    bindings = config.agents.bindings
    if bindings:
        console.print(f"[cyan]Active bindings:[/cyan] {len(bindings)}")
    else:
        console.print("[cyan]Active bindings:[/cyan] 0 (all traffic routes to default)")

    console.print("\n[dim]Run 'manobot agents list' for detailed agent information[/dim]")


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port (default: 18790)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose debug output"),
    agent: str = typer.Option(None, "--agent", "-a", help="Run only a specific agent by ID"),
):
    """Start the manobot gateway with multi-agent support.

    Launches the gateway server that handles incoming messages from configured
    channels (Telegram, Discord, etc.) and routes them to the appropriate agent
    based on bindings configuration.

    On first run, automatically initializes manobot and creates a default
    agent from your existing nanobot configuration.

    Examples:
        manobot gateway                    # Start with default settings
        manobot gateway --port 8080        # Use custom port
        manobot gateway --verbose          # Enable debug logging
        manobot gateway --agent coder      # Run only the 'coder' agent
    """
    from loguru import logger

    from manobot.accounts.registry import AccountRegistry
    from manobot.agents.init import ensure_default_agent, initialize_manobot
    from manobot.agents.pool import AgentPool
    from manobot.agents.scope import (
        list_agent_ids,
        normalize_agent_id,
        resolve_fallback_agent_id,
    )
    from manobot.bindings.router import MessageRouter
    from manobot.channels.multi_manager import MultiAccountChannelManager
    from manobot.sessions.ownership import PeerFingerprint, SessionOwnershipStore
    from nanobot.bus.events import InboundMessage, OutboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.utils.helpers import sync_workspace_templates

    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
        logger.enable("nanobot")
        logger.enable("manobot")
    else:
        logger.disable("nanobot")

    # Auto-initialize on first run
    console.print("[dim]Checking manobot initialization...[/dim]")
    result = initialize_manobot()

    if not result["success"]:
        console.print("[red]Initialization failed. Run 'manobot init' first.[/red]")
        raise typer.Exit(1)

    # Load config
    config = load_config()

    # Ensure default agent exists
    ensure_default_agent(config)
    config = load_config()  # Reload after potential modifications

    # Sync workspace templates
    sync_workspace_templates(config.workspace_path)

    agent_ids = list_agent_ids(config)
    default_id = resolve_fallback_agent_id(config)

    console.print(f"[green]✓[/green] Loaded {len(agent_ids)} agent(s), default: {default_id}")

    # Single agent mode validation
    single_agent_mode = agent is not None
    if single_agent_mode:
        if agent not in agent_ids:
            console.print(f"[red]Agent '{agent}' not found[/red]")
            console.print(f"Available agents: {', '.join(agent_ids)}")
            raise typer.Exit(1)
        console.print(f"[yellow]Running single agent mode: {agent}[/yellow]")

    # Show bindings
    bindings = config.agents.bindings
    if bindings and not single_agent_mode:
        console.print(f"[green]✓[/green] {len(bindings)} binding(s) configured")

        # Validate: warn about bindings referencing unknown agents
        configured_set = set(normalize_agent_id(i) for i in agent_ids)
        for idx, binding in enumerate(bindings):
            bid = normalize_agent_id(binding.agent_id)
            if bid not in configured_set:
                console.print(
                    f"[yellow]  ⚠ Binding #{idx} references unknown agent '{bid}' "
                    f"— messages will route to default agent '{default_id}'[/yellow]"
                )

    console.print(f"\n🤖 Starting manobot gateway on port {port}...")

    # Create message bus
    bus = MessageBus()

    # Create provider factory for AgentPool
    def provider_factory(model: str | None = None, provider_override: str | None = None):
        return _make_provider_for_model(config, model, provider_override=provider_override)

    # Create cron service first (needed by AgentPool)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create core multi-agent components
    pool = AgentPool(config, bus, provider_factory, cron_service=cron)
    router = MessageRouter(config)
    ownership_store = SessionOwnershipStore()

    # Create account registry and multi-account channel manager
    account_registry = AccountRegistry(config)
    channels = MultiAccountChannelManager(config, bus, account_registry)

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    # Cron job callback
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the appropriate agent."""
        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.message import MessageTool

        # Determine which agent should handle this cron job
        # Use default agent for cron jobs (could be extended to support per-job agent)
        target_agent_id = default_id if not single_agent_mode else agent

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        agent_loop = await pool.get_or_create_agent(target_agent_id)

        # Prevent agent from scheduling new cron jobs during execution
        cron_tool = agent_loop.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            response = await agent_loop.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        message_tool = agent_loop.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response
            ))
        return response

    cron.on_job = on_cron_job

    # Heartbeat service
    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        enabled = set(channels.enabled_channels)
        # Get session manager from default agent if available
        default_agent = pool.get_agent_sync(default_id if not single_agent_mode else agent)
        if default_agent:
            session_mgr = pool.get_session_manager(default_id if not single_agent_mode else agent)
            if session_mgr:
                for item in session_mgr.list_sessions():
                    key = item.get("key") or ""
                    # Session keys can be:
                    # - Legacy format: channel:chat (e.g., "telegram:12345")
                    # - Multi-agent format: agent:channel:chat (e.g., "assistant:telegram:12345")
                    parts = key.split(":")
                    if len(parts) == 2:
                        # Legacy format: channel:chat
                        channel_name, chat_id = parts
                    elif len(parts) >= 3:
                        # Multi-agent format: agent:channel:chat (chat_id may contain colons)
                        channel_name = parts[1]
                        chat_id = ":".join(parts[2:])
                    else:
                        continue
                    if channel_name in {"cli", "system"}:
                        continue
                    if channel_name in enabled and chat_id:
                        return channel_name, chat_id
        return "cli", "direct"

    async def on_heartbeat_execute(tasks: str) -> str:
        """Execute heartbeat tasks through the agent."""
        channel_name, chat_id = _pick_heartbeat_target()
        target_agent_id = default_id if not single_agent_mode else agent
        agent_loop = await pool.get_or_create_agent(target_agent_id)

        async def _silent(*_args, **_kwargs):
            pass

        return await agent_loop.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel_name,
            chat_id=chat_id,
            on_progress=_silent,
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Deliver a heartbeat response to the user's channel."""
        channel_name, chat_id = _pick_heartbeat_target()
        if channel_name == "cli":
            return
        await bus.publish_outbound(OutboundMessage(
            channel=channel_name,
            chat_id=chat_id,
            content=response
        ))

    hb_cfg = config.gateway.heartbeat
    # Create a default provider for heartbeat service
    default_provider = provider_factory(config.agents.defaults.model)
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=default_provider,
        model=config.agents.defaults.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")
    console.print("")

    # Message dispatch function
    async def dispatch_inbound(msg: InboundMessage) -> None:
        """Route and process an inbound message.

        Pipeline:
        1. Extract InboundContext -> route decision
        2. Build PeerFingerprint -> session ownership
        3. Get/create agent -> process message
        """
        # 1. Route decision
        if single_agent_mode:
            target_agent_id = agent
        else:
            peer_type = msg.metadata.get("peer_type")
            if peer_type is None and msg.metadata.get("is_group") is not None:
                peer_type = "group" if msg.metadata.get("is_group") else "direct"

            route = router.route(
                channel=msg.channel,
                chat_id=msg.chat_id,
                sender_id=msg.sender_id,
                peer_type=peer_type,
                guild_id=msg.metadata.get("guild_id"),
                team_id=msg.metadata.get("team_id"),
                account_id=msg.account_id,
                parent_peer_id=msg.metadata.get("parent_peer_id"),
            )
            target_agent_id = route.agent_id

            if route.binding_index is not None:
                logger.debug(
                    "Routed {}/{} -> agent '{}' (tier={}, binding #{})",
                    msg.channel, msg.chat_id, target_agent_id,
                    route.tier.name, route.binding_index,
                )

        # 2. Session ownership
        if msg.session_key_override:
            # Respect channel-provided session_key_override (e.g. Slack thread)
            fingerprint = PeerFingerprint(
                channel=msg.channel,
                account_id=msg.account_id,
                peer_id=msg.chat_id,
                thread_id=msg.session_key_override,
            )
        else:
            fingerprint = PeerFingerprint(
                channel=msg.channel,
                account_id=msg.account_id,
                peer_id=msg.chat_id,
            )

        ownership = ownership_store.resolve(target_agent_id, fingerprint)
        session_key = ownership.session_key

        # 3. Get or create agent
        agent_loop = await pool.get_or_create_agent(target_agent_id)

        # Handle /stop: cancel the tracked task for this session, then respond
        if msg.content.strip().lower() == "/stop":
            tasks = agent_loop._active_tasks.pop(session_key, [])
            cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
            for t in tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            sub_cancelled = await agent_loop.subagents.cancel_by_session(session_key)
            total = cancelled + sub_cancelled
            content = f"\u23f9 Stopped {total} task(s)." if total else "No active task to stop."
            await bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content,
            ))
            return

        # Register current task in the agent loop so /stop can find it
        current_task = asyncio.current_task()
        if current_task is not None:
            agent_loop._active_tasks.setdefault(session_key, []).append(current_task)

        # Process message
        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            """Send progress updates to the channel."""
            ch = config.channels
            if ch and tool_hint and not ch.send_tool_hints:
                return
            if ch and not tool_hint and not ch.send_progress:
                return
            await bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
                metadata={"_progress": True, "_tool_hint": tool_hint},
            ))

        try:
            response = await agent_loop.process_direct(
                msg.content,
                session_key=session_key,
                channel=msg.channel,
                chat_id=msg.chat_id,
                media=msg.media,
                on_progress=on_progress,
                metadata=msg.metadata,
            )
        finally:
            # Unregister task from agent loop tracking
            task_list = agent_loop._active_tasks.get(session_key)
            if task_list and current_task in task_list:
                task_list.remove(current_task)
                if not task_list:
                    agent_loop._active_tasks.pop(session_key, None)

        # Send response
        if response:
            await bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=response,
                metadata=msg.metadata,
            ))

    # Main async run function
    async def run():
        # Track active message tasks for graceful shutdown
        active_tasks: set[asyncio.Task] = set()

        def task_done_callback(task: asyncio.Task):
            active_tasks.discard(task)
            # Log exceptions from tasks
            if not task.cancelled():
                exc = task.exception()
                if exc:
                    logger.exception("Error processing message: {}", exc)

        try:
            # Initialize agents
            if single_agent_mode:
                await pool.get_or_create_agent(agent)
                console.print(f"[green]✓[/green] Agent '{agent}' ready")
            else:
                await pool.initialize_configured_agents()
                console.print("[green]✓[/green] All agents initialized")

            # Start services
            await cron.start()
            await heartbeat.start()

            # Message processing loop - dispatch tasks in parallel
            async def message_loop():
                while True:
                    try:
                        msg = await bus.consume_inbound()
                        # Create task for parallel processing instead of awaiting inline
                        task = asyncio.create_task(dispatch_inbound(msg))
                        active_tasks.add(task)
                        task.add_done_callback(task_done_callback)
                    except asyncio.CancelledError:
                        break

            # Run everything
            await asyncio.gather(
                message_loop(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            # Cancel active message tasks
            for task in active_tasks:
                task.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)

            heartbeat.stop()
            cron.stop()
            await pool.stop_all()
            await channels.stop_all()

    asyncio.run(run())


@app.command("agent")
def agent_chat(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    agent_id: str = typer.Option(None, "--agent", "-a", help="Agent ID to talk to (default: fallback agent)"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show runtime logs during chat"),
):
    """Interact with an agent directly.

    In single-message mode (-m), sends one message and prints the response.
    Without -m, starts an interactive REPL session.

    Examples:
        manobot agent -m "What is 2+2?"
        manobot agent --agent coder -m "Write a hello world"
        manobot agent                          # interactive mode
        manobot agent --agent coder            # interactive with specific agent
    """
    from loguru import logger

    from manobot.agents.init import ensure_default_agent, initialize_manobot
    from manobot.agents.pool import AgentPool
    from manobot.agents.scope import (
        build_agent_scope,
        list_agent_ids,
        resolve_fallback_agent_id,
    )
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService
    from nanobot.utils.helpers import sync_workspace_templates

    if logs:
        logger.enable("nanobot")
        logger.enable("manobot")
    else:
        logger.disable("nanobot")

    # Auto-initialize
    initialize_manobot()
    config = load_config()
    ensure_default_agent(config)
    config = load_config()

    # Resolve target agent
    fallback_id = resolve_fallback_agent_id(config)
    target_id = agent_id or fallback_id

    configured = list_agent_ids(config)
    if target_id not in configured:
        console.print(f"[red]Agent '{target_id}' not found[/red]")
        console.print(f"Available agents: {', '.join(configured)}")
        raise typer.Exit(1)

    scope = build_agent_scope(config, target_id)
    if not scope:
        console.print(f"[red]Cannot resolve scope for agent '{target_id}'[/red]")
        raise typer.Exit(1)

    sync_workspace_templates(scope.workspace)

    # Create runtime components
    bus = MessageBus()
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    def provider_factory(model=None, provider_override=None):
        return _make_provider_for_model(config, model, provider_override=provider_override)

    pool = AgentPool(config, bus, provider_factory, cron_service=cron)

    # Build session key
    session_key = f"agent:{target_id}:default:cli:direct"
    if ":" in session_id:
        cli_channel, cli_chat_id = session_id.split(":", 1)
        session_key = f"agent:{target_id}:default:{cli_channel}:{cli_chat_id}"
    else:
        cli_channel, cli_chat_id = "cli", session_id

    # Spinner context
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext
            return nullcontext()
        return console.status(f"[dim]{scope.name or target_id} is thinking...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = config.channels
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        console.print(f"  [dim]↳ {content}[/dim]")

    if message:
        # Single-message mode
        async def run_once():
            agent_loop = await pool.get_or_create_agent(target_id)
            with _thinking_ctx():
                response = await agent_loop.process_direct(
                    message, session_key, on_progress=_cli_progress,
                )
            _print_agent_response(response, render_markdown=markdown, agent_id=scope.name or target_id)
            await pool.stop_all()

        asyncio.run(run_once())
    else:
        # Interactive REPL mode
        _init_prompt_session()
        display_name = scope.name or target_id
        console.print(f"🤖 Interactive mode with [bold]{display_name}[/bold] "
                       f"(type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n")

        def _exit_on_sigint(signum, frame):
            _restore_terminal()
            console.print("\nGoodbye!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)

        async def run_interactive():
            agent_loop = await pool.get_or_create_agent(target_id)
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[str] = []

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        if msg.metadata.get("_progress"):
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = config.channels
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                console.print(f"  [dim]↳ {msg.content}[/dim]")
                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            console.print()
                            _print_agent_response(msg.content, render_markdown=markdown, agent_id=display_name)
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

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

                        turn_done.clear()
                        turn_response.clear()

                        await bus.publish_inbound(InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                        ))

                        with _thinking_ctx():
                            await turn_done.wait()

                        if turn_response:
                            _print_agent_response(turn_response[0], render_markdown=markdown, agent_id=display_name)
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
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await pool.stop_all()

        asyncio.run(run_interactive())


@app.command()
def sync():
    """Sync with upstream nanobot repository.

    Fetches and shows changes from the upstream nanobot repository.
    This helps keep your manobot installation up-to-date with the
    latest nanobot features and bug fixes.

    The sync script (scripts/sync-upstream.sh) will:
      1. Fetch latest changes from upstream
      2. Show a summary of new commits
      3. Prompt for confirmation before merging

    Example:
        manobot sync

    Note: You may need to resolve merge conflicts if you've modified
    files in the nanobot/ directory.
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
    """Manobot - Multi-Agent Management Layer for Nanobot."""
    pass


if __name__ == "__main__":
    app()
