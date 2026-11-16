"""Shared preparation of investigation inputs and MCP capabilities."""

import os
from datetime import UTC, datetime

from skill_improve_cycle.common.capabilities.gmail import gmail_capability
from skill_improve_cycle.common.capabilities.logfire import logfire_capability
from skill_improve_cycle.common.capabilities.mongo import mongo_capability
from skill_improve_cycle.common.capabilities.notion import notion_capability
from skill_improve_cycle.common.integrations.composio import required
from skill_improve_cycle.common.models import InvestigationRequest


def build_request(sender, scenario):
    required("OPENAI_API_KEY")
    request = InvestigationRequest(
        gmail_sender=sender,
        mailbox=required("GMAIL_ACCOUNT_EMAIL"),
        scenario=scenario,
        mongo_database=os.getenv("MONGODB_DATABASE", "skill_orders_demo"),
        logfire_project=required("LOGFIRE_PROJECT"),
        notion_database_name=os.getenv("NOTION_DATABASE_NAME", "Incidents"),
        now_utc=datetime.now(UTC),
    )
    return request


async def connect_capabilities():
    mongo= mongo_capability()
    logfire= logfire_capability()
    gmail = await gmail_capability()
    notion = await notion_capability()
    return [mongo, logfire, gmail, notion]
