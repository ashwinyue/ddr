"""WeChat ilink channel — connects to WeChat via HTTP long-polling (no public IP needed)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.channels.base import Channel
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage

logger = logging.getLogger(__name__)

# ilink API constants
_ILINK_DEFAULT_BASE = "https://ilinkai.weixin.qq.com"
_POLL_TIMEOUT = 38        # seconds — server holds up to 35s, 3s client margin
_RECONNECT_DELAY = 2      # seconds between retry attempts
_BACKOFF_DELAY = 30       # seconds after MAX_CONSECUTIVE_FAILURES
_MAX_CONSECUTIVE_FAILURES = 3
_SESSION_PAUSE_SECONDS = 3600  # 1 hour — errcode -14 session expired
_SESSION_EXPIRED_ERRCODE = -14

_TEXT_TYPE = 1            # MessageItemType.TEXT
_IMAGE_TYPE = 2           # MessageItemType.IMAGE
_VOICE_TYPE = 3           # MessageItemType.VOICE
_FILE_TYPE = 4            # MessageItemType.FILE
_VIDEO_TYPE = 5           # MessageItemType.VIDEO
_BOT_MESSAGE_TYPE = 2     # message_type: BOT
_MSG_STATE_FINISH = 2     # message_state: FINISH
_TYPING_STATUS_TYPING = 1
_TYPING_STATUS_CANCEL = 2

# Required in every ilink API request (from SDK source: buildBaseInfo())
_BASE_INFO = {"channel_version": "1.0.0"}

# Persistent cursor storage path (mirrors SDK: ~/.openclaw/.../accounts/{id}.sync.json)
_SYNC_BUF_DIR = Path.home() / ".openclaw" / "weixin-accounts"


def _random_uin() -> str:
    """Generate X-WECHAT-UIN header: base64(str(random_uint32))."""
    val = random.randint(0, 2**32 - 1)
    return base64.b64encode(str(val).encode()).decode()


def _strip_markdown(text: str) -> str:
    """Convert markdown to plain text for WeChat delivery (WeChat does not render markdown).

    Mirrors the SDK's markdownToPlainText logic (send.ts).
    """
    # Code blocks: keep content, strip fences
    text = re.sub(r"```[^\n]*\n?([\s\S]*?)```", lambda m: m.group(1).strip(), text)
    # Images: remove entirely
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # Links: keep display text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Table separator rows
    text = re.sub(r"^\|[\s:|-]+\|$", "", text, flags=re.MULTILINE)
    # Table rows: strip pipes
    text = re.sub(
        r"^\|(.+)\|$",
        lambda m: "  ".join(c.strip() for c in m.group(1).split("|")),
        text,
        flags=re.MULTILINE,
    )
    # Bold / italic / strikethrough / inline code
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r"^[-*_]{3,}$", "", text, flags=re.MULTILINE)
    # Collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _body_from_item_list(item_list: list[dict[str, Any]]) -> str:
    """Extract text body from item_list, including quoted message context.

    Mirrors SDK's bodyFromItemList in inbound.ts:
    - TEXT item: use text_item.text, prepend [引用: ...] if ref_msg present
    - VOICE item with voice_item.text: use transcribed text
    """
    if not item_list:
        return ""
    for item in item_list:
        item_type = item.get("type")
        if item_type == _TEXT_TYPE:
            text = item.get("text_item", {}).get("text") or ""
            text = str(text).strip()
            ref = item.get("ref_msg")
            if not ref:
                return text
            # Quoted media → only return current text (media comes separately)
            ref_item = ref.get("message_item")
            if ref_item and ref_item.get("type") in (_IMAGE_TYPE, _VIDEO_TYPE, _FILE_TYPE, _VOICE_TYPE):
                return text
            # Build quoted context from title + ref body
            parts: list[str] = []
            if ref.get("title"):
                parts.append(str(ref["title"]))
            if ref_item:
                ref_body = _body_from_item_list([ref_item])
                if ref_body:
                    parts.append(ref_body)
            if not parts:
                return text
            return f"[引用: {' | '.join(parts)}]\n{text}"
        # Voice-to-text: voice_item.text present
        if item_type == _VOICE_TYPE:
            voice_text = item.get("voice_item", {}).get("text")
            if voice_text:
                return str(voice_text).strip()
    return ""


class WeixinChannel(Channel):
    """WeChat ilink IM channel using HTTP long-polling.

    Configuration keys (in ``config.yaml`` under ``channels.weixin``):
        - ``bot_token``: Bot token from QR login.
        - ``bot_id``: ilink bot ID from QR login.
        - ``base_url``: ilink API base URL (default: https://ilinkai.weixin.qq.com).

    The channel uses HTTP long-polling so no public IP is required.
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="weixin", bus=bus, config=config)
        self._poll_task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None
        self._cursor: str = ""        # get_updates_buf cursor (in-memory)
        self._poll_timeout: int = 35  # dynamic, updated from server's longpolling_timeout_ms
        # Session pause: errcode -14 triggers 1-hour cooldown
        self._session_paused_until: float = 0.0
        # Per-user typing ticket cache: user_id → typing_ticket
        self._typing_ticket_cache: dict[str, str] = {}

    # -- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return

        bot_token = self.config.get("bot_token", "")
        bot_id = self.config.get("bot_id", "")

        if not bot_token or not bot_id:
            logger.error("WeChat channel requires bot_token and bot_id")
            return

        base_url = self.config.get("base_url") or _ILINK_DEFAULT_BASE
        self._base_url = base_url.rstrip("/")
        self._bot_token = bot_token
        self._bot_id = bot_id

        # Load persisted cursor (resume from last position across restarts)
        self._cursor = self._load_cursor()

        self._client = httpx.AsyncClient(timeout=httpx.Timeout(_POLL_TIMEOUT + 10))
        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        self._poll_task = asyncio.create_task(self._poll_loop(), name="weixin-poll")
        logger.info("WeChat channel started (bot_id=%s)", bot_id)

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("WeChat channel stopped")

    # -- cursor persistence ---------------------------------------------------

    def _cursor_path(self) -> Path:
        """Persistent cursor file path (mirrors SDK sync-buf.ts)."""
        safe_id = re.sub(r"[^a-zA-Z0-9._-]", "-", self._bot_id)
        return _SYNC_BUF_DIR / f"{safe_id}.sync.json"

    def _load_cursor(self) -> str:
        try:
            path = self._cursor_path()
            if path.exists():
                data = json.loads(path.read_text())
                buf = data.get("get_updates_buf", "")
                if buf:
                    logger.info("[WeChat] resuming from persisted cursor (%d bytes)", len(buf))
                    return buf
        except Exception:
            logger.debug("[WeChat] failed to load cursor, starting fresh")
        return ""

    def _save_cursor(self, buf: str) -> None:
        try:
            path = self._cursor_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"get_updates_buf": buf}))
        except Exception as exc:
            logger.debug("[WeChat] failed to save cursor: %s", exc)

    # -- outbound -------------------------------------------------------------

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        context_token = msg.metadata.get("context_token", "")
        if not context_token:
            logger.warning("[WeChat] missing context_token for chat_id=%s, cannot reply", msg.chat_id)
            return

        # WeChat does not render Markdown — strip before sending
        plain_text = _strip_markdown(msg.text)
        logger.info("[WeChat] sending reply: chat_id=%s, text_len=%d", msg.chat_id, len(plain_text))

        # Send typing cancel after reply (fire-and-forget)
        typing_ticket = self._typing_ticket_cache.get(msg.chat_id, "")

        last_exc: Exception | None = None
        try:
            for attempt in range(_max_retries):
                try:
                    await self._send_text(
                        to_user_id=msg.chat_id,
                        text=plain_text,
                        context_token=context_token,
                    )
                    return
                except Exception as exc:
                    last_exc = exc
                    if attempt < _max_retries - 1:
                        delay = 2**attempt
                        logger.warning(
                            "[WeChat] send failed (attempt %d/%d), retrying in %ds: %s",
                            attempt + 1,
                            _max_retries,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)

            logger.error("[WeChat] send failed after %d attempts: %s", _max_retries, last_exc)
            raise last_exc  # type: ignore[misc]
        finally:
            # Always cancel typing indicator — mirrors SDK's processOneMessage finally block
            if typing_ticket:
                asyncio.create_task(self._send_typing(msg.chat_id, typing_ticket, _TYPING_STATUS_CANCEL))

    # -- ilink API ------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self._bot_token}",
            "X-WECHAT-UIN": _random_uin(),
            "Content-Type": "application/json",
        }

    async def _api_post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to an ilink API endpoint."""
        if not self._client:
            raise RuntimeError("HTTP client not initialized")
        url = f"{self._base_url}{path}"
        resp = await self._client.post(url, headers=self._headers(), json=data)
        resp.raise_for_status()
        text = resp.text
        return {} if not text.strip() else resp.json()

    async def _get_updates(self) -> dict[str, Any]:
        """Long-poll for new messages.

        SDK format: {"get_updates_buf": "...", "base_info": {...}}
        Response:   {"msgs": [...], "get_updates_buf": "...", "longpolling_timeout_ms": N}
        """
        return await self._api_post(
            "/ilink/bot/getupdates",
            {"get_updates_buf": self._cursor, "base_info": _BASE_INFO},
        )

    async def _send_text(self, to_user_id: str, text: str, context_token: str) -> None:
        """Send a text message to a WeChat user.

        SDK format (from send.ts + api.ts):
          {"msg": {from_user_id:"", to_user_id, client_id, message_type:2,
                   message_state:2, item_list:[{type:1, text_item:{text}}],
                   context_token},
           "base_info": {...}}
        """
        await self._api_post(
            "/ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": str(uuid.uuid4()),
                    "message_type": _BOT_MESSAGE_TYPE,
                    "message_state": _MSG_STATE_FINISH,
                    "item_list": [{"type": _TEXT_TYPE, "text_item": {"text": text}}],
                    "context_token": context_token,
                },
                "base_info": _BASE_INFO,
            },
        )

    async def _get_config(self, user_id: str, context_token: str) -> dict[str, Any]:
        """Fetch bot config for a user — returns typing_ticket.

        SDK: getConfig → {typing_ticket, ret}
        """
        try:
            return await self._api_post(
                "/ilink/bot/getconfig",
                {
                    "ilink_user_id": user_id,
                    "context_token": context_token,
                    "base_info": _BASE_INFO,
                },
            )
        except Exception as exc:
            logger.debug("[WeChat] getConfig failed for %s: %s", user_id, exc)
            return {}

    async def _send_typing(self, user_id: str, typing_ticket: str, status: int) -> None:
        """Send typing indicator to a user (fire-and-forget).

        status: 1=typing, 2=cancel
        """
        try:
            await self._api_post(
                "/ilink/bot/sendtyping",
                {
                    "ilink_user_id": user_id,
                    "typing_ticket": typing_ticket,
                    "status": status,
                    "base_info": _BASE_INFO,
                },
            )
        except Exception as exc:
            logger.debug("[WeChat] sendTyping failed for %s: %s", user_id, exc)

    # -- poll loop ------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Continuously long-poll for updates and dispatch inbound messages."""
        logger.info("[WeChat] poll loop started")
        consecutive_failures = 0
        while self._running:
            # Session pause (errcode -14)
            if self._session_paused_until > time.time():
                remaining = self._session_paused_until - time.time()
                logger.info("[WeChat] session paused, waiting %.0fs", remaining)
                await asyncio.sleep(min(remaining, 60))
                continue

            try:
                result = await self._get_updates()

                # Respect server-suggested timeout for next poll
                suggested_ms = result.get("longpolling_timeout_ms")
                if suggested_ms and suggested_ms > 0:
                    self._poll_timeout = suggested_ms // 1000

                # Update and persist cursor
                new_cursor = result.get("get_updates_buf", "")
                if new_cursor:
                    self._cursor = new_cursor
                    self._save_cursor(new_cursor)

                # Check API-level errors
                ret = result.get("ret")
                errcode = result.get("errcode")
                is_error = (ret is not None and ret != 0) or (errcode is not None and errcode != 0)
                if is_error:
                    # errcode -14 = session expired → pause 1 hour (SDK: session-guard.ts)
                    if errcode == _SESSION_EXPIRED_ERRCODE or ret == _SESSION_EXPIRED_ERRCODE:
                        self._session_paused_until = time.time() + _SESSION_PAUSE_SECONDS
                        logger.warning(
                            "[WeChat] session expired (errcode -14), pausing for %d min",
                            _SESSION_PAUSE_SECONDS // 60,
                        )
                        consecutive_failures = 0
                        continue

                    consecutive_failures += 1
                    logger.warning(
                        "[WeChat] getupdates error: ret=%s errcode=%s errmsg=%s (%d/%d)",
                        ret, errcode, result.get("errmsg"), consecutive_failures, _MAX_CONSECUTIVE_FAILURES,
                    )
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        consecutive_failures = 0
                        await asyncio.sleep(_BACKOFF_DELAY)
                    else:
                        await asyncio.sleep(_RECONNECT_DELAY)
                    continue

                consecutive_failures = 0
                updates = result.get("msgs") or []
                for update in updates:
                    await self._handle_update(update)

            except asyncio.CancelledError:
                break
            except httpx.TimeoutException:
                logger.debug("[WeChat] poll timeout (normal), continuing")
            except Exception:
                consecutive_failures += 1
                if self._running:
                    logger.exception(
                        "[WeChat] poll error (%d/%d), reconnecting in %ds",
                        consecutive_failures, _MAX_CONSECUTIVE_FAILURES, _RECONNECT_DELAY,
                    )
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        consecutive_failures = 0
                        await asyncio.sleep(_BACKOFF_DELAY)
                    else:
                        await asyncio.sleep(_RECONNECT_DELAY)

        logger.info("[WeChat] poll loop stopped")

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """Process a single update from ilink getupdates."""
        try:
            # Skip messages sent by the bot itself
            if update.get("message_type") == _BOT_MESSAGE_TYPE:
                return

            from_user_id = update.get("from_user_id", "")
            context_token = update.get("context_token", "")
            item_list = update.get("item_list") or []

            # Extract text (supports plain text, quoted messages, voice-to-text)
            text = _body_from_item_list(item_list)

            logger.info("[WeChat] message from user_id=%s, text=%r", from_user_id, text[:100] if text else "")

            if not text:
                logger.debug("[WeChat] empty text update, ignoring")
                return

            # Fetch per-user config for typing_ticket (SDK: WeixinConfigManager.getForUser)
            # Only cache ticket when ret == 0 (SDK checks resp.ret === 0 before trusting response)
            if context_token and from_user_id:
                config_resp = await self._get_config(from_user_id, context_token)
                if config_resp.get("ret", 0) == 0:
                    typing_ticket = config_resp.get("typing_ticket", "")
                    if typing_ticket:
                        self._typing_ticket_cache[from_user_id] = typing_ticket
                # Always start typing with cached ticket (even if getConfig failed this time)
                cached_ticket = self._typing_ticket_cache.get(from_user_id, "")
                if cached_ticket:
                    asyncio.create_task(self._send_typing(from_user_id, cached_ticket, _TYPING_STATUS_TYPING))

            msg_type = InboundMessageType.COMMAND if text.startswith("/") else InboundMessageType.CHAT

            inbound = self._make_inbound(
                chat_id=from_user_id,
                user_id=from_user_id,
                text=text,
                msg_type=msg_type,
                thread_ts=context_token,
                metadata={"context_token": context_token},
            )
            # Each user gets a persistent DeerFlow thread
            inbound.topic_id = from_user_id

            await self.bus.publish_inbound(inbound)
        except Exception:
            logger.exception("[WeChat] error handling update: %s", update)
