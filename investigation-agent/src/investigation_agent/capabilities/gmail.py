"""Connect the full Gmail MCP toolset; the selected skill owns the procedure."""

from pydantic_ai.capabilities import Capability
from pydantic_ai.mcp import MCPToolset

from investigation_agent.integrations.composio import composio_client


async def gmail_capability(*, client=None) -> Capability:
    client = client if client is not None else await composio_client("gmail")
    toolset = MCPToolset(client, id="gmail").prefixed("gmail").defer_loading()
    return Capability(id="gmail", toolsets=[toolset])
