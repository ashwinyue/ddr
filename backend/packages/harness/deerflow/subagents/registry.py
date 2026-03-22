"""Subagent registry for managing available subagents.

Built-in subagents are defined in `deerflow.subagents.builtins`.  Dynamic
subagents registered at runtime via `create_subagent` tool are stored in
`DynamicSubagentRegistry` and merged transparently with the built-ins.

Lookup priority: built-in > dynamic (built-ins are always preferred to prevent
shadowing of core functionality).
"""

import logging
from dataclasses import replace

from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
from deerflow.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)


def get_subagent_config(name: str) -> SubagentConfig | None:
    """Get a subagent configuration by name.

    Looks up built-in subagents first, then falls back to dynamically registered
    ones.  For built-in subagents, config.yaml timeout overrides are applied.

    Args:
        name: The name of the subagent.

    Returns:
        SubagentConfig if found (with any config.yaml overrides applied for
        built-ins), None otherwise.
    """
    # 1. Check built-in subagents
    config = BUILTIN_SUBAGENTS.get(name)
    if config is not None:
        # Apply timeout override from config.yaml (lazy import to avoid circular deps)
        from deerflow.config.subagents_config import get_subagents_app_config  # noqa: PLC0415

        app_config = get_subagents_app_config()
        effective_timeout = app_config.get_timeout_for(name)
        if effective_timeout != config.timeout_seconds:
            logger.debug(
                "Subagent '%s': timeout overridden by config.yaml (%ds -> %ds)",
                name,
                config.timeout_seconds,
                effective_timeout,
            )
            config = replace(config, timeout_seconds=effective_timeout)
        return config

    # 2. Fall back to dynamic subagent registry
    from deerflow.subagents.dynamic_subagent import get_dynamic_registry  # noqa: PLC0415

    dynamic_config = get_dynamic_registry().get(name)
    if dynamic_config is not None:
        logger.debug("Resolved subagent '%s' from dynamic registry", name)
        return dynamic_config

    return None


def list_subagents() -> list[SubagentConfig]:
    """List all available subagent configurations.

    Returns built-in configs (with config.yaml overrides applied) followed by
    all dynamically registered configs.

    Returns:
        List of all registered SubagentConfig instances.
    """
    builtin_configs = [get_subagent_config(name) for name in BUILTIN_SUBAGENTS]

    from deerflow.subagents.dynamic_subagent import get_dynamic_registry  # noqa: PLC0415

    dynamic_configs = get_dynamic_registry().list_all()
    return builtin_configs + dynamic_configs  # type: ignore[return-value]


def get_subagent_names() -> list[str]:
    """Get all available subagent names (built-in + dynamic).

    Returns:
        List of subagent names.
    """
    builtin_names = list(BUILTIN_SUBAGENTS.keys())

    from deerflow.subagents.dynamic_subagent import get_dynamic_registry  # noqa: PLC0415

    dynamic_names = get_dynamic_registry().get_all_names()
    return builtin_names + dynamic_names
