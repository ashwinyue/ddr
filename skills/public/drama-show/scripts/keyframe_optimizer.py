"""
关键帧优化器
对应 BigBanana shotService.optimizeBothKeyframes
同时优化起始帧和结束帧，确保视觉连贯性
"""
from __future__ import annotations
from models import ScriptData, Shot
import api_client as api


def optimize_keyframes(shot: Shot, script: ScriptData) -> Shot:
    """
    同时优化起始帧和结束帧的 visualPrompt
    确保两帧在视觉上连贯协调，镜头运动轨迹清晰可推导
    """
    scene = script.get_scene(shot.scene_id)
    scene_info = f"{scene.location} / {scene.time} / {scene.atmosphere}" if scene else "未知场景"

    char_names = [
        script.get_character(cid).name
        for cid in shot.characters
        if script.get_character(cid)
    ]
    char_info = "、".join(char_names) if char_names else "无角色"

    style_desc = f"{script.visual_style}（{script.style_prompt}）"

    prompt = f"""你是一位专业的电影视觉导演和概念艺术家。请为以下镜头同时创作起始帧和结束帧的详细视觉描述。

## 场景信息
地点/时间/氛围：{scene_info}

## 叙事动作
{shot.action_summary}

## 对话
{shot.dialogue or '无'}

## 镜头运动
{shot.camera_movement}

## 景别
{shot.shot_size}

## 角色信息
{char_info}

## 视觉风格
{style_desc}

---

起始帧要求：
- 建立清晰的初始状态和构图
- 预留视觉空间以容纳即将发生的动作
- 设定光影基调和情绪氛围
- 角色姿态与情绪准备好迎接动作

结束帧要求：
- 展现动作完成后的最终状态
- 体现镜头运动带来的视角变化
- 光影和情绪随叙事发展自然演进
- 为下一个镜头留出衔接空间

⚠️ 两帧协调性：起始帧和结束帧必须在视觉上连贯协调，镜头运动轨迹清晰可推导。

每帧必须包含（100-150字）：
1. 构图与景别
2. 光影与色彩（参照风格：{script.visual_style}）
3. 角色细节（姿态、表情、服饰）
4. 环境细节
5. 运动暗示（暗示下一帧/上一帧的连接）
6. 电影感细节

输出格式（仅输出 JSON）：
{{"startFrame": "起始帧描述...", "endFrame": "结束帧描述..."}}"""

    try:
        data = api.chat_json(prompt, temperature=0.7, max_tokens=2048)
        start_kf = shot.start_keyframe
        end_kf = shot.end_keyframe
        if start_kf and data.get("startFrame"):
            start_kf.visual_prompt = data["startFrame"]
        if end_kf and data.get("endFrame"):
            end_kf.visual_prompt = data["endFrame"]
        print(f"   ✨ 关键帧已优化 [{shot.id}]")
    except Exception as e:
        print(f"   ⚠️  关键帧优化失败 [{shot.id}]: {e}")
    return shot


def optimize_all_keyframes(shots: list[Shot], script: ScriptData) -> list[Shot]:
    """批量优化所有分镜的关键帧"""
    print(f"\n✨ 优化 {len(shots)} 个分镜的关键帧...")
    for i, shot in enumerate(shots):
        print(f"   [{i+1}/{len(shots)}] {shot.id}: {shot.action_summary[:40]}...")
        shots[i] = optimize_keyframes(shot, script)
    return shots
