"""Native skill resources, deferred MCP catalogs and always-on Code Mode."""

from pydantic_ai.capabilities import LocalWorkspace, ToolSearch
from pydantic_ai_harness import CodeMode, FileSystem, Skills
from pydantic_monty import MountDir

from skill_improve_cycle.common.registry import SKILL, active_revision, revision_dir


def build_capabilities(capabilities, skills_root=None):
    """Expose one skill revision; the active one unless a root is given."""
    root = str(skills_root or revision_dir(active_revision()))
    return [
        *capabilities,
        LocalWorkspace(root, read_only=True),
        Skills(".", include=[SKILL]),
        FileSystem(read_only=True, tools=["read_file"]),
        ToolSearch(strategy="keywords", max_results=50),
        CodeMode(
            mount=MountDir(host_path=root, virtual_path="/skills", mode="read-only"),
            max_tool_calls=40,
            resource_limits={"max_memory": 64 * 1024 * 1024},
        ),
    ]
