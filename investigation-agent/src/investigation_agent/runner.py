"""Connect MCPs, run one investigation and report comparable usage metrics."""

import asyncio
import json
import os
from datetime import UTC, datetime
from time import perf_counter

from pydantic_ai import AgentRunResultEvent
from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness.code_mode import RunCodeCallPart

from investigation_agent.agent import build_agent
from investigation_agent.capabilities.gmail import gmail_capability
from investigation_agent.capabilities.logfire import logfire_capability
from investigation_agent.capabilities.mongo import mongo_capability
from investigation_agent.capabilities.notion import notion_capability
from investigation_agent.integrations.composio import required
from investigation_agent.models import InvestigationRequest


async def investigate(args):
    started = perf_counter()
    required("OPENAI_API_KEY")
    request = InvestigationRequest(
        gmail_sender=args.sender,
        mailbox=required("GMAIL_ACCOUNT_EMAIL"),
        scenario=args.scenario,
        mongo_database=os.getenv("MONGODB_DATABASE", "skill_orders_demo"),
        logfire_project=required("LOGFIRE_PROJECT"),
        notion_database_name=os.getenv("NOTION_DATABASE_NAME", "Incidents"),
        now_utc=datetime.now(UTC),
    )
    # Only connection setup happens here. Email selection and all investigation
    # decisions belong to the skill and execute through the agent's MCP tools.
    mongo, logfire = mongo_capability(), logfire_capability()
    gmail, notion = await asyncio.gather(gmail_capability(), notion_capability())
    model = os.getenv("MODEL", "openai:gpt-6-luna")
    agent = build_agent(model, [mongo, logfire, gmail, notion], code_mode=args.code_mode)
    code_blocks = retries = 0
    agent_started = perf_counter()
    async with agent:
        async with agent.run_stream_events(
            request.model_dump_json(),
            model_settings={"openai_reasoning_effort": "medium", "timeout": args.timeout},
            usage_limits=UsageLimits(request_limit=40, tool_calls_limit=120, output_tokens_limit=32000),
        ) as events:
            async for event in events:
                if isinstance(event, FunctionToolCallEvent):
                    print(f"→ {event.part.tool_name}", flush=True)
                    if isinstance(event.part, RunCodeCallPart):
                        code_blocks += 1
                        print(event.part.code, flush=True)
                elif isinstance(event, FunctionToolResultEvent):
                    print(f"← {event.part.tool_name}: {event.part.outcome}", flush=True)
                    if event.part.outcome == "retried":
                        retries += 1
                elif isinstance(event, AgentRunResultEvent):
                    result = event.result
                    print(result.output.model_dump_json(indent=2))
                    print(json.dumps({
                        "code_mode": args.code_mode,
                        "model": model,
                        "model_requests": result.usage.requests,
                        "input_tokens": result.usage.input_tokens,
                        "output_tokens": result.usage.output_tokens,
                        "code_blocks": code_blocks,
                        "tool_retries": retries,
                        "agent_seconds": round(perf_counter() - agent_started, 2),
                        "total_seconds": round(perf_counter() - started, 2),
                    }, indent=2))
                    return result.output


async def run(args):
    async with asyncio.timeout(args.timeout):
        return await investigate(args)
