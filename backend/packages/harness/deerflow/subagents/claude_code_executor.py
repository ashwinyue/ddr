"""Claude Code CLI subprocess executor for deer-flow subagent system."""

import json
import logging
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from typing import Callable

from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.executor import SubagentResult, SubagentStatus

logger = logging.getLogger(__name__)

# Event callback type: receives a dict event for streaming to the caller
EventCallback = Callable[[dict], None]


def is_claude_available() -> bool:
    """Check whether the claude CLI is available in PATH."""
    return shutil.which("claude") is not None


def _truncate(text: str, max_len: int = 300) -> str:
    """Truncate a string for display, appending ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """Build a concise one-line summary of a tool call for verbose display."""
    if not tool_input:
        return tool_name
    # For bash/shell tools show the command
    if tool_name.lower() in ("bash", "shell", "execute"):
        cmd = tool_input.get("command") or tool_input.get("cmd", "")
        return f"{tool_name}: {_truncate(str(cmd), 200)}"
    # Generic: show key=value pairs, truncated
    pairs = ", ".join(f"{k}={_truncate(str(v), 80)}" for k, v in list(tool_input.items())[:3])
    return f"{tool_name}({pairs})"


def _extract_text_content(content) -> str:
    """Extract text from Claude's content field (str or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "thinking":
                    parts.append(f"[thinking] {_truncate(block.get('thinking', ''), 200)}")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(content)


class ClaudeCodeExecutor:
    """Execute tasks via Claude Code CLI subprocess.

    Spawns `claude` with --output-format stream-json / --input-format stream-json,
    feeds the task prompt via stdin, and collects the streaming JSON output.

    verbose=False (default): only the final `result` event is surfaced.
    verbose=True: tool_use / tool_result / thinking events are emitted via
                  on_event callback in real-time, suitable for streaming to chat.
    """

    def __init__(
        self,
        config: SubagentConfig,
        work_dir: str = ".",
        verbose: bool = False,
        permission_mode: str = "bypassPermissions",
        trace_id: str | None = None,
    ):
        self.config = config
        self.work_dir = work_dir
        self.verbose = verbose
        self.permission_mode = permission_mode
        self.trace_id = trace_id or str(uuid.uuid4())[:8]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, task: str, on_event: EventCallback | None = None) -> SubagentResult:
        """Run task synchronously and return SubagentResult.

        Args:
            task: Natural-language task description sent to Claude Code.
            on_event: Optional callback for streaming events (verbose mode).
                      Called from the same thread as execute().
        """
        if not is_claude_available():
            return SubagentResult(
                task_id=str(uuid.uuid4())[:8],
                trace_id=self.trace_id,
                status=SubagentStatus.FAILED,
                error="claude CLI not found in PATH. Install Claude Code first.",
                started_at=datetime.now(),
                completed_at=datetime.now(),
            )

        task_id = str(uuid.uuid4())[:8]
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )

        try:
            self._run(task, result, on_event)
        except Exception as exc:
            logger.exception("[trace=%s] ClaudeCodeExecutor unexpected error", self.trace_id)
            result.status = SubagentStatus.FAILED
            result.error = str(exc)
            result.completed_at = datetime.now()

        return result

    def execute_async(self, task: str, task_id: str, on_event: EventCallback | None = None) -> SubagentResult:
        """Run task in a background thread. Returns a SubagentResult that is
        updated in-place as execution progresses (for polling by task_tool)."""
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
        )

        def _worker():
            result.status = SubagentStatus.RUNNING
            result.started_at = datetime.now()
            try:
                self._run(task, result, on_event)
            except Exception as exc:
                logger.exception("[trace=%s] ClaudeCodeExecutor thread error", self.trace_id)
                result.status = SubagentStatus.FAILED
                result.error = str(exc)
                result.completed_at = datetime.now()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    # All tools that Claude Code can call — pre-authorized to avoid interactive
    # permission prompts without needing --dangerously-skip-permissions (which
    # is blocked when running as root).
    _ALL_ALLOWED_TOOLS = (
        "Bash,Read,Write,Edit,MultiEdit,Glob,Grep,LS,"
        "NotebookRead,NotebookEdit,TodoRead,TodoWrite,Task,WebFetch,WebSearch"
    )

    def _build_args(self) -> list[str]:
        args = [
            "claude",
            "--output-format", "stream-json",
            "--verbose",
            "--input-format", "stream-json",
        ]
        if self.permission_mode == "bypassPermissions":
            # bypassPermissions = --dangerously-skip-permissions, blocked on root.
            # Use --allowedTools to pre-authorize all tools instead.
            args += ["--allowedTools", self._ALL_ALLOWED_TOOLS]
        elif self.permission_mode and self.permission_mode != "default":
            args += ["--permission-mode", self.permission_mode,
                     "--allowedTools", self._ALL_ALLOWED_TOOLS]
        else:
            args += ["--permission-prompt-tool", "stdio"]
        return args

    def _run(self, task: str, result: SubagentResult, on_event: EventCallback | None) -> None:
        """Core execution: spawn subprocess, send task, parse events."""
        args = self._build_args()
        logger.info(
            "[trace=%s] ClaudeCodeExecutor starting: work_dir=%s verbose=%s",
            self.trace_id, self.work_dir, self.verbose,
        )

        proc = subprocess.Popen(
            args,
            cwd=self.work_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,  # line-buffered
        )

        # Send the task prompt via stdin
        user_msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": task},
        })
        try:
            proc.stdin.write(user_msg + "\n")
            proc.stdin.flush()
            proc.stdin.close()
        except BrokenPipeError:
            pass

        # Read stdout line by line and parse events
        final_result: str | None = None
        error_msg: str | None = None
        text_parts: list[str] = []  # accumulate all assistant text blocks (cc-connect style)

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("[trace=%s] non-JSON stdout: %s", self.trace_id, line[:200])
                continue

            event_type = event.get("type", "")

            if event_type == "result":
                subtype = event.get("subtype", "")
                if subtype == "success":
                    final_result = event.get("result", "")
                    # cc-connect fallback: if result field is empty, use accumulated text parts
                    if not final_result and text_parts:
                        final_result = "\n\n".join(text_parts)
                    logger.info("[trace=%s] ClaudeCode result received (%d chars)", self.trace_id, len(final_result or ""))
                else:
                    error_msg = event.get("result") or event.get("error") or f"subtype={subtype}"
                    logger.warning("[trace=%s] ClaudeCode error result: %s", self.trace_id, error_msg)
                break  # result event signals end of stream

            elif event_type == "assistant":
                # Always process assistant events to accumulate text; verbose controls tool/thinking events
                self._handle_assistant_event(event, on_event, text_parts)

            elif event_type == "user" and self.verbose and on_event:
                self._handle_tool_result_event(event, on_event)

            elif event_type == "system":
                logger.debug("[trace=%s] system event: %s", self.trace_id, event.get("subtype"))

        # Collect any stderr for diagnostics
        stderr_output = proc.stderr.read() if proc.stderr else ""
        proc.wait()

        if final_result is not None:
            result.status = SubagentStatus.COMPLETED
            result.result = final_result
        else:
            result.status = SubagentStatus.FAILED
            result.error = error_msg or (f"Process exited with code {proc.returncode}. stderr: {_truncate(stderr_output, 500)}" if stderr_output else f"No result received (exit code {proc.returncode})")

        result.completed_at = datetime.now()

    def _handle_assistant_event(self, event: dict, on_event: EventCallback | None, text_parts: list[str]) -> None:
        """Parse assistant message event, accumulate text, and emit verbose callbacks.

        text_parts is always populated (regardless of verbose/on_event) so the
        executor can fall back to accumulated text when result.result is empty.

        on_event is called only when self.verbose is True (all block types).
        """
        message = event.get("message", {})
        content = message.get("content", [])
        if not isinstance(content, list):
            return

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")

            if block_type == "tool_use":
                if self.verbose and on_event:
                    tool_name = block.get("name", "unknown")
                    tool_input = block.get("input", {})
                    summary = _summarize_tool_input(tool_name, tool_input)
                    on_event({
                        "type": "claude_code_tool_use",
                        "tool_name": tool_name,
                        "summary": summary,
                    })

            elif block_type == "thinking":
                if self.verbose and on_event:
                    thinking_text = block.get("thinking", "")
                    if thinking_text:
                        on_event({
                            "type": "claude_code_thinking",
                            "content": _truncate(thinking_text, 400),
                        })

            elif block_type == "text":
                text = block.get("text", "")
                if text.strip():
                    text_parts.append(text)  # always accumulate for fallback
                    if self.verbose and on_event:
                        on_event({
                            "type": "claude_code_text",
                            "content": text,
                        })

    def _handle_tool_result_event(self, event: dict, on_event: EventCallback) -> None:
        """Parse user (tool_result) event and emit verbose callback."""
        message = event.get("message", {})
        content = message.get("content", [])
        if not isinstance(content, list):
            return

        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                is_error = block.get("is_error", False)
                result_content = block.get("content", "")
                text = _extract_text_content(result_content)
                on_event({
                    "type": "claude_code_tool_result",
                    "is_error": is_error,
                    "content": _truncate(text, 300),
                })
