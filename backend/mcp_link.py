"""The backend's own connection to the MCP server.

The API needs shop data too — the board, the balance, the approval queue — and
it reads them the same way the agents do, through MCP. There is deliberately
no second data layer here: `main.py` never opens the SQLite file, so the
tool-level rules (no negative balance, no payment without a human, no shipment
from a blocked vendor) cannot be sidestepped by calling the API instead of an
agent.

One long-lived stdio subprocess, opened at startup and closed at shutdown.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from .config import PROJECT_ROOT

MCP_COMMAND = ".venv/bin/python"
MCP_ARGS = ["mcp_server/server.py"]


class ToolRefused(RuntimeError):
    """An MCP tool declined to do something. The message is for the user.

    These are the shop's rules speaking — "a human must approve", "that would
    overdraw the account", "the vendor will not ship" — so the text is worth
    showing rather than swallowing behind a generic 500.
    """


class MCPLink:
    """A thin wrapper so routes can `await link.call("get_cash_balance")`."""

    def __init__(self) -> None:
        self._client: Client | None = None

    async def open(self) -> None:
        self._client = Client(
            StdioTransport(
                command=MCP_COMMAND, args=MCP_ARGS, cwd=str(PROJECT_ROOT)
            )
        )
        await self._client.__aenter__()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def call(self, tool: str, **arguments: Any) -> Any:
        """Call a tool and return its structured result.

        A tool that returns a list arrives wrapped as `{"result": [...]}`;
        that wrapper is unpacked here so routes see the list itself.
        """
        if self._client is None:
            raise RuntimeError("The MCP connection is not open.")
        try:
            result = await self._client.call_tool(tool, arguments)
        except Exception as exc:
            raise ToolRefused(str(exc)) from exc

        payload = result.structured_content
        if isinstance(payload, dict) and set(payload) == {"result"}:
            return payload["result"]
        return payload

    async def tool_names(self) -> list[str]:
        if self._client is None:
            return []
        return [t.name for t in await self._client.list_tools()]
