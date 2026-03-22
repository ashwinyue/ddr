"""Claude Code CLI subagent configuration."""

import os

from deerflow.subagents.config import SubagentConfig

# Claude Code 子代理的默认工作目录
# 
# SECURITY NOTE: "/" is an INTENTIONAL design choice for trusted single-user environments
# where the user owns the entire system. This allows Claude Code to access and modify
# code anywhere on the filesystem, essential for cross-project refactoring and 
# system-wide operations.
#
# For multi-tenant or untrusted environments:
# - Set CLAUDE_CODE_WORK_DIR to a restricted path (e.g., "/home/user/projects")
# - Or use AioSandbox with Docker-based isolation instead of LocalSandbox
# See: https://docs.deerflow.dev/security/deployment-modes
CLAUDE_CODE_DEFAULT_WORK_DIR = os.environ.get("CLAUDE_CODE_WORK_DIR", "/")

CLAUDE_CODE_AGENT_CONFIG = SubagentConfig(
    name="claude-code",
    description="""Claude Code CLI specialist for software engineering tasks that require writing, modifying, or debugging code in a real project.

Use this subagent when:
- Writing new code, implementing features, or creating files
- Modifying existing source files (refactoring, bug fixes, enhancements)
- Running tests, builds, or scripts and interpreting results
- Debugging complex code issues that require reading and editing multiple files
- Setting up or configuring a project (dependencies, configs, scaffolding)
- Any task where the primary deliverable is working code in the filesystem

Do NOT use for:
- Pure research or information gathering (use general-purpose)
- Simple bash commands with no code writing (use bash)
- Tasks that only require reading and summarizing existing code without changes
""",
    # system_prompt is unused by ClaudeCodeExecutor (Claude Code has its own agent loop),
    # kept for registry compatibility.
    system_prompt="",
    tools=None,
    disallowed_tools=None,
    model="inherit",
    max_turns=50,
    timeout_seconds=1800,  # 30 minutes — coding tasks can be long
)
