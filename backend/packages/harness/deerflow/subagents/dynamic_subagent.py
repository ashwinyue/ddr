"""Dynamic subagent registry for runtime registration of subagent configurations."""

import json
import logging
import re
import threading
from pathlib import Path

from deerflow.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)

# Reserved names that cannot be used for dynamic subagents
_RESERVED_NAMES: frozenset[str] = frozenset({"general-purpose", "bash", "claude-code"})

# Valid name pattern: lowercase letters, digits, and hyphens; must start with a letter
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


class DynamicSubagentRegistry:
    """Thread-safe registry for dynamically registered subagent configurations.

    Supports runtime registration/unregistration of subagents and optional
    persistence to the filesystem.
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        """Initialize the registry.

        Args:
            persist_path: Optional path to persist registrations as JSON.
                          On init, existing data is loaded from this path if present.
        """
        self._lock = threading.RLock()
        self._registry: dict[str, SubagentConfig] = {}
        self._persist_path = persist_path

        if persist_path is not None:
            self._load_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, config: SubagentConfig, *, overwrite: bool = False) -> None:
        """Register a subagent configuration.

        Args:
            config: The subagent configuration to register.
            overwrite: If True, allow replacing an existing registration.

        Raises:
            ValueError: If the name is reserved, invalid, or already registered
                        (when overwrite=False).
        """
        if not _NAME_PATTERN.match(config.name):
            raise ValueError(
                f"Subagent name '{config.name}' is invalid. "
                "Use lowercase letters, digits, and hyphens only. Must start with a letter."
            )
        if config.name in _RESERVED_NAMES:
            raise ValueError(f"Subagent name '{config.name}' is reserved for built-in subagents.")

        with self._lock:
            if config.name in self._registry and not overwrite:
                raise ValueError(
                    f"Subagent '{config.name}' is already registered. "
                    "Use overwrite=True to replace it."
                )
            self._registry[config.name] = config
            logger.info("Registered dynamic subagent '%s'", config.name)
            if self._persist_path is not None:
                self._save_to_disk()

    def unregister(self, name: str) -> bool:
        """Unregister a subagent configuration.

        Args:
            name: The name of the subagent to remove.

        Returns:
            True if the subagent was found and removed, False otherwise.
        """
        with self._lock:
            if name in self._registry:
                del self._registry[name]
                logger.info("Unregistered dynamic subagent '%s'", name)
                if self._persist_path is not None:
                    self._save_to_disk()
                return True
            return False

    def get(self, name: str) -> SubagentConfig | None:
        """Get a subagent configuration by name.

        Args:
            name: The name of the subagent.

        Returns:
            SubagentConfig if found, None otherwise.
        """
        with self._lock:
            return self._registry.get(name)

    def list_all(self) -> list[SubagentConfig]:
        """Return all registered dynamic subagent configurations.

        Returns:
            List of SubagentConfig instances (snapshot, not live references).
        """
        with self._lock:
            return list(self._registry.values())

    def get_all_names(self) -> list[str]:
        """Return all registered subagent names.

        Returns:
            Sorted list of subagent names.
        """
        with self._lock:
            return sorted(self._registry.keys())

    def as_dict(self) -> dict[str, SubagentConfig]:
        """Return a snapshot of the registry as a name-to-config mapping.

        Returns:
            Dict mapping name -> SubagentConfig.
        """
        with self._lock:
            return dict(self._registry)

    def __len__(self) -> int:
        with self._lock:
            return len(self._registry)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save_to_disk(self) -> None:
        """Persist the registry to disk (must be called with the lock held)."""
        assert self._persist_path is not None
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                name: {
                    "name": cfg.name,
                    "description": cfg.description,
                    "system_prompt": cfg.system_prompt,
                    "tools": cfg.tools,
                    "disallowed_tools": cfg.disallowed_tools,
                    "model": cfg.model,
                    "max_turns": cfg.max_turns,
                    "timeout_seconds": cfg.timeout_seconds,
                    "allow_nested_tasks": cfg.allow_nested_tasks,
                }
                for name, cfg in self._registry.items()
            }
            self._persist_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Persisted %d dynamic subagent(s) to %s", len(data), self._persist_path)
        except Exception as exc:
            logger.error("Failed to persist dynamic subagents to disk: %s", exc)

    def _load_from_disk(self) -> None:
        """Load the registry from disk (called once during __init__)."""
        assert self._persist_path is not None
        if not self._persist_path.exists():
            return
        try:
            data: dict = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for entry in data.values():
                config = SubagentConfig(
                    name=entry["name"],
                    description=entry["description"],
                    system_prompt=entry["system_prompt"],
                    tools=entry.get("tools"),
                    disallowed_tools=entry.get("disallowed_tools"),
                    model=entry.get("model", "inherit"),
                    max_turns=entry.get("max_turns", 50),
                    timeout_seconds=entry.get("timeout_seconds", 900),
                    allow_nested_tasks=entry.get("allow_nested_tasks", False),
                )
                self._registry[config.name] = config
            logger.info(
                "Loaded %d dynamic subagent(s) from %s",
                len(self._registry),
                self._persist_path,
            )
        except Exception as exc:
            logger.error("Failed to load dynamic subagents from disk: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_global_registry: DynamicSubagentRegistry | None = None
_global_registry_lock = threading.Lock()


def get_dynamic_registry() -> DynamicSubagentRegistry:
    """Return the process-wide DynamicSubagentRegistry singleton.

    The registry is created lazily on first access. Persistence path is
    derived from the application configuration when available.

    Returns:
        The global DynamicSubagentRegistry instance.
    """
    global _global_registry
    if _global_registry is None:
        with _global_registry_lock:
            if _global_registry is None:
                persist_path = _get_default_persist_path()
                _global_registry = DynamicSubagentRegistry(persist_path=persist_path)
    return _global_registry


def _get_default_persist_path() -> Path | None:
    """Derive the default persistence path from the application configuration."""
    try:
        # Avoid importing config at module level to prevent circular imports
        from deerflow.config import get_app_config  # noqa: PLC0415

        get_app_config()  # Ensure config is reachable; ignore the value
        storage_base = Path(".deer-flow")
        return storage_base / "dynamic_subagents.json"
    except Exception:
        return None
