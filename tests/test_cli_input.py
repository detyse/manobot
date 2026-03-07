import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.formatted_text import HTML

from manobot.cli import main as cli_main


@pytest.fixture
def mock_prompt_session():
    """Mock the global prompt session."""
    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock()
    with patch.object(cli_main, "_PROMPT_SESSION", mock_session), \
         patch.object(cli_main, "patch_stdout"):
        yield mock_session


@pytest.mark.asyncio
async def test_read_interactive_input_async_returns_input(mock_prompt_session):
    """Test that _read_interactive_input_async returns the user input from prompt_session."""
    mock_prompt_session.prompt_async.return_value = "hello world"

    result = await cli_main._read_interactive_input_async()

    assert result == "hello world"
    mock_prompt_session.prompt_async.assert_called_once()
    args, _ = mock_prompt_session.prompt_async.call_args
    assert isinstance(args[0], HTML)  # Verify HTML prompt is used


@pytest.mark.asyncio
async def test_read_interactive_input_async_handles_eof(mock_prompt_session):
    """Test that EOFError converts to KeyboardInterrupt."""
    mock_prompt_session.prompt_async.side_effect = EOFError()

    with pytest.raises(KeyboardInterrupt):
        await cli_main._read_interactive_input_async()


def test_init_prompt_session_creates_session():
    """Test that _init_prompt_session initializes the global session."""
    # Ensure global is None before test
    cli_main._PROMPT_SESSION = None

    with patch.object(cli_main, "PromptSession") as MockSession, \
         patch.object(cli_main, "FileHistory") as MockHistory, \
         patch("pathlib.Path.home") as mock_home:

        mock_home.return_value = MagicMock()

        cli_main._init_prompt_session()

        assert cli_main._PROMPT_SESSION is not None
        MockSession.assert_called_once()
        _, kwargs = MockSession.call_args
        assert kwargs["multiline"] is False
        assert kwargs["enable_open_in_editor"] is False
