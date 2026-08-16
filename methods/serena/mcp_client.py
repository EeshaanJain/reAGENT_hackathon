"""A thin async wrapper around a live Serena MCP server.

`SerenaRepositoryAnalyzer` (harness.py) uses this to make real Model Context Protocol calls
against a target repository -- it is not a simulation, a mock, or a regex fallback. Each analysis
spawns (once, reused for the whole run) `serena start-mcp-server --transport stdio --project
<repo>` as a subprocess and talks the real MCP wire protocol to it via the `mcp` Python SDK,
exactly as any MCP client (this CLI included, when Serena is registered as an MCP server) would.

Requires the `serena-agent` package (provides the `serena` CLI) and `mcp` to be installed in the
active Python environment -- see methods/README.md "Setup" for the exact install command. If
`serena` isn't on PATH, or the handshake fails, calls raise SerenaUnavailableError; callers must
not fall back to grep/regex on that error (see harness.py's module docstring) -- that's the line
this package is not allowed to cross.

This client is deliberately async, not a sync-wrapper-per-call: the underlying MCP session opens
an anyio TaskGroup in `__aenter__` whose cancel scope is tied to the asyncio Task it was entered
in, and anyio raises if `__aexit__` (or any call in between) runs in a *different* Task -- which a
naive "new event loop, `run_until_complete()` once per call" wrapper does by construction (each
`run_until_complete()` wraps its coroutine in a fresh Task). Keeping the whole session lifetime --
connect, every tool call, disconnect -- inside one coroutine avoids that entirely.
"""

from __future__ import annotations

import json
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any


class SerenaUnavailableError(Exception):
    """Raised when the `serena` CLI is missing, the MCP handshake fails, or a tool call errors."""


class SerenaMCPClient:
    """One live async MCP session, rooted at `repo_path`, reused across an entire 8-stage analysis.

    Use as an async context manager:

        async with SerenaMCPClient(repo_path) as client:
            await client.call("get_symbols_overview", relative_path="pkg/__init__.py")
    """

    def __init__(self, repo_path: str | Path, *, context: str = "agent", tool_timeout_s: float = 120.0):
        self.repo_path = str(Path(repo_path).resolve())
        self.context = context
        self.tool_timeout_s = tool_timeout_s
        self._stack: AsyncExitStack | None = None
        self._session = None

    async def __aenter__(self) -> "SerenaMCPClient":
        if shutil.which("serena") is None:
            raise SerenaUnavailableError(
                "`serena` CLI not found on PATH -- pip install serena-agent (see methods/README.md, Setup)"
            )
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as e:
            raise SerenaUnavailableError(f"`mcp` package not importable: {e}") from e

        params = StdioServerParameters(
            command="serena",
            args=[
                "start-mcp-server",
                "--transport", "stdio",
                "--project", self.repo_path,
                "--context", self.context,
                "--enable-web-dashboard", "False",
                "--open-web-dashboard", "False",
                "--log-level", "ERROR",
            ],
        )
        self._stack = AsyncExitStack()
        try:
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
        except Exception as e:
            await self._stack.aclose()
            self._stack = None
            raise SerenaUnavailableError(f"failed to start/connect to Serena MCP server: {e}") from e
        return self

    async def call(self, tool_name: str, **kwargs: Any) -> Any:
        """Call a Serena MCP tool by name (e.g. "find_symbol", "get_symbols_overview") and return
        its parsed-JSON result (or raw text, if the tool didn't return JSON). Raises
        SerenaUnavailableError on any tool-level error -- callers decide whether that's fatal for
        the stage or just means "this particular query found nothing" (see harness.py stages,
        which mostly treat individual query failures as `unknown`, not aborts).
        """
        if self._session is None:
            raise SerenaUnavailableError("not connected -- use SerenaMCPClient as an async context manager")
        import asyncio

        result = await asyncio.wait_for(self._session.call_tool(tool_name, kwargs), timeout=self.tool_timeout_s)
        texts = [getattr(c, "text", None) for c in result.content if getattr(c, "text", None)]
        raw = "\n".join(t for t in texts if t)
        if getattr(result, "isError", False):
            raise SerenaUnavailableError(f"{tool_name}({kwargs}) failed: {raw}")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        self._session = None
