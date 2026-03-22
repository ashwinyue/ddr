"""Built-in subagent configurations."""

from .bash_agent import BASH_AGENT_CONFIG
from .claude_code_agent import CLAUDE_CODE_AGENT_CONFIG
from .general_purpose import GENERAL_PURPOSE_CONFIG

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "BASH_AGENT_CONFIG",
    "CLAUDE_CODE_AGENT_CONFIG",
]

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "claude-code": CLAUDE_CODE_AGENT_CONFIG,
}
