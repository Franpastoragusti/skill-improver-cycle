"""Generate and test an investigation program with Code Mode and real MCP tools."""

from skill_improve_cycle.common.command_support import common_parser, launch, validated_args
from skill_improve_cycle.improver.runner import run


def parse_args(argv=None):
    return validated_args(common_parser(__doc__, default_timeout=600), argv)


def main():
    parser, args = parse_args()
    launch(run, parser, args,
           service_name="investigation-script-improver", span_name="Improve investigation script",
           span_attributes={"code_mode": True, "scenario": args.scenario})
