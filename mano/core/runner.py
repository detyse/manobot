"""Agent runner — standalone process entry point.

Starts a single agent with channels and a thin HTTP API.
Designed to be launched by ProcessManager as a subprocess:

    python -m mano.core.runner --agent-id default --port 18791 --config /path/to/config.json
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path

from loguru import logger


def _make_provider(
    config,
    *,
    model_override: str | None = None,
    provider_override: str | None = None,
    max_tokens_override: int | None = None,
    temperature_override: float | None = None,
    reasoning_effort_override: str | None = None,
):
    """Create LLM provider from config using new provider system."""
    from agent.providers.base import GenerationSettings
    from agent.providers.anthropic_provider import AnthropicProvider
    from agent.providers.azure_openai_provider import AzureOpenAIProvider
    from agent.providers.openai_codex_provider import OpenAICodexProvider
    from agent.providers.openai_compat_provider import OpenAICompatProvider
    from agent.providers.registry import find_by_name

    defaults = config.agents.defaults
    model = model_override or defaults.model
    forced_provider = provider_override or defaults.provider

    if forced_provider != "auto":
        spec = find_by_name(forced_provider)
    else:
        provider_name = config.get_provider_name(model)
        spec = find_by_name(provider_name) if provider_name else None

    p = config.get_provider(model)

    if spec is None:
        # Fallback to OpenAI-compatible provider
        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    elif spec.backend == "anthropic":
        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    elif spec.backend == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            logger.error("Azure OpenAI requires api_key and api_base")
            sys.exit(1)
        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    elif spec.backend == "openai_codex":
        provider = OpenAICodexProvider(default_model=model)
    else:
        # Default to OpenAI-compatible provider
        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
        )

    provider.generation = GenerationSettings(
        temperature=temperature_override if temperature_override is not None else defaults.temperature,
        max_tokens=max_tokens_override if max_tokens_override is not None else defaults.max_tokens,
        reasoning_effort=reasoning_effort_override or defaults.reasoning_effort,
    )
    return provider


# ---------------------------------------------------------------------------
# HTTP API (aiohttp)
# ---------------------------------------------------------------------------

def _create_http_app(agent_loop, agent_id: str, model: str, start_time: float, shutdown_event: asyncio.Event):
    """Build an aiohttp application with health/chat/stop endpoints."""
    from aiohttp import web

    async def handle_health(request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "agent_id": agent_id,
            "model": model,
            "uptime": round(time.time() - start_time, 1),
        })

    async def handle_chat(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        message = data.get("message", "")
        if not message:
            return web.json_response({"error": "Missing 'message'"}, status=400)

        session_key = data.get("session_key") or f"agent:{agent_id}:default:api:direct"
        channel = data.get("channel", "api")
        chat_id = data.get("chat_id", "direct")

        try:
            response = await agent_loop.process_direct(
                message,
                session_key=session_key,
                channel=channel,
                chat_id=chat_id,
            )
            return web.json_response({"response": response, "session_key": session_key})
        except Exception as e:
            logger.error("Chat error: {}", e)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_stop(request: web.Request) -> web.Response:
        shutdown_event.set()
        return web.json_response({"status": "stopping"})

    app = web.Application()
    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/api/stop", handle_stop)
    return app


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def _run(agent_id: str, port: int, config_path: Path) -> None:
    """Async entry point: start agent + channels + HTTP server."""
    from aiohttp import web

    from agent.agent.loop import AgentLoop
    from agent.bus.queue import MessageBus
    from agent.channels.manager import ChannelManager
    from agent.config.loader import load_config
    from agent.cron.service import CronService
    from agent.cron.types import CronJob
    from agent.heartbeat.service import HeartbeatService
    from agent.session.manager import SessionManager
    from agent.utils.helpers import sync_workspace_templates

    # Load the standalone config for this agent.
    config = load_config(config_path)
    workspace = config.workspace_path
    sync_workspace_templates(workspace)
    defaults = config.agents.defaults

    # Core components
    bus = MessageBus()
    provider = _make_provider(config, model_override=defaults.model)
    agent_entry = config.agents.agent_list[0] if config.agents.agent_list else None
    sessions_dir = (
        Path(agent_entry.sessions_dir).expanduser()
        if agent_entry and agent_entry.sessions_dir
        else None
    )
    memory_dir = (
        Path(agent_entry.memory_dir).expanduser()
        if agent_entry and agent_entry.memory_dir
        else None
    )
    session_manager = SessionManager(workspace, sessions_dir=sessions_dir)

    cron_root = (
        Path(agent_entry.agent_dir).expanduser()
        if agent_entry and agent_entry.agent_dir
        else workspace
    )
    cron_store_path = cron_root / "cron" / "jobs.json"
    cron_store_path.parent.mkdir(parents=True, exist_ok=True)
    cron = CronService(cron_store_path)

    # Restart / shutdown coordination
    shutdown_event = asyncio.Event()
    restart_requested = False

    def _request_restart():
        nonlocal restart_requested
        restart_requested = True
        shutdown_event.set()

    # Create AgentLoop (same pattern as agent/cli/commands.py)
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=defaults.model,
        max_iterations=defaults.max_tool_iterations,
        context_window_tokens=defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        memory_dir=memory_dir,
        timezone=defaults.timezone,
        hooks=[],
        on_restart=_request_restart,
    )

    # Cron callback
    async def on_cron_job(job: CronJob) -> str | None:
        from agent.agent.tools.cron import CronTool
        from agent.agent.tools.message import MessageTool

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            response = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            from agent.bus.events import OutboundMessage

            await bus.publish_outbound(
                OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to,
                    content=response,
                )
            )
        return response

    cron.on_job = on_cron_job

    # Channel manager
    channels = ChannelManager(config, bus)

    # Heartbeat
    def _pick_heartbeat_target() -> tuple[str, str]:
        from mano.core.scope import parse_session_key

        enabled = set(channels.enabled_channels)
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if not key:
                continue
            parsed = parse_session_key(key)
            channel = parsed.get("channel", "")
            chat_id = parsed.get("peer_id", "")
            if not channel or channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        return "cli", "direct"

    async def on_heartbeat_execute(tasks: str) -> str:
        channel, chat_id = _pick_heartbeat_target()
        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=lambda *a, **k: asyncio.sleep(0),
        )

    async def on_heartbeat_notify(response: str) -> None:
        from agent.bus.events import OutboundMessage

        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return
        await bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response)
        )

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=workspace,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    # HTTP API
    start_time = time.time()
    http_app = _create_http_app(agent, agent_id, agent.model, start_time, shutdown_event)

    runner = web.AppRunner(http_app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)

    # Signal handling
    def _on_signal():
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _on_signal)

    # Start everything
    logger.info("Agent '{}' starting on port {} (model={})", agent_id, port, agent.model)

    try:
        await site.start()
        await cron.start()
        await heartbeat.start()

        # Run agent loop and channels in background
        asyncio.create_task(agent.run())
        asyncio.create_task(channels.start_all())

        # Wait for shutdown signal
        await shutdown_event.wait()
        logger.info("Agent '{}' shutting down...", agent_id)

    except KeyboardInterrupt:
        logger.info("Agent '{}' interrupted", agent_id)
    finally:
        agent.stop()
        heartbeat.stop()
        cron.stop()
        await agent.close_mcp()
        await channels.stop_all()
        await runner.cleanup()
        logger.info("Agent '{}' stopped", agent_id)

    if restart_requested:
        logger.info("Agent '{}' exiting with code 75 (restart requested)", agent_id)
        sys.exit(75)


def main():
    parser = argparse.ArgumentParser(description="Manobot agent runner")
    parser.add_argument("--agent-id", required=True, help="Agent identifier")
    parser.add_argument("--port", type=int, required=True, help="HTTP API port")
    parser.add_argument("--config", required=True, help="Path to agent config.json")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Setup logging from config (replaces the old logger.disable approach)
    from agent.config.loader import load_config as _load_cfg
    from agent.utils.logging_config import setup_logging
    try:
        cfg = _load_cfg(Path(args.config))
        setup_logging(cfg.logging, verbose=args.verbose)
    except Exception:
        # Fallback: basic logging if config load fails
        setup_logging(verbose=args.verbose)

    asyncio.run(_run(args.agent_id, args.port, Path(args.config)))


if __name__ == "__main__":
    main()
