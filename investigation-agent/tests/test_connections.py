"""Composio connection contracts, without external calls or real credentials."""

import json
import os
import unittest
from unittest.mock import patch

import httpx

from skill_improve_cycle.common.integrations.composio import composio_client


class ComposioConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_exposes_only_the_connected_application(self):
        requests = []

        def respond(request):
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(200, json={
                    "status": "ACTIVE", "toolkit": {"slug": "gmail"}, "user_id": "test-user",
                })
            return httpx.Response(200, json={"mcp": {"url": "https://mcp.composio.dev/test-session"}})

        async_client = httpx.AsyncClient
        with patch.dict(os.environ, {
            "COMPOSIO_API_KEY": "test-key", "COMPOSIO_GMAIL_CONNECTED_ACCOUNT_ID": "test-account",
        }), patch("skill_improve_cycle.common.integrations.composio.httpx.AsyncClient",
                  side_effect=lambda **kwargs: async_client(transport=httpx.MockTransport(respond), **kwargs)):
            await composio_client("gmail")

        self.assertEqual([(r.method, r.url.path) for r in requests], [
            ("GET", "/api/v3.1/connected_accounts/test-account"),
            ("POST", "/api/v3.1/tool_router/session"),
        ])
        session = json.loads(requests[1].content)
        self.assertEqual(session["connected_accounts"], {"gmail": ["test-account"]})
        self.assertEqual(session["toolkits"], {"enable": ["gmail"]})
        self.assertEqual(session["preload"], {"tools": "all"})
        self.assertFalse(session["manage_connections"]["enable"])

    async def test_mismatched_account_cannot_create_a_session(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={
                "status": "ACTIVE", "toolkit": {"slug": "notion"}, "user_id": "test-user",
            })

        async_client = httpx.AsyncClient
        with patch.dict(os.environ, {
            "COMPOSIO_API_KEY": "test-key", "COMPOSIO_GMAIL_CONNECTED_ACCOUNT_ID": "test-account",
        }), patch("skill_improve_cycle.common.integrations.composio.httpx.AsyncClient",
                  side_effect=lambda **kwargs: async_client(transport=httpx.MockTransport(respond), **kwargs)):
            with self.assertRaises(ValueError):
                await composio_client("gmail")
        self.assertEqual([r.method for r in requests], ["GET"])
