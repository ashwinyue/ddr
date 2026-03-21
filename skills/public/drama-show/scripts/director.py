#!/usr/bin/env python3
"""
drama-show 主导演 — 全流程编排 CLI
用法：
  python3 director.py generate --story "故事文本" --style "3D温馨动漫"
  python3 director.py generate --story-file story.txt --style "赛博朋克漫画"
  python3 director.py resume --project-dir ~/Desktop/drama_xxx/
"""
from __future__ import annotations
import os
import sys
import json
import argparse
import time
from pathlib import Path

# 添加脚本目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent))

from models import ScriptData
import api_client as api

# ──────────────────────────────────────────────
# 环境变量加载（复用 manga-drama 模式）
# ──────────────────────────────────────────────

def _load_env_file(path: Path):
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _load_env():
    candidates = [
        Path.cwd() / ".canghe-skills" / ".env",
        Path.home() / ".canghe-skills" / ".env",
    ]
    current = Path(__file__).parent
    for _ in range(10):
        env_file = current / ".env"
        if env_file.exists():
            candidates.append(env_file)
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    for p in candidates:
        _load_env_file(p)


# ──────────────────────────────────────────────
# 风格预设
# ──────────────────────────────────────────────

STYLE_PRESETS = {
    "3D温馨动漫": "3D animation style, warm and vibrant colors, soft lighting, high quality render, cinematic, Pixar-inspired",
    "国漫手绘": "Chinese manga style, hand-drawn, ink lines, watercolor palette, expressive characters, warm atmosphere",
    "日漫": "Japanese anime style, clean lines, vivid colors, expressive eyes, dynamic composition, high detail",
    "赛博朋克": "cyberpunk comic style, neon colors, dark atmosphere, gritty details, urban dystopia, dramatic lighting",
    "水墨国风": "traditional Chinese ink painting, brush strokes, minimal color, poetic composition, misty atmosphere",
    "欧美漫画": "Western comic book style, bold outlines, flat colors, dynamic poses, superhero aesthetics",
}


def _resolve_style_prompt(style: str) -> str:
    return STYLE_PRESETS.get(style, style)


# ──────────────────────────────────────────────
# 核心流程
# ──────────────────────────────────────────────

def run_full_pipeline(
    story_text: str,
    visual_style: str = "3D温馨动漫",
    output_dir: str = None,
    language: str = "zh",
    target_duration: int = 60,
    shot_duration: int = 5,
    video_ratio: str = "16:9",
    quality: str = "balanced",
    skip_assets: bool = False,
    skip_keyframes: bool = False,
    skip_videos: bool = False,
    skip_merge: bool = False,
    bgm_path: str = None,
    resume_project: str = None,
) -> str:
    """
    完整漫剧生成流水线

    Returns:
        成片路径
    """
    # 准备输出目录
    if output_dir is None:
        output_dir = str(Path.home() / "Desktop" / f"drama_show_{int(time.time())}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    progress_file = str(Path(output_dir) / "progress.json")
    style_prompt = _resolve_style_prompt(visual_style)

    print(f"\n{'='*60}")
    print(f"🎬 drama-show 导演台")
    print(f"{'='*60}")
    print(f"📁 输出目录: {output_dir}")
    print(f"🎨 视觉风格: {visual_style}")
    print(f"⏱️  目标时长: {target_duration}s | 每镜: {shot_duration}s")
    print()

    # ── 恢复进度 ──
    script = None
    if resume_project and Path(resume_project).exists():
        print("🔄 恢复上次进度...")
        import dataclasses
        with open(resume_project) as f:
            raw = json.load(f)
        script = _load_script_from_dict(raw)

    # ── Agent1+2: 解析剧本 ──
    if script is None:
        from script_parser import parse_and_enrich
        script = parse_and_enrich(
            story_text,
            visual_style=visual_style,
            style_prompt=style_prompt,
            language=language,
        )
        script.original_story = story_text  # 保存原文用于后续恢复
        script.save(progress_file)

    # ── Agent3: 生成分镜 ──
    if not script.shots:
        from shot_generator import generate_shot_list
        script.shots = generate_shot_list(
            script,
            target_duration=target_duration,
            shot_duration=shot_duration,
        )
        script.save(progress_file)

    # ── 优化关键帧 ──
    if not skip_keyframes:
        from keyframe_optimizer import optimize_all_keyframes
        script.shots = optimize_all_keyframes(script.shots, script)
        script.save(progress_file)

    # ── Phase02: 资产图像 ──
    if not skip_assets:
        from asset_generator import generate_all_assets, generate_shot_keyframes
        script = generate_all_assets(script, output_dir)
        script.save(progress_file)
        script.shots = generate_shot_keyframes(script.shots, script, output_dir)
        script.save(progress_file)

    # ── 视频生成 ──
    if not skip_videos:
        from video_generator import generate_all_videos
        script.shots = generate_all_videos(
            script.shots, script, output_dir,
            duration=shot_duration,
            ratio=video_ratio,
        )
        script.save(progress_file)

    # ── 合并成片 ──
    master_path = ""
    if not skip_merge:
        from video_merger import merge_videos
        master_path = merge_videos(
            script.shots,
            output_dir,
            output_name=f"{script.title or 'drama'}_master.mp4",
            quality=quality,
            add_bgm=bgm_path,
        )

    # ── 输出摘要 ──
    _print_summary(script, output_dir, master_path)
    return master_path


def _print_summary(script: ScriptData, output_dir: str, master_path: str):
    total_shots = len(script.shots)
    done_videos = sum(1 for s in script.shots if s.video_path and Path(s.video_path).exists())
    print(f"\n{'='*60}")
    print(f"✅ 漫剧生成完成!")
    print(f"{'='*60}")
    print(f"   标题: {script.title}")
    print(f"   角色: {len(script.characters)} 个")
    print(f"   场景: {len(script.scenes)} 个")
    print(f"   分镜: {total_shots} 个 ({done_videos} 个视频已生成)")
    if master_path:
        print(f"   成片: {master_path}")
    print(f"   目录: {output_dir}")
    print(f"{'='*60}\n")


def _load_script_from_dict(raw: dict) -> ScriptData:
    """从进度文件恢复 ScriptData"""
    from models import (
        ArtDirection, Character, Scene, Prop, StoryParagraph,
        Shot, Keyframe, ShotQualityAssessment
    )
    import dataclasses

    script = ScriptData(
        title=raw.get("title", ""),
        genre=raw.get("genre", ""),
        logline=raw.get("logline", ""),
        language=raw.get("language", "zh"),
        visual_style=raw.get("visual_style", ""),
        style_prompt=raw.get("style_prompt", ""),
    )
    if raw.get("art_direction"):
        script.art_direction = ArtDirection.from_dict(raw["art_direction"])
    script.characters = [Character.from_dict(c) for c in raw.get("characters", [])]
    script.scenes = [Scene.from_dict(s) for s in raw.get("scenes", [])]
    script.props = [Prop.from_dict(p) for p in raw.get("props", [])]
    script.story_paragraphs = [StoryParagraph.from_dict(p) for p in raw.get("story_paragraphs", [])]

    shots = []
    for sd in raw.get("shots", []):
        shot = Shot.from_dict(sd)
        shot.video_path = sd.get("video_path")
        for kfd in sd.get("keyframes", []):
            kf = next((k for k in shot.keyframes if k.id == kfd.get("id")), None)
            if kf:
                kf.image_path = kfd.get("image_path")
        shots.append(shot)
    script.shots = shots
    return script


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

def main():
    _load_env()

    parser = argparse.ArgumentParser(
        description="drama-show — 专业漫剧生成导演台",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
风格预设:
  3D温馨动漫 / 国漫手绘 / 日漫 / 赛博朋克 / 水墨国风 / 欧美漫画

示例:
  # 快速生成
  python3 director.py generate \\
    --story "狐狸和小兔的奇幻冒险" \\
    --style "3D温馨动漫" \\
    --duration 60

  # 从文件读取故事
  python3 director.py generate \\
    --story-file /path/to/story.txt \\
    --style "国漫手绘" \\
    --output ~/Desktop/my_drama

  # 恢复中断的生成
  python3 director.py resume \\
    --project-dir ~/Desktop/drama_show_xxx/
        """
    )
    sub = parser.add_subparsers(dest="command")

    # generate
    p_gen = sub.add_parser("generate", help="从故事文本生成漫剧")
    story_grp = p_gen.add_mutually_exclusive_group(required=True)
    story_grp.add_argument("--story", help="故事文本")
    story_grp.add_argument("--story-file", help="故事文本文件路径")
    p_gen.add_argument("--style", default="3D温馨动漫",
                       help=f"视觉风格，可选: {' / '.join(STYLE_PRESETS.keys())} 或自定义")
    p_gen.add_argument("--output", "-o", default=None, help="输出目录")
    p_gen.add_argument("--duration", "-d", type=int, default=60, help="目标时长（秒，默认60）")
    p_gen.add_argument("--shot-duration", type=int, default=5, help="每个分镜时长（秒，默认5）")
    p_gen.add_argument("--ratio", default="16:9", choices=["16:9", "9:16", "1:1"], help="视频比例")
    p_gen.add_argument("--quality", default="balanced", choices=["economy", "balanced", "pro"])
    p_gen.add_argument("--language", default="zh", help="语言（zh/en）")
    p_gen.add_argument("--bgm", default=None, help="背景音乐文件路径")
    p_gen.add_argument("--skip-assets", action="store_true", help="跳过资产图像生成")
    p_gen.add_argument("--skip-keyframes", action="store_true", help="跳过关键帧优化")
    p_gen.add_argument("--skip-videos", action="store_true", help="跳过视频生成（只生成脚本和图像）")
    p_gen.add_argument("--skip-merge", action="store_true", help="跳过成片合并")

    # resume
    p_res = sub.add_parser("resume", help="恢复中断的生成")
    p_res.add_argument("--project-dir", required=True, help="之前的输出目录")
    p_res.add_argument("--skip-assets", action="store_true")
    p_res.add_argument("--skip-keyframes", action="store_true")
    p_res.add_argument("--skip-videos", action="store_true")
    p_res.add_argument("--skip-merge", action="store_true")
    p_res.add_argument("--quality", default="balanced", choices=["economy", "balanced", "pro"])
    p_res.add_argument("--bgm", default=None)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 验证 API Key
    try:
        api._get_api_key()
    except EnvironmentError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.command == "generate":
            story_text = args.story
            if args.story_file:
                with open(args.story_file, encoding="utf-8") as f:
                    story_text = f.read()

            run_full_pipeline(
                story_text=story_text,
                visual_style=args.style,
                output_dir=args.output,
                language=args.language,
                target_duration=args.duration,
                shot_duration=args.shot_duration,
                video_ratio=args.ratio,
                quality=args.quality,
                skip_assets=args.skip_assets,
                skip_keyframes=args.skip_keyframes,
                skip_videos=args.skip_videos,
                skip_merge=args.skip_merge,
                bgm_path=args.bgm,
            )

        elif args.command == "resume":
            progress_file = str(Path(args.project_dir) / "progress.json")
            if not Path(progress_file).exists():
                print(f"❌ 未找到进度文件: {progress_file}", file=sys.stderr)
                sys.exit(1)

            with open(progress_file, encoding="utf-8") as f:
                raw = json.load(f)
            story_text = raw.get("original_story") or raw.get("logline", "") or "（从进度文件恢复）"

            run_full_pipeline(
                story_text=story_text,
                output_dir=args.project_dir,
                skip_assets=args.skip_assets,
                skip_keyframes=args.skip_keyframes,
                skip_videos=args.skip_videos,
                skip_merge=args.skip_merge,
                quality=args.quality,
                bgm_path=args.bgm,
                resume_project=progress_file,
            )

    except KeyboardInterrupt:
        print("\n\n⚠️  已中断。可用 resume 命令恢复进度。")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
