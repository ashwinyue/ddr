"""
ARK API 统一客户端
支持：Chat Completions / 图像生成 / Seedance 视频生成
"""
from __future__ import annotations
import os
import json
import time
import base64
import ssl
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_CHAT_MODEL = "doubao-seed-2-0-pro-260215"
DEFAULT_IMAGE_MODEL = "doubao-seedream-5-0-260128"
DEFAULT_VIDEO_MODEL = "doubao-seedance-1-5-pro-251215"

_ssl_ctx = ssl.create_default_context()


def _get_api_key() -> str:
    key = os.environ.get("ARK_API_KEY", "")
    if not key:
        raise EnvironmentError("ARK_API_KEY 未设置，请在 .env 中配置")
    return key


def _post(endpoint: str, body: dict, timeout: int = 120) -> dict:
    """发送 POST 请求，带重试"""
    url = f"{BASE_URL}{endpoint}"
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            if attempt < 2 and e.code in (429, 500, 502, 503):
                wait = 2 ** attempt * 3
                print(f"   ⚠️  HTTP {e.code}，{wait}s 后重试...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"API 请求失败 [{e.code}]: {body_text}") from e
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt * 2)
                continue
            raise
    raise RuntimeError("API 请求多次失败")


def _get(endpoint: str, timeout: int = 30) -> dict:
    url = f"{BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {_get_api_key()}"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ─────────────────────────────────────────────
# Chat Completions
# ─────────────────────────────────────────────

def chat(
    prompt: str,
    model: str = DEFAULT_CHAT_MODEL,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 8192,
    json_mode: bool = False,
) -> str:
    """调用 Chat Completions，返回文本内容"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    result = _post("/chat/completions", body, timeout=600)
    return result["choices"][0]["message"]["content"]


def chat_json(
    prompt: str,
    model: str = DEFAULT_CHAT_MODEL,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 8192,
) -> dict:
    """调用 Chat Completions，解析并返回 JSON"""
    text = chat(prompt, model=model, system=system,
                temperature=temperature, max_tokens=max_tokens, json_mode=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试从代码块中提取 JSON
        import re
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if m:
            return json.loads(m.group(1))
        raise RuntimeError(f"LLM 返回内容无法解析为 JSON:\n{text[:500]}")


# ─────────────────────────────────────────────
# 图像生成
# ─────────────────────────────────────────────

def generate_image(
    prompt: str,
    model: str = DEFAULT_IMAGE_MODEL,
    size: str = "2K",
    reference_images: list[str] = None,   # base64 列表
) -> str:
    """生成图像，返回图像 URL"""
    body: dict = {
        "model": model,
        "prompt": _truncate_prompt(prompt, 4000),
        "response_format": "url",
        "size": size,
        "watermark": False,
    }
    if reference_images:
        body["image"] = reference_images[:4]  # 最多4张参考图

    result = _post("/images/generations", body, timeout=120)

    # 提取 URL（兼容多种返回格式）
    data = result.get("data") or []
    if data:
        item = data[0]
        return item.get("url") or item.get("b64_json") or ""
    raise RuntimeError(f"图像生成返回格式异常: {result}")


def _truncate_prompt(prompt: str, max_chars: int) -> str:
    if len(prompt) <= max_chars:
        return prompt
    return prompt[:max_chars - 3] + "..."


# ─────────────────────────────────────────────
# Seedance 视频生成
# ─────────────────────────────────────────────

def generate_video(
    prompt: str,
    start_image_b64: str = None,
    model: str = DEFAULT_VIDEO_MODEL,
    duration: int = 5,
    ratio: str = "16:9",
) -> str:
    """
    调用 Seedance 生成视频，轮询等待完成。
    Returns: 视频 URL
    """
    content = []
    if start_image_b64:
        ext = "png" if start_image_b64.startswith("iVBOR") else "jpeg"
        img_url = f"data:image/{ext};base64,{start_image_b64}"
        content.append({"type": "image_url", "image_url": {"url": img_url}})
        ratio_val = "adaptive"
    else:
        ratio_val = ratio

    content.append({"type": "text", "text": prompt})

    body = {
        "model": model,
        "content": content,
        "ratio": ratio_val,
        "duration": duration,
        "watermark": False,
    }

    result = _post("/contents/generations/tasks", body, timeout=30)
    task_id = result.get("id")
    if not task_id:
        raise RuntimeError(f"创建视频任务失败: {result}")
    print(f"   🎬 任务已创建: {task_id}")

    return _poll_video_task(task_id)


def _poll_video_task(task_id: str, max_wait: int = 1200) -> str:
    """轮询视频任务，返回视频 URL"""
    elapsed = 0
    interval = 10
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        result = _get(f"/contents/generations/tasks/{task_id}", timeout=30)
        status = result.get("status", "")
        if status in ("succeeded", "completed", "success", "done"):
            # 多路径提取 video_url
            for path in [
                ("content", "video_url"), ("content", "videoUrl"),
                ("data", "content", "video_url"),
                ("result", "video_url"), ("output", "video_url"),
                ("video_url",), ("url",),
            ]:
                obj = result
                for key in path:
                    obj = obj.get(key) if isinstance(obj, dict) else None
                    if obj is None:
                        break
                if isinstance(obj, str) and obj:
                    return obj
            raise RuntimeError(f"视频生成成功但无法提取 URL: {result}")
        elif status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"视频生成失败: {result}")
        else:
            print(f"   ⏳ {status}... ({elapsed}s)", end="\r", flush=True)
    raise RuntimeError(f"视频生成超时 ({max_wait}s)")


def download_file(url: str, save_path: str) -> str:
    """下载文件到本地，返回保存路径"""
    req = urllib.request.Request(url, headers={"User-Agent": "drama-show/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        with open(save_path, "wb") as f:
            f.write(resp.read())
    return save_path


def image_path_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")
