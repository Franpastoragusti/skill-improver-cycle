"""Connect the native Mongo MCP catalog with deferred tool loading."""

import os

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic_ai.capabilities import Capability
from pydantic_ai.mcp import MCPToolset

from investigation_agent.paths import PROJECT_ROOT

ROOT = PROJECT_ROOT


def mongo_client(*, read_only=True) -> Client:
    script = ROOT / "mcp/mongodb/node_modules/mongodb-mcp-server/dist/esm/index.js"
    if not script.is_file():
        raise ValueError("Install the Mongo MCP server with npm ci --prefix mcp/mongodb --ignore-scripts from investigation-agent.")
    logs = ROOT / ".local"
    logs.mkdir(exist_ok=True)
    return Client(
        StdioTransport(
            command="node",
            args=[str(script), *(["--readOnly"] if read_only else [])],
            env={
                "MDB_MCP_CONNECTION_STRING": os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27029"),
                "MDB_MCP_TELEMETRY": "disabled",
                "MDB_MCP_LOGGERS": "stderr",
                "MDB_MCP_MAX_DOCUMENTS_PER_QUERY": "100",
            },
            log_file=logs / "mongo-mcp.log",
        ),
        mode="legacy",
        timeout=30,
    )


def mongo_capability(*, client=None, read_only=True) -> Capability:
    toolset = MCPToolset(
        client if client is not None else mongo_client(read_only=read_only), id="mongodb",
    ).prefixed("mongo").defer_loading()
    return Capability(id="mongodb", toolsets=[toolset])
