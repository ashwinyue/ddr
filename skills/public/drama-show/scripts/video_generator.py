"""
视频生成器 — Seedance 路由
对应 BigBanana videoService.generateVideoVolcengineTask
支持图生视频（首帧驱动）
"""
from __future__ import annotations
import os
from pathlib import Path
from models import ScriptData, Shot
import api_client as api


def generate_all_videos(
    shots: list[Shot],
    script: ScriptData,
    output_dir: str,
    duration: int = 5,
    ratio: str = "16:9",
    video_model: str = api.DEFAULT_VIDEO_MODEL,
) -> list[Shot]:
    """为所有分镜生成视频"""
    videos_dir = Path(output_dir) / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🎬 视频生成: {len(shots)} 个分镜 (模型: {video_model})")
    for i, shot in enumerate(shots):
        if shot.video_path and os.path.exists(shot.video_path):
            print(f"   ⏭️  [{i+1}/{len(shots)}] {shot.id} 已存在，跳过")
            continue
        print(f"\n   [{i+1}/{len(shots)}] {shot.id}: {shot.action_summary[:50]}...")
        shots[i] = _generate_shot_video(
            shot, script, videos_dir, duration, ratio, video_model
        )
    return shots


def _generate_shot_video(
    shot: Shot,
    script: ScriptData,
    output_dir: Path,
    duration: int,
    ratio: str,
    video_model: str,
) -> Shot:
    """为单个分镜生成视频"""
    start_kf = shot.start_keyframe
    start_image_b64 = None

    # 优先使用生成的关键帧图像
    if start_kf and start_kf.image_path and os.path.exists(start_kf.image_path):
        start_image_b64 = api.image_path_to_b64(start_kf.image_path)
        print(f"   📷 使用关键帧参考图: {start_kf.image_path}")

    # 构建视频提示词（对齐 BigBanana sora2Chinese 模板）
    art_anchors = (
        script.art_direction.consistency_anchors
        if script.art_direction else script.style_prompt
    )
    video_prompt = _build_video_prompt(shot, script, art_anchors)

    save_path = str(output_dir / f"shot_{shot.id}.mp4")
    try:
        video_url = api.generate_video(
            prompt=video_prompt,
            start_image_b64=start_image_b64,
            model=video_model,
            duration=duration,
            ratio=ratio,
        )
        api.download_file(video_url, save_path)
        shot.video_path = save_path
        print(f"   ✅ 视频已生成: {save_path}")
    except Exception as e:
        print(f"   ❌ 视频生成失败 [{shot.id}]: {e}")

    return shot


def _build_video_prompt(shot: Shot, script: ScriptData, art_anchors: str) -> str:
    """
    构建视频提示词
    对应 BigBanana sora2Chinese 模板
    """
    dialogue_line = f"\n对话：{shot.dialogue}" if shot.dialogue else ""
    return f"""基于提供的参考图片生成视频。{dialogue_line}

动作描述：{shot.action_summary}
视觉风格锚点：{art_anchors}

技术要求：
- 关键：视频必须从参考图的精确构图和画面内容开始，再自然发展后续动作
- 镜头运动：{shot.camera_movement}
- 景别：{shot.shot_size}
- 运动：确保动作流畅自然，避免突兀跳变或不连续
- 视觉风格：{script.style_prompt}，保持一致的光照与色调
- 细节：角色外观和场景环境需全程一致
- 禁止字幕及任何画面文字"""
