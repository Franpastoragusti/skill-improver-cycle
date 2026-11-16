"""Native skill resources, deferred MCP catalogs and always-on Code Mode."""

from importlib.resources import files

from pydantic_ai.capabilities import LocalWorkspace, ToolSearch
from pydantic_ai_harness import CodeMode, FileSystem, Skills
from pydantic_monty import MountDir

SKILLS_ROOT = files("skill_improve_cycle.common").joinpath("skills")


def build_capabilities(capabilities):
    return [
        *capabilities,
        LocalWorkspace(str(SKILLS_ROOT), read_only=True),
        Skills(".", include=["investigate-incident"]),
        FileSystem(read_only=True, tools=["read_file"]),
        ToolSearch(strategy="keywords", max_results=50),
        CodeMode(
            mount=MountDir(host_path=str(SKILLS_ROOT), virtual_path="/skills", mode="read-only"),
            max_tool_calls=40,
            resource_limits={"max_memory": 64 * 1024 * 1024},
        ),
    ]
