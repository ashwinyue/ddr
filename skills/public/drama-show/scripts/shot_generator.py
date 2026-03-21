"""
Agent3: 分镜生成 + 5维质量评估 + 自动修复
对应 BigBanana scriptService.generateShotList + shotService 质量评估
"""
from __future__ import annotations
import json
import math
from models import ScriptData, Shot, Keyframe, ShotQualityAssessment
import api_client as api

CAMERA_MOVEMENTS = (
    "Static | Push In | Pull Out | Pan Left | Pan Right | "
    "Tilt Up | Tilt Down | Tracking | Orbit/Arc | Handheld"
)
SHOT_SIZES = "Extreme Long | Long | Wide | Medium | Close-Up | Extreme Close-Up"


def generate_shot_list(
    script: ScriptData,
    target_duration: int = 60,
    shot_duration: int = 5,
) -> list[Shot]:
    """
    Agent3: 逐场景生成分镜列表
    target_duration: 目标总时长（秒）
    shot_duration: 每个分镜时长（秒）
    """
    print(f"\n🎬 Agent3: 生成分镜列表（目标时长: {target_duration}s）...")
    total_shots_needed = max(1, math.ceil(target_duration / shot_duration))
    shots_per_scene = max(1, math.ceil(total_shots_needed / max(1, len(script.scenes))))

    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""
    chars_json = json.dumps(
        [{"id": c.id, "name": c.name, "gender": c.gender, "personality": c.personality}
         for c in script.characters],
        ensure_ascii=False
    )
    props_json = json.dumps(
        [{"id": p.id, "name": p.name, "category": p.category}
         for p in script.props],
        ensure_ascii=False
    )

    all_shots: list[Shot] = []
    for idx, scene in enumerate(script.scenes):
        scene_paragraphs = [
            p.text for p in script.story_paragraphs if p.scene_ref_id == scene.id
        ]
        scene_action = " ".join(scene_paragraphs) if scene_paragraphs else scene.atmosphere

        shots = _generate_scene_shots(
            script=script,
            scene_idx=idx + 1,
            scene=scene,
            scene_action=scene_action,
            shots_needed=shots_per_scene,
            shot_duration=shot_duration,
            total_shots_needed=total_shots_needed,
            art_block=art_block,
            chars_json=chars_json,
            props_json=props_json,
        )
        all_shots.extend(shots)
        print(f"   ✅ 场景 [{scene.id}] 生成 {len(shots)} 个分镜")

    # 质量评估 + 自动修复
    all_shots = _apply_quality_pipeline(all_shots, script)
    print(f"\n   🎯 分镜生成完成: 共 {len(all_shots)} 个")
    return all_shots


def _generate_scene_shots(
    script: ScriptData,
    scene_idx: int,
    scene,
    scene_action: str,
    shots_needed: int,
    shot_duration: int,
    total_shots_needed: int,
    art_block: str,
    chars_json: str,
    props_json: str,
) -> list[Shot]:
    prompt = f"""Act as a professional cinematographer. Generate a detailed shot list for Scene {scene_idx}.
Language: {script.language}

IMPORTANT VISUAL STYLE: {script.style_prompt}
All 'visualPrompt' fields MUST describe shots in "{script.visual_style}" style.
{art_block}

Scene Details:
- Location: {scene.location}
- Time: {scene.time}
- Atmosphere: {scene.atmosphere}
- Scene Action: "{scene_action}"

Context:
- Genre: {script.genre}
- Visual Style: {script.visual_style}
- Target Duration: {total_shots_needed * shot_duration}s total
- Active Video Model: doubao-seedance
- Shot Duration Baseline: {shot_duration}s per shot
- Shots for This Scene: EXACTLY {shots_needed}

Characters available: {chars_json}
Props available: {props_json}
Camera Movement Reference: {CAMERA_MOVEMENTS}
Shot Size Reference: {SHOT_SIZES}

Instructions:
1. Create EXACTLY {shots_needed} shots for this scene
2. Each shot represents ~{shot_duration} seconds
3. Use character IDs from the provided list only
4. Use prop IDs from the provided list only
5. Each shot MUST have a startKeyframe with a detailed visualPrompt (60-90 words)
6. Include an endKeyframe with different visual state showing motion result
7. visualPrompt must match the {script.visual_style} style
8. Vary shot sizes and camera movements for cinematic variety
9. dialogue: include character spoken lines if any (empty string if none)
10. actionSummary must be specific and vivid

Output ONLY valid JSON:
{{"shots":[{{
  "id":"s{scene_idx}_{{n}}",
  "sceneId":"{scene.id}",
  "actionSummary":"string",
  "dialogue":"string",
  "cameraMovement":"string",
  "shotSize":"string",
  "characters":["char_id"],
  "props":["prop_id"],
  "keyframes":[
    {{"id":"kf_s{scene_idx}_{{n}}_start","type":"start","visualPrompt":"detailed 60-90 word description"}},
    {{"id":"kf_s{scene_idx}_{{n}}_end","type":"end","visualPrompt":"detailed 60-90 word description"}}
  ]
}}]}}"""

    data = api.chat_json(prompt, temperature=0.7, max_tokens=8192)
    shots_raw = data.get("shots", [])

    # 数量纠偏
    if len(shots_raw) != shots_needed:
        shots_raw = _repair_shot_count(
            shots_raw, shots_needed, scene_idx, scene, scene_action, script, shot_duration
        )

    return [Shot.from_dict(s) for s in shots_raw]


def _repair_shot_count(
    current_shots: list,
    needed: int,
    scene_idx: int,
    scene,
    scene_action: str,
    script: ScriptData,
    shot_duration: int,
) -> list:
    actual = len(current_shots)
    print(f"   🔧 分镜数量纠偏: 当前 {actual} 个，需要 {needed} 个")
    prompt = f"""You returned {actual} shots for Scene {scene_idx}, but EXACTLY {needed} shots are required.

Scene: Location={scene.location} | Action={scene_action[:200]}

Requirements:
1. Return EXACTLY {needed} shots in JSON: {{"shots":[...]}}
2. Maintain narrative continuity with the provided shots
3. Each shot ~{shot_duration}s, actionSummary required, both keyframes required

Current shots for reference:
{json.dumps(current_shots[:3], ensure_ascii=False)}

Generate EXACTLY {needed} shots now."""
    data = api.chat_json(prompt, temperature=0.4, max_tokens=8192)
    return data.get("shots", current_shots)


# ─────────────────────────────────────────────
# 5 维质量评估
# ─────────────────────────────────────────────

def _assess_shot_quality(shot: Shot, all_shots: list[Shot], script: ScriptData) -> ShotQualityAssessment:
    score = 0.0
    issues = []

    # 1. 必填字段 (30%)
    field_score = 0.0
    if shot.action_summary and len(shot.action_summary) > 10:
        field_score += 45
    else:
        issues.append("actionSummary 缺失或过短")
    if shot.camera_movement:
        field_score += 30
    else:
        issues.append("cameraMovement 缺失")
    if shot.shot_size:
        field_score += 25
    else:
        issues.append("shotSize 缺失")
    score += field_score * 0.30

    # 2. 关键帧结构 (25%)
    kf_score = 0.0
    start_kf = shot.start_keyframe
    end_kf = shot.end_keyframe
    if start_kf:
        kf_score += 30
        if start_kf.visual_prompt and len(start_kf.visual_prompt) >= 60:
            kf_score += 20
        else:
            issues.append("起始帧 visualPrompt 过短")
    else:
        issues.append("缺少起始关键帧")
    if end_kf:
        kf_score += 30
        if end_kf.visual_prompt and len(end_kf.visual_prompt) >= 60:
            kf_score += 20
        else:
            issues.append("结束帧 visualPrompt 过短")
    score += kf_score * 0.25

    # 3. 资产引用合法性 (20%)
    valid_char_ids = {c.id for c in script.characters}
    valid_prop_ids = {p.id for p in script.props}
    asset_score = 100.0
    for cid in shot.characters:
        if cid not in valid_char_ids:
            asset_score -= 45
            issues.append(f"非法角色ID: {cid}")
    for pid in shot.props:
        if pid not in valid_prop_ids:
            asset_score -= 30
            issues.append(f"非法道具ID: {pid}")
    score += max(0, asset_score) * 0.20

    # 4. 相邻镜头差异度 (15%)
    shot_idx = next((i for i, s in enumerate(all_shots) if s.id == shot.id), -1)
    variation_score = 100.0
    if shot_idx > 0:
        prev = all_shots[shot_idx - 1]
        if prev.shot_size == shot.shot_size:
            variation_score -= 30
        if prev.camera_movement == shot.camera_movement:
            variation_score -= 20
        if prev.action_summary[:30] == shot.action_summary[:30]:
            variation_score -= 50
            issues.append("相邻镜头动作描述重复")
    score += max(0, variation_score) * 0.15

    # 5. 提示词丰富度 (10%)
    richness_score = 0.0
    all_prompts = [k.visual_prompt for k in shot.keyframes if k.visual_prompt]
    if all_prompts:
        avg_len = sum(len(p) for p in all_prompts) / len(all_prompts)
        richness_score = min(100, avg_len / 60 * 100)
        style_keywords = script.style_prompt.lower().split()
        for kw in style_keywords[:3]:
            if any(kw in p.lower() for p in all_prompts):
                richness_score = min(100, richness_score + 8)
    score += richness_score * 0.10

    grade = "pass" if score >= 80 else "warning" if score >= 60 else "fail"
    return ShotQualityAssessment(score=round(score, 1), grade=grade, issues=issues)


def _apply_quality_pipeline(shots: list[Shot], script: ScriptData) -> list[Shot]:
    print("\n   🔍 质量评估中...")
    fail_count = 0
    for shot in shots:
        shot.quality = _assess_shot_quality(shot, shots, script)
        if shot.quality.grade == "fail":
            fail_count += 1
            shot = _auto_fix_shot(shot, script)
        grade_emoji = "✅" if shot.quality.grade == "pass" else "⚠️" if shot.quality.grade == "warning" else "❌"
        print(f"   {grade_emoji} [{shot.id}] score={shot.quality.score} grade={shot.quality.grade}")
    if fail_count:
        print(f"   🔧 自动修复了 {fail_count} 个低质量分镜")
    return shots


def _auto_fix_shot(shot: Shot, script: ScriptData) -> Shot:
    """对 fail 级分镜强制重写关键帧 prompt"""
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""
    issues_str = "; ".join(shot.quality.issues)
    prompt = f"""Fix and improve this shot's visual prompts. Issues: {issues_str}

{art_block}

Shot: actionSummary="{shot.action_summary}" | cameraMovement={shot.camera_movement} | shotSize={shot.shot_size}
Style: {script.visual_style} | {script.style_prompt}

Generate improved keyframe descriptions (each 60-90 words, rich visual detail):
Output JSON: {{"startPrompt":"...","endPrompt":"..."}}"""

    try:
        data = api.chat_json(prompt, temperature=0.6, max_tokens=1024)
        start_kf = shot.start_keyframe
        end_kf = shot.end_keyframe
        if start_kf and data.get("startPrompt"):
            start_kf.visual_prompt = data["startPrompt"]
        if end_kf and data.get("endPrompt"):
            end_kf.visual_prompt = data["endPrompt"]
    except Exception as e:
        print(f"   ⚠️  自动修复失败 [{shot.id}]: {e}")
    return shot
