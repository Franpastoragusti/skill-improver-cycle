"""Inspect and manage skill revisions and recorded failures. No external calls."""

import argparse
import sys

from skill_improve_cycle.common import registry
from skill_improve_cycle.common.checks import check_program
from skill_improve_cycle.common.failures import list_failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List revisions")
    commands.add_parser("failures", help="List recorded failures of the saved program")
    for name, text in (("diff", "Show the diff of a revision against its base"),
                       ("check", "Run the static checks on a revision"),
                       ("activate", "Activate a checked and verified candidate")):
        commands.add_parser(name, help=text).add_argument("revision")
    commands.add_parser("rollback", help="Return to the revision that the active one replaced")
    args = parser.parse_args(argv)
    try:
        print(run(args))
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")


def run(args):
    if args.command == "list":
        active = registry.active_revision()
        lines = []
        for revision in registry.list_revisions():
            meta = registry.read_meta(revision)
            mark = "*" if revision == active else " "
            lines.append(f"{mark} {revision:<4} {meta.get('status', '?'):<12} base={meta.get('base_revision') or '-':<4} "
                         f"{(meta.get('reason') or '')[:90]}")
        return "\n".join(lines)
    if args.command == "failures":
        rows = [f"{f['id']}  {f['classification']:<12} {f['status']:<18} rev={f['revision']} "
                f"candidate={f.get('candidate') or '-'}  {f['error'][:80]!r}" for f in list_failures()]
        return "\n".join(rows) or "No recorded failures."
    if args.command == "diff":
        return registry.diff(args.revision) or "No differences."
    if args.command == "check":
        problems = check_program(registry.read_script(args.revision))
        if problems:
            print("\n".join(problems), file=sys.stderr)
            raise ValueError(f"{args.revision} failed the static checks.")
        return f"{args.revision} passed the static checks."
    if args.command == "activate":
        problems = check_program(registry.read_script(args.revision))
        if problems:
            raise ValueError(f"{args.revision} failed the static checks: " + "; ".join(problems))
        previous = registry.activate(args.revision)
        return f"{args.revision} is now active (replaced {previous}). Undo with `make skill-rollback`."
    current, previous = registry.rollback()
    return f"Rolled back {current}; {previous} is active again."
