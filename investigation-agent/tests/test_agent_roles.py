"""Offline wiring checks: real MCP discovery, skill loading and Monty, fake model."""

import json

import pytest
from fastmcp import Client, FastMCP
from pydantic_ai.capabilities import Capability
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from skill_improve_cycle.investigator.agent import build_agent
from skill_improve_cycle.investigator.cli import parse_args
from skill_improve_cycle.improver.agent import build_improver
from skill_improve_cycle.investigator.runner import model_configuration
from skill_improve_cycle.improver.runner import model_configuration as improver_configuration
from skill_improve_cycle.improver.cli import parse_args as improver_args


@pytest.mark.parametrize("improve", [False, True])
async def test_roles_can_read_procedure_and_execute_native_tools(improve):
    server = FastMCP("role-check")
    observed = []

    @server.tool
    async def lookup_customer() -> dict:
        observed.append("lookup")
        return {"name": "Fixture Customer"}

    cap = Capability(id="fixture", toolsets=[
        MCPToolset(Client(server), id="fixture").prefixed("fixture").defer_loading(),
    ])
    step = 0

    def respond(messages, info):
        nonlocal step
        assert not any(isinstance(p, RetryPromptPart) for p in messages[-1].parts)
        assert ("Runtime compatibility" in info.instructions) is improve
        current = step
        step += 1
        if current == 0:
            assert not any(t.name == "fixture_lookup_customer" for t in info.function_tools)
            assert not any(t.name == "run_investigation_script" for t in info.function_tools)
            assert not any(t.name == "read_file" for t in info.function_tools)
            return ModelResponse(parts=[ToolCallPart("load_capability", {"id": "investigate-incident"})])
        if current == 1:
            loaded_context = str(messages) + (info.instructions or "")
            assert "# Run the saved investigation" in loaded_context
            return ModelResponse(parts=[ToolCallPart("run_code", {"code":
                "procedure = await read_file(path='investigate-incident/references/direct-procedure.md')\nprocedure"})])
        if current == 2:
            loaded_context = str(messages) + (info.instructions or "")
            assert "## Ordered procedure and completion" in loaded_context
            return ModelResponse(parts=[ToolCallPart("search_tools", {"queries": ["fixture_lookup_customer"]})])
        if current == 3:
            return ModelResponse(parts=[ToolCallPart("run_code", {"code":
                "customer = await fixture_lookup_customer()\ncustomer"})])
        results = [p.model_response_object() for p in messages[-1].parts if isinstance(p, ToolReturnPart)]
        assert "Fixture Customer" in json.dumps(results)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "customer": "Fixture Customer", "status": "unknown", "summary": "Offline tool wiring verified",
            "likely_cause": "No real investigation in this test", "evidence": [],
            "next_steps": [], "notion_page_url": None,
        })])

    model = FunctionModel(respond, profile={"supported_native_tools": frozenset()})
    capabilities = [cap]
    agent = (build_improver(model, capabilities) if improve else
             build_agent(model, capabilities))
    async with agent:
        result = await agent.run("Check the shared skill and fixture tool only.")
    assert observed == ["lookup"]
    assert len(capabilities) == 1
    assert result.output.customer == "Fixture Customer"
    assert agent.name == ("investigation-script-improver" if improve else "orders-investigator")


def test_commands_select_independent_models_and_deadlines(monkeypatch):
    monkeypatch.setenv("MODEL", "investigator-model")
    monkeypatch.setenv("REASONING_EFFORT", "medium")
    monkeypatch.setenv("IMPROVER_MODEL", "improver-model")
    monkeypatch.setenv("IMPROVER_REASONING_EFFORT", "high")
    _, normal = parse_args(argv=["--sender", "customer@example.com"])
    _, research = improver_args(argv=["--sender", "customer@example.com"])
    assert not hasattr(normal, "code_mode") and normal.timeout == 300
    assert not hasattr(research, "code_mode") and research.timeout == 600
    assert model_configuration() == ("investigator-model", "medium")
    assert improver_configuration() == ("improver-model", "high")
