"""Run a manual investigation with or without Code Mode."""

from skill_improve_cycle.common.command_support import common_parser, launch, validated_args
from skill_improve_cycle.investigator.runner import run


def parse_args(argv=None):
    parser = common_parser(__doc__, default_timeout=300)
    parser.add_argument("--code-mode", action="store_true", help="Use model-generated Python executed by Monty.")
    return validated_args(parser, argv)


def main():
    parser, args = parse_args()
    launch(run, parser, args,
           service_name="orders-investigation-agent", span_name="Investigate email incident",
           span_attributes={"code_mode": args.code_mode, "scenario": args.scenario})
