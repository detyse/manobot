"""Tests for cron tool timezone validation."""

import pytest

from nanobot.agent.tools.cron import CronTool
from nanobot.cron.service import CronService


@pytest.fixture
def cron_tool(tmp_path):
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path)
    tool = CronTool(service)
    tool.set_context("cli", "direct")
    return tool


@pytest.mark.asyncio
async def test_cron_add_rejects_invalid_timezone(cron_tool) -> None:
    result = await cron_tool.execute(
        action="add",
        message="hello",
        cron_expr="0 9 * * *",
        tz="America/Vancovuer",
    )
    assert "unknown timezone" in result
    assert "America/Vancovuer" in result
