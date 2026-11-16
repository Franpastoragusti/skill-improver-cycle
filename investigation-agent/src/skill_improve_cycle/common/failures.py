"""Detect a failure of the saved program in a run, classify it and queue it."""

import json
import re
from datetime import UTC, datetime

from opentelemetry import trace
from pydantic_ai.messages import RetryPromptPart, ToolCallPart, ToolReturnPart

from skill_improve_cycle.common.registry import registry_root

SCRIPT_MARK = "scripts/investigate.py"

# Order matters: a transient failure is noise; a business condition belongs to a
# person; only runtime and tool-contract failures go to the improver.
_TRANSIENT = re.compile(
    r"timeout|timed out|rate.?limit|\b429\b|\b50[0234]\b|temporar|unavailable|connection (reset|refused|error)|overloaded",
    re.IGNORECASE)
_BUSINESS = re.compile(
    r"expected exactly one mongo customer|ambiguous|duplicate active incidents|does not match requested mailbox"
    r"|identity mismatch|identity/readback mismatch|no historical sync attempts|no longer in inbox"
    r"|expected exactly one active exact-name notion database",
    re.IGNORECASE)
_CONTRACT = re.compile(
    r"type error|syntax error|runtime error|unexpected|schema|missing|unknown function|not supported|unsupported"
    r"|notimplementederror|typeerror|keyerror|attributeerror|nameerror|invalid-|application failure|tool error"
    r"|exceeds|too many|repeated",
    re.IGNORECASE)


def classify(error):
    """Return `transient`, `needs_human` or `contract` for an error text."""
    if _TRANSIENT.search(error):
        return "transient"
    if _BUSINESS.search(error):
        return "needs_human"
    if _CONTRACT.search(error):
        return "contract"
    return "needs_human"


def find_script_failure(messages):
    """Return the first failure of the saved program in a run, or None."""
    script_calls = set()
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_name == "run_code":
                if SCRIPT_MARK in str(part.args_as_dict().get("code", "")):
                    script_calls.add(part.tool_call_id)
            elif isinstance(part, RetryPromptPart) and part.tool_call_id in script_calls:
                return {"kind": "script_error", "error": _text(part.content)}
            elif isinstance(part, ToolReturnPart) and part.tool_call_id in script_calls:
                content = part.content
                if isinstance(content, dict) and isinstance(content.get("verification"), dict):
                    if content["verification"].get("complete") is True:
                        continue
                    return {"kind": "incomplete",
                            "error": _text(content.get("blocker") or "Verification incomplete without a blocker")}
                return {"kind": "script_error", "error": _text(content)}
    return None


def _text(value):
    return (value if isinstance(value, str) else json.dumps(value, default=str))[:4000]


def current_trace_id():
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None


def record_failure(failure, *, revision, request, recovered, root=None):
    """Store a failure in the queue and return its record."""
    now = datetime.now(UTC)
    record = {
        "id": now.strftime("f%Y%m%d-%H%M%S"),
        "created_at": now.isoformat(),
        "status": "open",
        "revision": revision,
        "kind": failure["kind"],
        "error": failure["error"],
        "classification": classify(failure["error"]),
        "trace_id": current_trace_id(),
        "recovered_with_markdown": recovered,
        "request": {"sender": request.gmail_sender, "scenario": request.scenario},
        "candidate": None,
    }
    save_failure(record, root)
    return record


def _directory(root=None):
    return registry_root(root) / "failures"


def save_failure(record, root=None):
    _directory(root).mkdir(parents=True, exist_ok=True)
    (_directory(root) / f"{record['id']}.json").write_text(json.dumps(record, indent=2) + "\n")


def load_failure(failure_id, root=None):
    if not re.fullmatch(r"f\d{8}-\d{6}", failure_id or ""):
        raise ValueError(f"Invalid failure ID: {failure_id!r}")
    path = _directory(root) / f"{failure_id}.json"
    if not path.is_file():
        raise ValueError(f"Failure {failure_id} does not exist")
    return json.loads(path.read_text())


def list_failures(root=None):
    directory = _directory(root)
    return [json.loads(p.read_text()) for p in sorted(directory.glob("f*.json"))] if directory.is_dir() else []
