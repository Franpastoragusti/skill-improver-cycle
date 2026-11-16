"""Shared skill and MCP toolset composition, independent of either agent."""

from importlib.resources import files

from pydantic_ai.capabilities import ToolSearch
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import CodeMode, Skills


def build_capabilities(capabilities, *, code_mode):
    """Compose the same skill and tool catalogs for either agent."""
    result = [
        *capabilities,
        Skills("skills", include=["investigate-incident"],
               workspace=LocalWorkspaceBackend(str(files("skill_improve_cycle.common")))),
        ToolSearch(strategy="keywords", max_results=5),
    ]
    if code_mode:
        result.append(CodeMode(
            max_tool_calls=40,
            resource_limits={"max_memory": 64 * 1024 * 1024},
        ))
    return result
