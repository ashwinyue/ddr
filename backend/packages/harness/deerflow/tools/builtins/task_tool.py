"""Task tool for delegating work to subagents."""

import logging
import time
import uuid
from dataclasses import replace
from typing import Annotated, Literal

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langgraph.config import get_stream_writer
from langgraph.typing import ContextT

from deerflow.agents.lead_agent.prompt import get_skills_prompt_section
from deerflow.agents.thread_state import ThreadState
from deerflow.subagents import SubagentExecutor, get_subagent_config
from deerflow.subagents.executor import SubagentStatus, cleanup_background_task, get_background_task_result

logger = logging.getLogger(__name__)

# Subagent types that use ClaudeCodeExecutor instead of SubagentExecutor
_CLAUDE_CODE_TYPES = {"claude-code"}


@tool("task", parse_docstring=True)
def task_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    prompt: str,
    subagent_type: Literal["general-purpose", "bash", "claude-code"],
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_turns: int | None = None,
) -> str:
    """Delegate a task to a specialized subagent that runs in its own context.

    Subagents help you:
    - Preserve context by keeping exploration and implementation separate
    - Handle complex multi-step tasks autonomously
    - Execute commands or operations in isolated contexts

    Available subagent types:
    - **general-purpose**: A capable agent for complex, multi-step tasks that require
      both exploration and action. Use when the task requires complex reasoning,
      multiple dependent steps, or would benefit from isolated context.
    - **bash**: Command execution specialist for running bash commands. Use for
      git operations, build processes, or when command output would be verbose.
    - **claude-code**: Claude Code CLI specialist for software engineering tasks.
      Use when writing new code, implementing features, modifying source files,
      debugging, refactoring, or any task where the primary deliverable is working
      code in the filesystem. Requires the `claude` CLI to be installed.

    When to use this tool:
    - Complex tasks requiring multiple steps or tools
    - Tasks that produce verbose output
    - When you want to isolate context from the main conversation
    - Parallel research or exploration tasks

    When NOT to use this tool:
    - Simple, single-step operations (use tools directly)
    - Tasks requiring user interaction or clarification

    Args:
        description: A short (3-5 word) description of the task for logging/display. ALWAYS PROVIDE THIS PARAMETER FIRST.
        prompt: The task description for the subagent. Be specific and clear about what needs to be done. ALWAYS PROVIDE THIS PARAMETER SECOND.
        subagent_type: The type of subagent to use. ALWAYS PROVIDE THIS PARAMETER THIRD.
        max_turns: Optional maximum number of agent turns. Defaults to subagent's configured max.
    """
    # Get subagent configuration
    config = get_subagent_config(subagent_type)
    if config is None:
        return f"Error: Unknown subagent type '{subagent_type}'. Available: general-purpose, bash, claude-code"

    # Build config overrides
    overrides: dict = {}

    skills_section = get_skills_prompt_section()
    if skills_section:
        overrides["system_prompt"] = config.system_prompt + "\n\n" + skills_section

    if max_turns is not None:
        overrides["max_turns"] = max_turns

    if overrides:
        config = replace(config, **overrides)

    # Extract parent context from runtime
    sandbox_state = None
    thread_data = None
    thread_id = None
    parent_model = None
    trace_id = None

    if runtime is not None:
        sandbox_state = runtime.state.get("sandbox")
        thread_data = runtime.state.get("thread_data")
        thread_id = runtime.context.get("thread_id")

        # Try to get parent model from configurable
        metadata = runtime.config.get("metadata", {})
        parent_model = metadata.get("model_name")

        # Get or generate trace_id for distributed tracing
        trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]

    # Route to ClaudeCodeExecutor for claude-code subagent type
    if subagent_type in _CLAUDE_CODE_TYPES:
        # Read verbose flag: channel-level setting (via configurable) takes priority over config.yaml
        configurable = runtime.config.get("configurable", {}) if runtime else {}
        verbose_override = configurable.get("claude_code_verbose")
        return _run_claude_code(
            prompt=prompt,
            description=description,
            config=config,
            task_id=tool_call_id,
            trace_id=trace_id,
            work_dir="/",
            verbose_override=verbose_override,
        )

    # Get available tools (excluding task tool to prevent nesting)
    # Lazy import to avoid circular dependency
    from deerflow.tools import get_available_tools

    # Subagents should not have subagent tools enabled (prevent recursive nesting)
    tools = get_available_tools(model_name=parent_model, subagent_enabled=False)

    # Create executor
    executor = SubagentExecutor(
        config=config,
        tools=tools,
        parent_model=parent_model,
        sandbox_state=sandbox_state,
        thread_data=thread_data,
        thread_id=thread_id,
        trace_id=trace_id,
    )

    # Start background execution (always async to prevent blocking)
    # Use tool_call_id as task_id for better traceability
    task_id = executor.execute_async(prompt, task_id=tool_call_id)

    # Poll for task completion in backend (removes need for LLM to poll)
    poll_count = 0
    last_status = None
    last_message_count = 0  # Track how many AI messages we've already sent
    # Polling timeout: execution timeout + 60s buffer, checked every 5s
    max_poll_count = (config.timeout_seconds + 60) // 5

    logger.info(f"[trace={trace_id}] Started background task {task_id} (subagent={subagent_type}, timeout={config.timeout_seconds}s, polling_limit={max_poll_count} polls)")

    writer = get_stream_writer()
    # Send Task Started message'
    writer({"type": "task_started", "task_id": task_id, "description": description})

    while True:
        result = get_background_task_result(task_id)

        if result is None:
            logger.error(f"[trace={trace_id}] Task {task_id} not found in background tasks")
            writer({"type": "task_failed", "task_id": task_id, "error": "Task disappeared from background tasks"})
            cleanup_background_task(task_id)
            return f"Error: Task {task_id} disappeared from background tasks"

        # Log status changes for debugging
        if result.status != last_status:
            logger.info(f"[trace={trace_id}] Task {task_id} status: {result.status.value}")
            last_status = result.status

        # Check for new AI messages and send task_running events
        current_message_count = len(result.ai_messages)
        if current_message_count > last_message_count:
            # Send task_running event for each new message
            for i in range(last_message_count, current_message_count):
                message = result.ai_messages[i]
                writer(
                    {
                        "type": "task_running",
                        "task_id": task_id,
                        "message": message,
                        "message_index": i + 1,  # 1-based index for display
                        "total_messages": current_message_count,
                    }
                )
                logger.info(f"[trace={trace_id}] Task {task_id} sent message #{i + 1}/{current_message_count}")
            last_message_count = current_message_count

        # Check if task completed, failed, or timed out
        if result.status == SubagentStatus.COMPLETED:
            writer({"type": "task_completed", "task_id": task_id, "result": result.result})
            logger.info(f"[trace={trace_id}] Task {task_id} completed after {poll_count} polls")
            cleanup_background_task(task_id)
            return f"Task Succeeded. Result: {result.result}"
        elif result.status == SubagentStatus.FAILED:
            writer({"type": "task_failed", "task_id": task_id, "error": result.error})
            logger.error(f"[trace={trace_id}] Task {task_id} failed: {result.error}")
            cleanup_background_task(task_id)
            return f"Task failed. Error: {result.error}"
        elif result.status == SubagentStatus.TIMED_OUT:
            writer({"type": "task_timed_out", "task_id": task_id, "error": result.error})
            logger.warning(f"[trace={trace_id}] Task {task_id} timed out: {result.error}")
            cleanup_background_task(task_id)
            return f"Task timed out. Error: {result.error}"

        # Still running, wait before next poll
        time.sleep(5)  # Poll every 5 seconds
        poll_count += 1

        # Polling timeout as a safety net (in case thread pool timeout doesn't work)
        # Set to execution timeout + 60s buffer, in 5s poll intervals
        # This catches edge cases where the background task gets stuck
        # Note: We don't call cleanup_background_task here because the task may
        # still be running in the background. The cleanup will happen when the
        # executor completes and sets a terminal status.
        if poll_count > max_poll_count:
            timeout_minutes = config.timeout_seconds // 60
            logger.error(f"[trace={trace_id}] Task {task_id} polling timed out after {poll_count} polls (should have been caught by thread pool timeout)")
            writer({"type": "task_timed_out", "task_id": task_id})
            return f"Task polling timed out after {timeout_minutes} minutes. This may indicate the background task is stuck. Status: {result.status.value}"


def _run_claude_code(
    prompt: str,
    description: str,
    config,
    task_id: str,
    trace_id: str | None,
    work_dir: str,
    verbose_override: bool | None = None,
) -> str:
    """Execute a task via ClaudeCodeExecutor with streaming events.

    Runs synchronously in the current thread (Claude Code manages its own
    concurrency internally). Streams verbose events via LangGraph stream writer.

    verbose priority: channel /verbose command > config.yaml > False (default)
    """
    from deerflow.subagents.claude_code_executor import ClaudeCodeExecutor, is_claude_available

    writer = get_stream_writer()
    writer({"type": "task_started", "task_id": task_id, "description": description})

    if not is_claude_available():
        msg = "claude CLI not found in PATH. Install Claude Code first."
        writer({"type": "task_failed", "task_id": task_id, "error": msg})
        return f"Task failed. Error: {msg}"

    # verbose priority: channel setting (from /verbose command) > config.yaml > False
    verbose = verbose_override if verbose_override is not None else _get_claude_code_verbose()

    logger.info("[trace=%s] Starting claude-code task (verbose=%s): %s", trace_id, verbose, description)

    def _on_event(event: dict) -> None:
        """Forward verbose events to the stream writer."""
        event_type = event.get("type", "")
        if event_type == "claude_code_tool_use":
            writer({
                "type": "task_running",
                "task_id": task_id,
                "message": {"role": "assistant", "content": f"🔧 {event['summary']}"},
                "message_index": 0,
                "total_messages": 0,
            })
        elif event_type == "claude_code_tool_result":
            status_icon = "❌" if event.get("is_error") else "✅"
            writer({
                "type": "task_running",
                "task_id": task_id,
                "message": {"role": "assistant", "content": f"{status_icon} {event['content']}"},
                "message_index": 0,
                "total_messages": 0,
            })
        elif event_type == "claude_code_thinking":
            writer({
                "type": "task_running",
                "task_id": task_id,
                "message": {"role": "assistant", "content": f"💭 {event['content']}"},
                "message_index": 0,
                "total_messages": 0,
            })

    executor = ClaudeCodeExecutor(
        config=config,
        work_dir=work_dir,
        verbose=verbose,
        trace_id=trace_id,
    )

    result = executor.execute(prompt, on_event=_on_event if verbose else None)

    if result.status == SubagentStatus.COMPLETED:
        writer({"type": "task_completed", "task_id": task_id, "result": result.result})
        return f"Task Succeeded. Result: {result.result}"
    else:
        error = result.error or "Unknown error"
        writer({"type": "task_failed", "task_id": task_id, "error": error})
        return f"Task failed. Error: {error}"


def _get_claude_code_verbose() -> bool:
    """Read verbose flag from config.yaml subagents.claude_code.verbose (default: False)."""
    try:
        from deerflow.config import get_app_config
        cfg = get_app_config()
        subagents_cfg = getattr(cfg, "subagents", None)
        if subagents_cfg is None:
            return False
        claude_code_cfg = getattr(subagents_cfg, "claude_code", None)
        if claude_code_cfg is None:
            return False
        return bool(getattr(claude_code_cfg, "verbose", False))
    except Exception:
        return False
