"""Run the investigator with its own model and execution budget."""

import asyncio
import os

from pydantic_ai.usage import UsageLimits

from skill_improve_cycle.investigator.agent import build_agent
from skill_improve_cycle.common.runtime import build_request, connect_capabilities


def model_configuration():
    return (os.getenv("MODEL", "openai:gpt-6-luna"),
            os.getenv("REASONING_EFFORT", "high"))


async def run(args):
    async with asyncio.timeout(args.timeout):
        request = build_request(args.sender, args.scenario)
        capabilities = await connect_capabilities()
        model, reasoning = model_configuration()
        agent = build_agent(model, capabilities, code_mode=args.code_mode)
        async with agent:
            result = await agent.run(
                request.model_dump_json(),
                model_settings={"openai_reasoning_effort": reasoning, "timeout": args.timeout},
                usage_limits=UsageLimits(request_limit=60, tool_calls_limit=120, output_tokens_limit=None),
            )
            return result.output
