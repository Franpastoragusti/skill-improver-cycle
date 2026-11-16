"""Run the investigator with its own model and execution budget."""

import asyncio
import os
import sys

from opentelemetry import trace

from pydantic_ai.usage import UsageLimits

from skill_improve_cycle.investigator.agent import build_agent
from skill_improve_cycle.common.failures import find_script_failure, record_failure
from skill_improve_cycle.common.registry import active_revision, revision_dir
from skill_improve_cycle.common.runtime import build_request, connect_capabilities


def model_configuration():
    return (os.getenv("MODEL", "openai:gpt-6-luna"),
            os.getenv("REASONING_EFFORT", "low"))


async def run(args):
    async with asyncio.timeout(args.timeout):
        request = build_request(args.sender, args.scenario)
        capabilities = await connect_capabilities()
        model, reasoning = model_configuration()
        revision = active_revision()
        trace.get_current_span().set_attribute("skill_revision", revision)
        agent = build_agent(model, capabilities, revision_dir(revision))
        async with agent:
            result = await agent.run(
                request.model_dump_json(),
                model_settings={"openai_reasoning_effort": reasoning, "timeout": args.timeout},
                usage_limits=UsageLimits(request_limit=60, tool_calls_limit=120, output_tokens_limit=None),
            )
            queue_script_failure(result, revision, request)
            return result.output


def queue_script_failure(result, revision, request):
    """Queue a failure of the saved program; the run itself is already finished."""
    failure = find_script_failure(result.all_messages())
    if failure is None:
        return None
    record = record_failure(failure, revision=revision, request=request,
                            recovered=result.output.notion_page_url is not None)
    print(f"The saved program ({revision}) failed: {record['classification']} failure {record['id']} recorded. "
          f"Inspect it with `make failures`.", file=sys.stderr)
    return record
