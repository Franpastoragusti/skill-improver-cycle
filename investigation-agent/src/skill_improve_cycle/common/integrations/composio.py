"""Create a Composio MCP session for one connected application."""

import os
from urllib.parse import quote, urlsplit

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

API = "https://backend.composio.dev/api/v3.1"


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} in investigation-agent/.env.")
    return value


async def composio_client(toolkit):
    account_id = required(f"COMPOSIO_{toolkit.upper()}_CONNECTED_ACCOUNT_ID")
    headers = {"x-api-key": required("COMPOSIO_API_KEY")}
    async with httpx.AsyncClient(base_url=API, headers=headers, timeout=30) as http:
        response = await http.get("/connected_accounts/" + quote(account_id, safe=""))
        if response.is_error:
            raise ValueError(f"Composio connection lookup failed (HTTP {response.status_code}). Check the API key and account ID.")
        account = response.json()
        if account.get("status") != "ACTIVE":
            raise ValueError("Complete authorization for the connected account in Composio.")
        if account.get("toolkit", {}).get("slug") != toolkit or not account.get("user_id"):
            raise ValueError("The connected account does not match the requested application.")
        response = await http.post("/tool_router/session", json={
            "user_id": account["user_id"],
            "connected_accounts": {toolkit: [account_id]},
            "toolkits": {"enable": [toolkit]},
            "preload": {"tools": "all"},
            "manage_connections": {"enable": False},
            "workbench": {"enable": False, "enable_proxy_execution": False},
            "proxy_execute": {"enable": False},
            "instant": False,
            "search": {"enable": False},
            "execute": {"enable_multi_execute": False},
        })
        if response.is_error:
            raise ValueError(f"Composio session creation failed (HTTP {response.status_code}). Check session permissions on the API key.")
        url = response.json()["mcp"]["url"]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".composio.dev"):
        raise ValueError("Composio returned an unexpected MCP address.")
    return Client(StreamableHttpTransport(url, headers=headers), mode="legacy", timeout=60)
