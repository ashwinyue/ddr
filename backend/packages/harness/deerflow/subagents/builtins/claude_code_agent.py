"""Claude Code CLI subagent configuration."""

from deerflow.subagents.config import SubagentConfig

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
