"""
视频合并器 — ffmpeg 实现
对应 BigBanana exportService.stitchVideoBlobsToMaster
将所有分镜视频合并为完整成片
"""
from __future__ import annotations
import subprocess
import shutil
from pathlib import Path
from models import Shot

QUALITY_PRESETS = {
    "economy":  {"fps": 24, "crf": 28, "preset": "fast"},
    "balanced": {"fps": 30, "crf": 23, "preset": "medium"},
    "pro":      {"fps": 30, "crf": 18, "preset": "slow"},
}


def merge_videos(
    shots: list[Shot],
    output_dir: str,
    output_name: str = "master.mp4",
    quality: str = "balanced",
    add_bgm: str = None,
) -> str:
    """
    将所有分镜视频合并为成片

    Args:
        shots: 已生成视频的分镜列表
        output_dir: 输出目录
        output_name: 成片文件名
        quality: economy / balanced / pro
        add_bgm: 可选背景音乐路径

    Returns:
        成片路径
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 未安装，请运行: brew install ffmpeg")

    video_paths = [s.video_path for s in shots if s.video_path and Path(s.video_path).exists()]
    if not video_paths:
        raise RuntimeError("没有可合并的视频文件")

    output_path = Path(output_dir) / output_name
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])

    print(f"\n🎞️  合并 {len(video_paths)} 个视频片段...")
    print(f"   质量预设: {quality} (fps={preset['fps']}, crf={preset['crf']})")

    # 统一转码所有片段（确保分辨率/帧率一致）
    normalized_dir = Path(output_dir) / "_normalized"
    normalized_dir.mkdir(exist_ok=True)
    normalized_paths = []

    for i, vp in enumerate(video_paths):
        norm_path = str(normalized_dir / f"norm_{i:03d}.mp4")
        _normalize_video(vp, norm_path, fps=preset["fps"])
        normalized_paths.append(norm_path)
        print(f"   🔄 标准化 [{i+1}/{len(video_paths)}]: {Path(vp).name}")

    # 生成 concat list 文件
    concat_file = str(Path(output_dir) / "_concat.txt")
    with open(concat_file, "w") as f:
        for p in normalized_paths:
            f.write(f"file '{p}'\n")

    # 合并
    merged_path = str(Path(output_dir) / "_merged.mp4")
    _concat_videos(concat_file, merged_path)

    # 加背景音乐（可选）
    if add_bgm and Path(add_bgm).exists():
        print(f"   🎵 混合背景音乐: {add_bgm}")
        _mix_bgm(merged_path, add_bgm, str(output_path), preset)
    else:
        # 最终编码
        _encode_final(merged_path, str(output_path), preset)

    # 清理临时文件
    import shutil as sh
    sh.rmtree(str(normalized_dir), ignore_errors=True)
    for tmp in [concat_file, merged_path]:
        Path(tmp).unlink(missing_ok=True)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"\n   ✅ 成片完成: {output_path}")
    print(f"   📦 文件大小: {size_mb:.1f} MB")
    return str(output_path)


def _normalize_video(input_path: str, output_path: str, fps: int = 30):
    """统一分辨率和帧率"""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an",  # 移除音频，后续统一处理
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"视频标准化失败: {result.stderr[-500:]}")


def _concat_videos(concat_file: str, output_path: str):
    """无损拼接"""
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"视频拼接失败: {result.stderr[-500:]}")


def _encode_final(input_path: str, output_path: str, preset: dict):
    """最终编码输出"""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264",
        "-preset", preset["preset"],
        "-crf", str(preset["crf"]),
        "-r", str(preset["fps"]),
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"最终编码失败: {result.stderr[-500:]}")


def _mix_bgm(video_path: str, bgm_path: str, output_path: str, preset: dict):
    """混合背景音乐，视频时长优先"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", bgm_path,
        "-filter_complex",
        "[1:a]aloop=loop=-1:size=2e+09[bgm];[bgm]volume=0.3[bgm_v];[bgm_v]atrim=duration={dur}[bgm_t]".format(dur=9999),
        "-map", "0:v", "-map", "[bgm_t]",
        "-c:v", "libx264", "-preset", preset["preset"], "-crf", str(preset["crf"]),
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # 降级：不加 BGM
        print(f"   ⚠️  BGM 混合失败，输出无配乐版本")
        _encode_final(video_path, output_path, preset)
