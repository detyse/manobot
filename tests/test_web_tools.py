"""Tests for web tool edge cases added on this branch."""

from __future__ import annotations

import json
import socket
from unittest.mock import patch

import httpx
import pytest

from agent.agent.tools.web import WebFetchTool, WebSearchTool
from agent.config.schema import WebSearchConfig


def _tool(provider: str = "brave", api_key: str = "", base_url: str = "") -> WebSearchTool:
    return WebSearchTool(config=WebSearchConfig(provider=provider, api_key=api_key, base_url=base_url))


def _response(status: int = 200, json_data: dict | None = None) -> httpx.Response:
    response = httpx.Response(status, json=json_data)
    response._request = httpx.Request("GET", "https://mock")
    return response


def _fake_resolve_public(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


@pytest.mark.asyncio
async def test_jina_search_uses_path_encoded_query(monkeypatch):
    calls = {}

    async def mock_get(self, url, **kwargs):
        calls["url"] = str(url)
        calls["params"] = kwargs.get("params")
        return _response(
            json_data={
                "data": [
                    {
                        "title": "Jina Result",
                        "url": "https://jina.ai",
                        "content": "AI search",
                    }
                ]
            }
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="jina", api_key="jina-key")

    await tool.execute(query="hello world")

    assert calls["url"].rstrip("/") == "https://s.jina.ai/hello%20world"
    assert calls["params"] in (None, {})


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_redirect_before_returning_image(monkeypatch):
    tool = WebFetchTool()

    class FakeStreamResponse:
        headers = {"content-type": "image/png"}
        url = "http://127.0.0.1/secret.png"
        content = b"\x89PNG\r\n\x1a\n"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aread(self):
            return self.content

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None):
            return FakeStreamResponse()

    monkeypatch.setattr("agent.agent.tools.web.httpx.AsyncClient", FakeClient)

    with patch("agent.security.network.socket.getaddrinfo", _fake_resolve_public):
        result = await tool.execute(url="https://example.com/image.png")

    data = json.loads(result)
    assert "error" in data
    assert "redirect blocked" in data["error"].lower()
