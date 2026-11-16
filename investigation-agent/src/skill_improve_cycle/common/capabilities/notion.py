"""Connect the full Notion MCP toolset; the selected skill owns the procedure."""

from pydantic_ai.capabilities import Capability
from pydantic_ai.mcp import MCPToolset

from skill_improve_cycle.common.integrations.composio import composio_client


async def notion_capability(*, client=None) -> Capability:
    client = client if client is not None else await composio_client("notion")
    toolset = MCPToolset(client, id="notion").prefixed("notion").defer_loading()
    return Capability(id="notion", toolsets=[toolset])
