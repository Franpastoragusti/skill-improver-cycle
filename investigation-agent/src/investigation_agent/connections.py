"""Check MCP connectivity by listing tools; never execute application tools."""

import argparse
import asyncio
import os
import sys

from fastmcp import Client

from investigation_agent.capabilities.logfire import LOGFIRE_URL
from investigation_agent.capabilities.mongo import mongo_client
from investigation_agent.integrations.composio import composio_client, required


async def check(service):
    if service == "mongo":
        client = mongo_client()
    elif service == "logfire":
        client = Client(os.getenv("LOGFIRE_MCP_URL", LOGFIRE_URL),
                        auth=required("LOGFIRE_API_KEY"), timeout=30)
    else:
        client = await composio_client(service)
    async with client:
        tools = await client.list_tools()
    print(f"{service}: connected; {len(tools)} MCP tools available. No application tools executed.")


async def check_services(services):
    succeeded = True
    for service in services:
        try:
            await check(service)
        except Exception as exc:
            succeeded = False
            print(f"{service}: connection check failed ({type(exc).__name__}). "
                  "Check configuration, authorization and service availability.", file=sys.stderr)
    return succeeded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    services = ["logfire", "gmail", "notion", "mongo"]
    parser.add_argument("service", nargs="?", default="all", choices=["all", *services])
    args = parser.parse_args()
    selected = services if args.service == "all" else [args.service]
    raise SystemExit(0 if asyncio.run(check_services(selected)) else 1)
