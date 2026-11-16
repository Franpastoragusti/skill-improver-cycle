"""Offline checks of the improvement cycle: failure detection, classification,
static checks, candidate creation, activation and rollback. No model or external service."""

import shutil
from types import SimpleNamespace

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from skill_improve_cycle.common import registry
from skill_improve_cycle.common.checks import check_program
from skill_improve_cycle.common.failures import classify, find_script_failure, list_failures, record_failure
from skill_improve_cycle.common.models import InvestigationRequest
from skill_improve_cycle.improver.repair import MARKER, store_candidate
from skill_improve_cycle.investigator.agent import build_agent

INVOCATION = ('exec(Path("/skills/investigate-incident/scripts/investigate.py").read_text())\n'
              "result = await run_investigation(params)\nresult")
REQUEST = InvestigationRequest(
    gmail_sender="customer@example.com", mailbox="inbox@example.com", scenario="demo",
    mongo_database="db", logfire_project="project", notion_database_name="Incidents",
    now_utc="2030-01-01T00:00:00Z")


def run_messages(code, returned):
    return [ModelResponse(parts=[ToolCallPart("run_code", {"code": code}, tool_call_id="c1")]),
            ModelRequest(parts=[returned])]


@pytest.fixture
def root(tmp_path):
    """A private registry that starts with the repository's first revision."""
    source = registry.registry_root() / "revisions" / "r1"
    shutil.copytree(source, tmp_path / "revisions" / "r1")
    (tmp_path / "active").write_text("r1\n")
    return tmp_path


def test_first_revision_passes_the_static_checks():
    assert check_program(registry.read_script("r1")) == []


@pytest.mark.parametrize("source, expected", [
    ("async def run_investigation(params):\n    yield 1\n", "yield"),
    ("async def run_investigation(params):\n    return getattr(params, 'x')\n", "getattr"),
    ("async def run_investigation(params):\n    import os\n", "import of `os`"),
    ("async def run_investigation(params):\n    return await notion_NOTION_DELETE_BLOCK(block_id='x')\n", "allowed tools"),
    ("async def run_investigation(params):\n    return 1\nresult = 1\n", "top-level statement"),
    ("async def other(params):\n    return 1\n", "exactly one"),
    ("async def run_investigation(params:\n", "Syntax error"),
])
def test_static_checks_reject_unsafe_or_unsupported_programs(source, expected):
    assert any(expected in problem for problem in check_program(source))


def test_static_checks_allow_local_helpers_named_like_tools():
    source = ("async def run_investigation(params):\n"
              "    async def mongo_all(collection):\n        return await mongo_find(collection=collection)\n"
              "    return await mongo_all('orders')\n")
    assert check_program(source) == []


@pytest.mark.parametrize("error, expected", [
    ("Type error in code: Expected `MongoFindFilter | None`, found `dict`", "contract"),
    ("NotImplementedError: The monty syntax parser does not yet support yield expressions", "contract"),
    ("Unexpected Notion incident query response: {}", "contract"),
    ("Request timed out after 30 seconds", "transient"),
    ("Application failure: 503 Service Unavailable", "transient"),
    ("Expected exactly one Mongo customer matching observed sender and scenario; found 2", "needs_human"),
    ("Duplicate active incidents for selected Gmail message", "needs_human"),
    ("something nobody anticipated", "needs_human"),
])
def test_classification_separates_noise_business_cases_and_contract_failures(error, expected):
    assert classify(error) == expected


def test_failure_detection_reads_only_saved_program_calls():
    blocked = {"verification": {"complete": False}, "blocker": "Unexpected Gmail list response"}
    done = {"verification": {"complete": True}, "blocker": None}
    assert find_script_failure(run_messages(INVOCATION, ToolReturnPart("run_code", blocked, "c1"))) == {
        "kind": "incomplete", "error": "Unexpected Gmail list response"}
    assert find_script_failure(run_messages(INVOCATION, ToolReturnPart("run_code", done, "c1"))) is None
    assert find_script_failure(run_messages(INVOCATION, ToolReturnPart("run_code", "Runtime error: boom", "c1"))) == {
        "kind": "script_error", "error": "Runtime error: boom"}
    assert find_script_failure(run_messages(INVOCATION, RetryPromptPart("Type error in code", tool_name="run_code",
                                                                        tool_call_id="c1")))["kind"] == "script_error"
    # A failing program that the model wrote itself (recovery, exploration) is not a saved-program failure.
    assert find_script_failure(run_messages("x = 1\nx", ToolReturnPart("run_code", "Runtime error", "c1"))) is None


async def test_saved_program_failure_is_detected_and_queued(root):
    """The real r1 program runs in Monty without its tools, fails and is queued."""
    step = 0

    def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            return ModelResponse(parts=[ToolCallPart("run_code", {"code":
                "from pathlib import Path\nfrom typing import Any\nparams = {}\n"
                "run_investigation: Any = None\n" + INVOCATION})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "customer": None, "status": "unknown", "summary": "s", "likely_cause": "c",
            "evidence": [], "next_steps": [], "notion_page_url": None})])

    agent = build_agent(FunctionModel(respond, profile={"supported_native_tools": frozenset()}), [],
                        registry.revision_dir("r1", root))
    async with agent:
        result = await agent.run("x")
    failure = find_script_failure(result.all_messages())
    assert failure["kind"] == "incomplete" and "Unknown function" in failure["error"]

    record = record_failure(failure, revision="r1", request=REQUEST, recovered=False, root=root)
    assert record["classification"] == "contract" and record["status"] == "open"
    assert [f["id"] for f in list_failures(root)] == [record["id"]]


def repair_result(program, complete=True):
    messages = run_messages(f"{program}\n{MARKER}\nparams = {{}}\nresult = await run_investigation(params)\nresult",
                            ToolReturnPart("run_code", {"verification": {"complete": complete},
                                                        "notion_page_url": "https://notion.example/p"}, "c1"))
    return SimpleNamespace(all_messages=lambda: messages,
                           output=SimpleNamespace(root_cause="Cause.", change_summary="Fix."))


def test_candidate_is_the_tested_program_and_needs_explicit_activation(root):
    failure = record_failure({"kind": "incomplete", "error": "Unexpected Gmail list response"},
                             revision="r1", request=REQUEST, recovered=True, root=root)
    program = registry.read_script("r1", root).replace("Investigation not completed.", "Investigation incomplete.")

    message = store_candidate(repair_result(program), failure, "r1", root)
    assert "Candidate r2 created from r1 (static checks passed)" in message
    assert registry.read_script("r2", root) == program
    assert registry.active_revision(root) == "r1"
    assert registry.read_meta("r2", root)["failure_id"] == failure["id"]
    assert "-" in registry.diff("r2", root=root) and "Investigation incomplete." in registry.diff("r2", root=root)
    assert list_failures(root)[0]["candidate"] == "r2"

    assert registry.activate("r2", root) == "r1"
    assert registry.active_revision(root) == "r2"
    assert registry.read_meta("r1", root)["status"] == "superseded"
    assert registry.rollback(root) == ("r2", "r1")
    assert registry.active_revision(root) == "r1"
    assert registry.read_meta("r2", root)["status"] == "rolled_back"
    with pytest.raises(registry.RegistryError):
        registry.activate("r2", root)


def test_unverified_or_unchanged_repairs_create_no_candidate(root):
    failure = record_failure({"kind": "incomplete", "error": "Unexpected"}, revision="r1",
                             request=REQUEST, recovered=True, root=root)
    program = registry.read_script("r1", root)
    assert "No candidate" in store_candidate(repair_result(program + "# changed", complete=False), failure, "r1", root)
    assert "No candidate" in store_candidate(repair_result(program.rstrip()), failure, "r1", root)
    assert registry.list_revisions(root) == ["r1"]


def test_candidate_that_fails_static_checks_cannot_be_activated(root):
    failure = record_failure({"kind": "incomplete", "error": "Unexpected"}, revision="r1",
                             request=REQUEST, recovered=True, root=root)
    program = registry.read_script("r1", root) + "\nleaked = 1\n"
    assert "static checks FAILED" in store_candidate(repair_result(program), failure, "r1", root)
    with pytest.raises(registry.RegistryError, match="static checks"):
        registry.activate("r2", root)
    assert registry.active_revision(root) == "r1"
