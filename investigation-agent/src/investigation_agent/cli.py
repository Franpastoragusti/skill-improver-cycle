"""Run a manual investigation with or without Code Mode."""

import argparse
import asyncio
import math

import logfire
from pydantic_ai.exceptions import UsageLimitExceeded

from investigation_agent.integrations.composio import required
from investigation_agent.runner import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sender", required=True, help="Select the latest inbox message from this sender.")
    parser.add_argument("--scenario", default="demo")
    parser.add_argument("--code-mode", action="store_true", help="Use model-generated Python executed by Monty.")
    parser.add_argument("--timeout", type=float, default=300, help="Whole-run deadline in seconds.")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a positive finite number.")
    try:
        token = required("LOGFIRE_TOKEN")
    except ValueError as exc:
        parser.error(str(exc))
    logfire.configure(token=token, service_name="orders-investigation-agent",
                      service_version="0.2.0", environment="demo", console=False, metrics=False)
    logfire.instrument_pydantic_ai(include_content=True)
    try:
        with logfire.span("Investigate email incident", code_mode=args.code_mode, scenario=args.scenario):
            asyncio.run(run(args))
    except TimeoutError:
        parser.exit(2, "Investigation exceeded its time limit. Check Notion before retrying; writes may have completed.\n")
    except (ValueError, UsageLimitExceeded) as exc:
        parser.exit(2, f"{exc}\n")
    finally:
        logfire.force_flush()
