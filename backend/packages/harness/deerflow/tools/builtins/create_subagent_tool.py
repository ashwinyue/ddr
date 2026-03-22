"""Tool for dynamically registering new subagent configurations at runtime."""

import logging

from langchain.tools import tool

from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.dynamic_subagent import get_dynamic_registry

logger = logging.getLogger(__name__)


@tool("create_subagent", parse_docstring=True)
def create_subagent_tool(
    name: str,
    description: str,
    system_prompt: str,
    tools: list[str] | None = None,
    max_turns: int = 50,
    timeout_seconds: int = 900,
    allow_nested_tasks: bool = False,
) -> str:
    """Create a new specialized subagent that can be invoked via the task tool.

    Once created, the subagent is available immediately for the current session
    (and persisted across restarts). Invoke it with:
        task(subagent_type="<name>", prompt="...", description="...")

    Args:
        name: Unique identifier for the new subagent. Lowercase letters, digits,
              and hyphens only; must start with a letter (e.g., "data-analyzer").
        description: Describes when the parent agent should delegate to this subagent.
                     Be specific about capabilities and intended use cases.
        system_prompt: The full system prompt defining this subagent's behavior,
                       persona, and constraints.
        tools: Optional list of tool names to restrict this subagent to. When None,
               the subagent inherits all tools available to the parent (excluding
               disallowed ones). Example: ["bash", "read_file", "write_file"].
        max_turns: Maximum number of agent turns before the subagent stops
                   (default: 50).
        timeout_seconds: Maximum wall-clock execution time in seconds
                         (default: 900 = 15 minutes).
        allow_nested_tasks: If True, this subagent may itself spawn further subagents
                            via the task tool (one level of nesting). Defaults to False
                            to prevent unbounded recursion.

    Returns:
        A success message containing the subagent name and usage example,
        or an error description if registration failed.
    """
    # Validate: reserved built-in names
    if name in BUILTIN_SUBAGENTS:
        return (
            f"Error: '{name}' is a reserved built-in subagent name. "
            "Choose a different name."
        )

    registry = get_dynamic_registry()

    # Validate: uniqueness
    if registry.get(name) is not None:
        return (
            f"Error: A subagent named '{name}' is already registered. "
            "Choose a different name or unregister the existing one first."
        )

    # Build config — disallow task/clarification/present_files by default unless
    # allow_nested_tasks is explicitly requested
    disallowed: list[str] = ["ask_clarification", "present_files"]
    if not allow_nested_tasks:
        disallowed.append("task")

    config = SubagentConfig(
        name=name,
        description=description,
        system_prompt=system_prompt,
        tools=tools,
        disallowed_tools=disallowed,
        model="inherit",
        max_turns=max_turns,
        timeout_seconds=timeout_seconds,
        allow_nested_tasks=allow_nested_tasks,
    )

    try:
        registry.register(config)
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        logger.error("Unexpected error registering dynamic subagent '%s': %s", name, exc)
        return f"Error: Failed to register subagent '{name}': {exc}"

    logger.info(
        "Dynamic subagent '%s' registered (nested_tasks=%s, max_turns=%d, timeout=%ds)",
        name,
        allow_nested_tasks,
        max_turns,
        timeout_seconds,
    )
    return (
        f"Success: Subagent '{name}' created and ready to use.\n"
        f"Invoke it with: task(subagent_type='{name}', description='...', prompt='...')"
    )
