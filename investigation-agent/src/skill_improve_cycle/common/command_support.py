"""Shared CLI argument primitives, telemetry setup and error presentation."""

import argparse
import asyncio
import math

import logfire
from pydantic_ai.exceptions import UsageLimitExceeded

from skill_improve_cycle.common.integrations.composio import required


def common_parser(description, *, default_timeout):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--sender", required=True, help="Select the latest inbox message from this sender.")
    parser.add_argument("--scenario", default="demo")
    parser.add_argument("--timeout", type=float, default=default_timeout, help="Whole-run deadline in seconds.")
    return parser


def validated_args(parser, argv):
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a positive finite number.")
    return parser, args


def launch(runner, parser, args, *, service_name, span_name, span_attributes):
    try:
        token = required("LOGFIRE_TOKEN")
    except ValueError as exc:
        parser.error(str(exc))
    logfire.configure(token=token, service_name=service_name,
                      service_version="0.2.0", environment="demo", console=False, metrics=False)
    logfire.instrument_pydantic_ai(include_content=True)
    try:
        with logfire.span(span_name, **span_attributes):
            asyncio.run(runner(args))
    except TimeoutError:
        parser.exit(2, "Execution exceeded its time limit. Check Notion before retrying; writes may have completed.\n")
    except (ValueError, UsageLimitExceeded) as exc:
        parser.exit(2, f"{exc}\n")
    finally:
        logfire.force_flush()
