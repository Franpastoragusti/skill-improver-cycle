"""One Markdown skill and native MCP capabilities, with optional Code Mode."""

from importlib.resources import files

from pydantic_ai import Agent
from pydantic_ai.capabilities import ToolSearch
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import CodeMode, Skills

from investigation_agent.models import Diagnosis


def build_agent(model, capabilities, *, code_mode=False):
    capabilities = [*capabilities,
        Skills("skills", include=["investigate-incident"],
               workspace=LocalWorkspaceBackend(str(files("investigation_agent")))),
        ToolSearch(strategy="keywords", max_results=5),
    ]
    if code_mode:
        capabilities.append(CodeMode(
            max_tool_calls=40,
            resource_limits={"max_memory": 64 * 1024 * 1024},
        ))
    return Agent(
        model,
        name="orders-investigator",
        instructions="Load the investigate-incident skill and follow it to complete the requested investigation. Write the final diagnosis in English.",
        capabilities=capabilities,
        output_type=Diagnosis,
    )
