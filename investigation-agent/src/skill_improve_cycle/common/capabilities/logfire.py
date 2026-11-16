"""Connect the full Logfire MCP catalog with deferred tool loading."""

import os

from fastmcp import Client
from pydantic_ai.capabilities import Capability
from pydantic_ai.mcp import MCPToolset

LOGFIRE_URL = "https://logfire-eu.pydantic.dev/mcp"


def logfire_capability(*, client=None) -> Capability:
    if client is None:
        key = os.getenv("LOGFIRE_API_KEY", "").strip()
        if not key:
            raise ValueError("Set LOGFIRE_API_KEY with project:read access in investigation-agent/.env.")
        client = Client(os.getenv("LOGFIRE_MCP_URL", LOGFIRE_URL), auth=key, timeout=30)

    toolset = MCPToolset(client, id="logfire").prefixed("logfire").defer_loading()
    return Capability(id="logfire", toolsets=[toolset])
