"""WeChat ilink channel — connects to WeChat via HTTP long-polling (no public IP needed)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote as url_quote

import httpx

from app.channels.base import Channel
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage

logger = logging.getLogger(__name__)

# ilink API constants
_ILINK_DEFAULT_BASE = "https://ilinkai.weixin.qq.com"
_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"

# CDN media type constants (used by getuploadurl API)
_UPLOAD_MEDIA_IMAGE = 1
_UPLOAD_MEDIA_VIDEO = 2
_UPLOAD_MEDIA_FILE = 3
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


def _aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    """AES-128-ECB encrypt with PKCS7 padding (mirrors cc-connect encryptAESECB)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    block_size = 16
    n = block_size - (len(data) % block_size)
    padded = data + bytes([n] * n)
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(padded) + enc.finalize()


def _aes_ecb_padded_size(plaintext_len: int) -> int:
    """Return AES-128-ECB ciphertext length for given plaintext length."""
    return ((plaintext_len + 16) // 16) * 16


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
        logger.info("[WeChat] sending reply: chat_id=%s, text_len=%d, attachments=%d", msg.chat_id, len(plain_text), len(msg.attachments))

        # Send typing cancel after reply (fire-and-forget)
        typing_ticket = self._typing_ticket_cache.get(msg.chat_id, "")

        last_exc: Exception | None = None
        try:
            # Send text message
            for attempt in range(_max_retries):
                try:
                    await self._send_text(
                        to_user_id=msg.chat_id,
                        text=plain_text,
                        context_token=context_token,
                    )
                    break
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
            else:
                logger.error("[WeChat] send failed after %d attempts: %s", _max_retries, last_exc)
                raise last_exc  # type: ignore[misc]

            # Send attachments (images and files)
            for attachment in msg.attachments:
                try:
                    if attachment.is_image:
                        await self._send_image(
                            to_user_id=msg.chat_id,
                            image_path=attachment.actual_path,
                            context_token=context_token,
                        )
                    else:
                        # Send as file attachment (PDF, ZIP, DOC, etc.)
                        await self._send_file(
                            to_user_id=msg.chat_id,
                            file_path=attachment.actual_path,
                            context_token=context_token,
                            filename=attachment.filename,
                        )
                except Exception as exc:
                    logger.warning("[WeChat] failed to send attachment %s: %s", attachment.filename, exc)
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

    async def _get_upload_url(self, to_user_id: str, raw_data: bytes, aes_key_hex: str, media_type: int = _UPLOAD_MEDIA_IMAGE) -> tuple[str, str] | None:
        """Call /ilink/bot/getuploadurl to get CDN upload parameters.

        Returns (upload_param, filekey) or None on failure.
        Mirrors cc-connect getUploadURL in client.go.
        """
        raw_size = len(raw_data)
        padded_size = _aes_ecb_padded_size(raw_size)
        file_key = os.urandom(16).hex()
        raw_md5 = hashlib.md5(raw_data).hexdigest()

        try:
            resp = await self._api_post(
                "/ilink/bot/getuploadurl",
                {
                    "filekey": file_key,
                    "media_type": media_type,
                    "to_user_id": to_user_id,
                    "rawsize": raw_size,
                    "rawfilemd5": raw_md5,
                    "filesize": padded_size,
                    "no_need_thumb": True,
                    "aeskey": aes_key_hex,
                    "base_info": _BASE_INFO,
                },
            )
            upload_param = resp.get("upload_param", "")
            if not upload_param:
                logger.warning("[WeChat] getuploadurl returned empty upload_param: %s", resp)
                return None
            return upload_param, file_key
        except Exception as exc:
            logger.warning("[WeChat] getuploadurl failed: %s", exc)
            return None

    async def _upload_to_cdn(self, to_user_id: str, data: bytes, media_type: int) -> tuple[str, bytes, int, int] | None:
        """Upload data to WeChat CDN with AES-128-ECB encryption.

        Shared by _send_image(), _send_file().
        Mirrors cc-connect uploadToWeixinCDN.

        Returns (download_param, aes_key, cipher_size, raw_size) or None on failure.
        """
        aes_key = os.urandom(16)
        result = await self._get_upload_url(to_user_id, data, aes_key.hex(), media_type)
        if result is None:
            return None
        upload_param, file_key = result

        ciphertext = _aes_ecb_encrypt(data, aes_key)
        cdn_upload_url = (
            f"{_CDN_BASE_URL}/upload"
            f"?encrypted_query_param={url_quote(upload_param)}"
            f"&filekey={url_quote(file_key)}"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            upload_resp = await client.post(
                cdn_upload_url,
                content=ciphertext,
                headers={"Content-Type": "application/octet-stream"},
            )
            upload_resp.raise_for_status()

        download_param = upload_resp.headers.get("x-encrypted-param", "")
        if not download_param:
            logger.error("[WeChat] CDN upload response missing x-encrypted-param header")
            return None
        return download_param, aes_key, len(ciphertext), len(data)

    async def _send_image(self, to_user_id: str, image_path: Path, context_token: str) -> None:
        """Send an image to a WeChat user via CDN upload.

        Mirrors cc-connect SendImage / weixin-agent-sdk sendImageMessageWeixin.
        image_item.mid_size = ciphertext size (NOT raw size).
        """
        logger.info("[WeChat] sending image via CDN: to=%s, path=%s", to_user_id, image_path)
        try:
            data = image_path.read_bytes()
            if len(data) > 10 * 1024 * 1024:
                logger.warning("[WeChat] image too large (%d bytes), skipping: %s", len(data), image_path)
                return
            ref = await self._upload_to_cdn(to_user_id, data, _UPLOAD_MEDIA_IMAGE)
            if ref is None:
                logger.error("[WeChat] CDN upload failed for image %s", image_path.name)
                return
            download_param, aes_key, cipher_size, _ = ref
            await self._api_post(
                "/ilink/bot/sendmessage",
                {
                    "msg": {
                        "from_user_id": "",
                        "to_user_id": to_user_id,
                        "client_id": str(uuid.uuid4()),
                        "message_type": _BOT_MESSAGE_TYPE,
                        "message_state": _MSG_STATE_FINISH,
                        "item_list": [
                            {
                                "type": _IMAGE_TYPE,
                                "image_item": {
                                    # aeskey (hex) at top level — WeChat client's preferred field
                                    "aeskey": aes_key.hex(),
                                    "media": {
                                        "encrypt_query_param": download_param,
                                        # base64(hex_string) mirrors what WeChat server sends us
                                        "aes_key": base64.b64encode(aes_key.hex().encode()).decode(),
                                        "encrypt_type": 1,
                                    },
                                    "mid_size": cipher_size,
                                },
                            }
                        ],
                        "context_token": context_token,
                    },
                    "base_info": _BASE_INFO,
                },
            )
            logger.info("[WeChat] image sent: %s (%d bytes)", image_path.name, len(data))
        except Exception:
            logger.exception("[WeChat] failed to send image %s", image_path.name)

    async def _send_file(self, to_user_id: str, file_path: Path, context_token: str, filename: str | None = None) -> None:
        """Send a file attachment to a WeChat user via CDN upload.

        Mirrors cc-connect SendFile / weixin-agent-sdk sendFileMessageWeixin.
        file_item.len = raw (plaintext) size as string (NOT cipher size).
        """
        file_name = filename or file_path.name
        logger.info("[WeChat] sending file via CDN: to=%s, path=%s, name=%s", to_user_id, file_path, file_name)
        try:
            data = file_path.read_bytes()
            if len(data) > 100 * 1024 * 1024:
                logger.warning("[WeChat] file too large (%d bytes), skipping: %s", len(data), file_path)
                return
            ref = await self._upload_to_cdn(to_user_id, data, _UPLOAD_MEDIA_FILE)
            if ref is None:
                logger.error("[WeChat] CDN upload failed for file %s", file_name)
                return
            download_param, aes_key, _, raw_size = ref
            await self._api_post(
                "/ilink/bot/sendmessage",
                {
                    "msg": {
                        "from_user_id": "",
                        "to_user_id": to_user_id,
                        "client_id": str(uuid.uuid4()),
                        "message_type": _BOT_MESSAGE_TYPE,
                        "message_state": _MSG_STATE_FINISH,
                        "item_list": [
                            {
                                "type": _FILE_TYPE,
                                "file_item": {
                                    "media": {
                                        "encrypt_query_param": download_param,
                                        "aes_key": base64.b64encode(aes_key).decode(),
                                        "encrypt_type": 1,
                                    },
                                    "file_name": file_name,
                                    "len": str(raw_size),  # raw plaintext size, not cipher
                                },
                            }
                        ],
                        "context_token": context_token,
                    },
                    "base_info": _BASE_INFO,
                },
            )
            logger.info("[WeChat] file sent: %s (%d bytes)", file_name, raw_size)
        except Exception:
            logger.exception("[WeChat] failed to send file %s", file_name)

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

    async def _download_weixin_image(self, item: dict[str, Any]) -> bytes | None:
        """Download image from Weixin CDN and decrypt if needed.

        Args:
            item: The image item from message's item_list.

        Returns:
            Image bytes or None if download fails.
        """
        image_item = item.get("image_item") or {}
        media = image_item.get("media") or {}
        encrypt_query_param = media.get("encrypt_query_param")
        aes_key = media.get("aes_key")
        # Alternative: aeskey in hex format
        aeskey_hex = image_item.get("aeskey")

        if not encrypt_query_param:
            logger.warning("[WeChat] no encrypt_query_param for image")
            return None

        try:
            # Build CDN download URL — mirrors cc-connect buildCdnDownloadURL
            # CDN base: https://novac2c.cdn.weixin.qq.com/c2c (NOT cdn.weixin.qq.com)
            # Parameters must be URL-encoded (may contain '+', '/', '=' etc.)
            cdn_url = f"{_CDN_BASE_URL}/download?encrypted_query_param={url_quote(encrypt_query_param)}"

            # Download from CDN
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(cdn_url)
                resp.raise_for_status()
                data = resp.content

            # Resolve AES key: prefer aeskey (hex) from image_item, fallback to media.aes_key (base64)
            # Mirrors cc-connect parseAesKey logic
            key_bytes: bytes | None = None
            if aeskey_hex and len(aeskey_hex) == 32:
                # image_item.aeskey — raw hex string representing 16 bytes
                key_bytes = bytes.fromhex(aeskey_hex)
            elif aes_key:
                # image_item.media.aes_key — base64(raw 16 bytes) OR base64(32-char hex ASCII)
                try:
                    decoded = base64.b64decode(aes_key)
                    if len(decoded) == 16:
                        key_bytes = decoded
                    elif len(decoded) == 32:
                        # base64 wraps a 32-char hex string
                        key_bytes = bytes.fromhex(decoded.decode("ascii"))
                except Exception as e:
                    logger.warning("[WeChat] failed to parse aes_key: %s", e)

            if key_bytes and len(key_bytes) == 16:
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

                cipher = Cipher(algorithms.AES(key_bytes), modes.ECB())
                decryptor = cipher.decryptor()
                decrypted = decryptor.update(data) + decryptor.finalize()
                # Remove PKCS7 padding
                if decrypted:
                    padding_len = decrypted[-1]
                    if 1 <= padding_len <= 16 and len(decrypted) >= padding_len:
                        decrypted = decrypted[:-padding_len]
                return decrypted
            else:
                logger.warning("[WeChat] no valid AES key found, returning raw CDN data")

            # Return as-is if no decryption key available
            return data
        except Exception:
            logger.exception("[WeChat] error downloading/decrypting image")
            return None

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """Process a single update from ilink getupdates."""
        try:
            # Skip messages sent by the bot itself
            if update.get("message_type") == _BOT_MESSAGE_TYPE:
                return

            from_user_id = update.get("from_user_id", "")
            context_token = update.get("context_token", "")
            item_list = update.get("item_list") or []

            # Check for image messages
            image_data = None
            image_filename = None
            text = ""

            for item in item_list:
                item_type = item.get("type")
                logger.info("[WeChat] item type: %s (expected image=%s)", item_type, _IMAGE_TYPE)
                if item_type == _IMAGE_TYPE:
                    # Image message - download and process
                    logger.info("[WeChat] received image from user_id=%s, item=%s", from_user_id, item)
                    image_data = await self._download_weixin_image(item)
                    if image_data:
                        image_filename = f"weixin_{from_user_id}_{int(time.time())}.jpg"
                        logger.info("[WeChat] image downloaded: %s (%d bytes)", image_filename, len(image_data))
                    else:
                        logger.warning("[WeChat] image download failed for user_id=%s", from_user_id)
                    # Continue to check for text in same message
                elif item_type == _TEXT_TYPE:
                    # Extract text
                    text_item = item.get("text_item") or {}
                    item_text = text_item.get("text", "").strip()
                    if item_text:
                        text = item_text

            # If no text extracted, try voice-to-text or fallback
            if not text:
                text = _body_from_item_list(item_list)

            logger.info("[WeChat] message from user_id=%s, has_image=%s, text=%r",
                       from_user_id, bool(image_data), text[:100] if text else "")

            if not text and not image_data:
                logger.debug("[WeChat] empty text and no image, ignoring")
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

            msg_type = InboundMessageType.COMMAND if (text and text.startswith("/")) else InboundMessageType.CHAT

            # Save image and inject path into text if available
            if image_data and image_filename:
                try:
                    from app.channels.store import ChannelStore
                    from deerflow.config.paths import get_paths

                    store = ChannelStore()
                    thread_id = store.get_thread_id("weixin", from_user_id, topic_id=from_user_id)

                    if thread_id:
                        paths = get_paths()
                        uploads_dir = paths.sandbox_uploads_dir(thread_id)
                        uploads_dir.mkdir(parents=True, exist_ok=True)

                        # Save image file
                        image_path = uploads_dir / image_filename
                        image_path.write_bytes(image_data)
                        logger.info("[WeChat] saved image to %s (%d bytes)", image_path, len(image_data))

                        # Inject image path into text
                        virtual_path = f"/mnt/user-data/uploads/{image_filename}"
                        if text:
                            text = f"{text}\n\n[图片: {virtual_path}]"
                        else:
                            text = f"[图片: {virtual_path}]"
                except Exception:
                    logger.exception("[WeChat] failed to save image")

            inbound = self._make_inbound(
                chat_id=from_user_id,
                user_id=from_user_id,
                text=text or "",  # Ensure text is not None
                msg_type=msg_type,
                thread_ts=context_token,
                metadata={"context_token": context_token},
            )
            # Each user gets a persistent DeerFlow thread
            inbound.topic_id = from_user_id

            await self.bus.publish_inbound(inbound)
        except Exception:
            logger.exception("[WeChat] error handling update: %s", update)
