"""
资产图像生成器
生成角色定妆图、场景概念图、道具图、关键帧图
对应 BigBanana visualService.generateImage + Phase02 资产生成
"""
from __future__ import annotations
import os
from pathlib import Path
from models import ScriptData, Character, Scene, Prop, Shot
import api_client as api


def generate_all_assets(script: ScriptData, output_dir: str) -> ScriptData:
    """生成所有资产图（角色/场景/道具）"""
    assets_dir = Path(output_dir) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    print("\n🖼️  Phase02: 生成资产图像...")

    # 角色定妆图
    for char in script.characters:
        if not char.reference_image_path:
            char.reference_image_path = _generate_character_image(char, script, assets_dir)

    # 场景概念图
    for scene in script.scenes:
        if not scene.reference_image_path:
            scene.reference_image_path = _generate_scene_image(scene, script, assets_dir)

    # 道具图
    for prop in script.props:
        if not prop.reference_image_path:
            prop.reference_image_path = _generate_prop_image(prop, script, assets_dir)

    return script


def generate_shot_keyframes(shots: list[Shot], script: ScriptData, output_dir: str) -> list[Shot]:
    """为每个分镜生成关键帧图像"""
    frames_dir = Path(output_dir) / "keyframes"
    frames_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🎨 Phase03: 生成 {len(shots)} 个分镜关键帧...")
    for i, shot in enumerate(shots):
        print(f"\n   [{i+1}/{len(shots)}] {shot.id}: {shot.action_summary[:50]}...")
        shots[i] = _generate_shot_keyframe_images(shot, script, frames_dir)
    return shots


def _generate_character_image(char: Character, script: ScriptData, output_dir: Path) -> str:
    """生成角色定妆参考图"""
    print(f"   👤 生成角色图: {char.name}")
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""

    prompt = f"""{art_block}

Character Reference Sheet: {char.name}
{char.visual_prompt}

Full body portrait, character design reference sheet, neutral background, {script.style_prompt}
Show full outfit and facial features clearly. Consistent with art direction above."""

    save_path = str(output_dir / f"char_{char.id}.png")
    return _generate_and_save_image(prompt, save_path)


def _generate_scene_image(scene: Scene, script: ScriptData, output_dir: Path) -> str:
    """生成场景概念图（严禁人物）"""
    print(f"   🏞️  生成场景图: {scene.location}")
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""

    prompt = f"""{art_block}

Scene Concept Art: {scene.location}
{scene.visual_prompt}

⚠️ ABSOLUTELY NO PEOPLE, characters, or figures. Environment only.
Establish lighting and mood for this scene. {script.style_prompt}"""

    save_path = str(output_dir / f"scene_{scene.id}.png")
    return _generate_and_save_image(prompt, save_path)


def _generate_prop_image(prop: Prop, script: ScriptData, output_dir: Path) -> str:
    """生成道具参考图"""
    print(f"   🔧 生成道具图: {prop.name}")
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""

    prompt = f"""{art_block}

Prop Design: {prop.name} ({prop.category})
{prop.visual_prompt}

Product shot, studio lighting, neutral background, no people or hands. {script.style_prompt}"""

    save_path = str(output_dir / f"prop_{prop.id}.png")
    return _generate_and_save_image(prompt, save_path)


def _generate_shot_keyframe_images(shot: Shot, script: ScriptData, output_dir: Path) -> Shot:
    """为分镜的起始关键帧生成图像"""
    scene = script.get_scene(shot.scene_id)
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""

    # 收集参考图（场景 + 角色）
    reference_b64s = []
    if scene and scene.reference_image_path and os.path.exists(scene.reference_image_path):
        reference_b64s.append(api.image_path_to_b64(scene.reference_image_path))

    for cid in shot.characters[:2]:  # 最多2个角色参考图
        char = script.get_character(cid)
        if char and char.reference_image_path and os.path.exists(char.reference_image_path):
            reference_b64s.append(api.image_path_to_b64(char.reference_image_path))

    # 生成起始帧
    start_kf = shot.start_keyframe
    if start_kf and not start_kf.image_path:
        ref_instruction = (
            "Use provided reference images for scene environment and character appearance consistency."
            if reference_b64s else ""
        )
        prompt = f"""{art_block}

{ref_instruction}

Shot Keyframe: {shot.shot_size} | {shot.camera_movement}
Action: {shot.action_summary}
Visual Description: {start_kf.visual_prompt}

Generate this exact frame in {script.visual_style} style. {script.style_prompt}
Cinematic composition, maintain character consistency with references."""

        save_path = str(output_dir / f"kf_{shot.id}_start.png")
        start_kf.image_path = _generate_and_save_image(
            prompt, save_path,
            reference_images=reference_b64s if reference_b64s else None
        )
        print(f"   ✅ 起始帧: {save_path}")

    return shot


def _generate_and_save_image(
    prompt: str,
    save_path: str,
    reference_images: list[str] = None,
) -> str:
    """调用图像生成 API 并保存文件"""
    try:
        url = api.generate_image(prompt, reference_images=reference_images)
        if not url:
            raise RuntimeError("API 未返回有效 URL")
        api.download_file(url, save_path)
        return save_path
    except Exception as e:
        print(f"   ⚠️  图像生成失败: {e}")
        return ""
