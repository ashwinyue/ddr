"""
剧本解析三段式流水线
Agent1: parseScriptStructure  — 结构化解析
Agent2: enrichScriptDataVisuals — 视觉增强（美术指导 + 角色/场景/道具提示词）
Agent3: generateShotList       — 分镜生成（见 shot_generator.py）
"""
from __future__ import annotations
import json
from models import (
    ScriptData, Character, Scene, Prop, StoryParagraph, ArtDirection
)
import api_client as api


# ─────────────────────────────────────────────
# Agent 1: 结构化解析
# ─────────────────────────────────────────────

def parse_script_structure(raw_text: str, language: str = "zh") -> ScriptData:
    print("📖 Agent1: 解析剧本结构...")
    prompt = f"""Analyze the text and output a JSON object. Output language: {language}.

Tasks:
1. Extract title, genre, logline (in {language}).
2. Extract characters (id, name, gender, age, personality).
3. Extract scenes (id, location, time, atmosphere).
4. Extract recurring props/items that appear in multiple scenes (id, name, category, description).
5. Break down the story into paragraphs linked to scenes.

Input:
\"\"\"{raw_text[:30000]}\"\"\"

Output ONLY valid JSON:
{{
  "title": "string",
  "genre": "string",
  "logline": "string",
  "characters": [{{"id":"string","name":"string","gender":"string","age":"string","personality":"string"}}],
  "scenes": [{{"id":"string","location":"string","time":"string","atmosphere":"string"}}],
  "props": [{{"id":"string","name":"string","category":"string","description":"string"}}],
  "storyParagraphs": [{{"id":1,"text":"string","sceneRefId":"string"}}]
}}"""

    data = api.chat_json(prompt, temperature=0.7, max_tokens=8192)

    script = ScriptData(
        title=data.get("title", "未命名"),
        genre=data.get("genre", ""),
        logline=data.get("logline", ""),
        language=language,
    )
    script.characters = [Character.from_dict(c) for c in data.get("characters", [])]
    script.scenes = [Scene.from_dict(s) for s in data.get("scenes", [])]
    script.props = [Prop.from_dict(p) for p in data.get("props", [])]
    script.story_paragraphs = [StoryParagraph.from_dict(p) for p in data.get("storyParagraphs", [])]

    print(f"   ✅ 解析完成: {len(script.characters)} 角色 / {len(script.scenes)} 场景 / {len(script.props)} 道具")
    return script


# ─────────────────────────────────────────────
# Agent 2: 视觉增强
# ─────────────────────────────────────────────

def enrich_script_visuals(script: ScriptData) -> ScriptData:
    print("\n🎨 Agent2: 生成视觉提示词...")

    # Step 1: 全局美术指导
    script.art_direction = _generate_art_direction(script)

    # Step 2: 批量生成角色提示词
    if script.characters:
        _generate_all_character_prompts(script)

    # Step 3: 批量生成场景提示词
    scenes_without_prompt = [s for s in script.scenes if not s.visual_prompt]
    if scenes_without_prompt:
        _generate_all_scene_prompts(script, scenes_without_prompt)

    # Step 4: 批量生成道具提示词
    props_without_prompt = [p for p in script.props if not p.visual_prompt]
    if props_without_prompt:
        _generate_all_prop_prompts(script, props_without_prompt)

    return script


def _generate_art_direction(script: ScriptData) -> ArtDirection:
    print("   🎭 生成全局美术指导文档...")
    chars_desc = "\n".join(
        f"  {i+1}. {c.name} ({c.gender}, {c.age}, {c.personality})"
        for i, c in enumerate(script.characters)
    )
    scenes_desc = "\n".join(
        f"  {i+1}. {s.location} - {s.time} - {s.atmosphere}"
        for i, s in enumerate(script.scenes)
    )
    prompt = f"""You are a world-class Art Director for {script.visual_style} productions.
Create a unified Art Direction Brief that will guide ALL visual prompt generation.

## Project Info
- Title: {script.title}
- Genre: {script.genre}
- Logline: {script.logline}
- Visual Style: {script.visual_style} ({script.style_prompt})
- Language: {script.language}

## Characters:
{chars_desc}

## Scenes:
{scenes_desc}

## Your Task
Create a comprehensive Art Direction Brief in JSON.

CRITICAL RULES:
- All descriptions must be specific, concrete, and actionable for image generation AI
- The brief must define a COHESIVE visual world
- Output all descriptive text in {script.language}

Output ONLY valid JSON:
{{
  "colorPalette": {{
    "primary": "...", "secondary": "...", "accent": "...",
    "skinTones": "...", "saturation": "...", "temperature": "..."
  }},
  "characterDesignRules": {{
    "proportions": "...", "eyeStyle": "...", "lineWeight": "...", "detailLevel": "..."
  }},
  "lightingStyle": "...",
  "textureStyle": "...",
  "moodKeywords": ["kw1","kw2","kw3","kw4","kw5"],
  "consistencyAnchors": "A single comprehensive paragraph (80-120 words) serving as MASTER STYLE REFERENCE..."
}}"""

    data = api.chat_json(prompt, temperature=0.4, max_tokens=4096)
    art = ArtDirection.from_dict(data)
    print(f"   ✅ 美术指导生成完成 | 风格锚点: {art.consistency_anchors[:60]}...")
    return art


def _generate_all_character_prompts(script: ScriptData):
    print(f"   👥 批量生成 {len(script.characters)} 个角色视觉提示词...")
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""
    chars_list = "\n".join(
        f"Character {i+1} (ID: {c.id}) | Name: {c.name} | Gender: {c.gender} | Age: {c.age} | Personality: {c.personality}"
        for i, c in enumerate(script.characters)
    )
    prompt = f"""You are an expert Art Director and AI prompt engineer for {script.visual_style} style image generation.
Generate visual prompts for ALL {len(script.characters)} characters in a SINGLE response.

## GLOBAL ART DIRECTION (MANDATORY)
{art_block}

## Genre: {script.genre}
## Technical Quality: {script.style_prompt}

## Characters to Generate:
{chars_list}

## REQUIRED PROMPT STRUCTURE (for EACH character, in {script.language}):
1. Core Identity [MUST follow proportions rule]
2. Facial Features [MUST follow eye style rule, skin tone from palette]
3. Hairstyle [color, length, style]
4. Clothing [colors MUST harmonize with palette]
5. Pose & Expression [matching personality]
6. Technical Quality: {script.style_prompt}

## CRITICAL CONSISTENCY RULES:
1. All characters MUST share the same art style
2. All characters MUST have the same proportions, line weight, detail level
3. Characters must look visually distinct from each other
4. Sections 1-3 are FIXED features for consistency across all variations

## OUTPUT FORMAT
{{"characters":[{{"id":"character_id","visualPrompt":"single paragraph, 60-90 words"}}]}}
The "characters" array MUST have exactly {len(script.characters)} items."""

    data = api.chat_json(prompt, temperature=0.5, max_tokens=4096)
    chars_data = data.get("characters", [])
    prompt_map = {c["id"]: c.get("visualPrompt", "") for c in chars_data}
    for char in script.characters:
        if char.id in prompt_map:
            char.visual_prompt = prompt_map[char.id]
            print(f"   ✅ 角色 [{char.name}] 提示词就绪")
        else:
            char.visual_prompt = _generate_single_character_prompt(char, script)


def _generate_single_character_prompt(char: Character, script: ScriptData) -> str:
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""
    prompt = f"""You are an expert AI prompt engineer for {script.visual_style} style.
{art_block}

Character: Name={char.name} | Gender={char.gender} | Age={char.age} | Personality={char.personality}

Generate a visual prompt in {script.language} (60-90 words):
1. Core Identity [follow proportions]
2. Facial Features [follow eye style, skin tone]
3. Hairstyle
4. Clothing [harmonize with palette]
5. Pose & Expression
6. Technical Quality: {script.style_prompt}

Output ONLY the prompt text, no JSON."""
    return api.chat(prompt, temperature=0.6, max_tokens=512)


def _generate_scene_prompt(scene: Scene, script: ScriptData) -> str:
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""
    prompt = f"""You are an expert cinematographer and AI prompt engineer for {script.visual_style}.
{art_block}

Scene: Location={scene.location} | Time={scene.time} | Atmosphere={scene.atmosphere} | Genre={script.genre}

Generate a scene visual prompt in {script.language} (70-110 words):
1. Environment [architectural/natural elements, ABSOLUTELY NO PEOPLE]
2. Lighting [MUST follow project lighting style]
3. Composition [camera angle, framing, depth layers]
4. Atmosphere [mood, weather, particles]
5. Color Palette [MUST use project palette]
6. Technical Quality: {script.style_prompt}

⚠️ ABSOLUTELY NO PEOPLE, characters, or figures in the scene.
Output ONLY the prompt text."""
    return api.chat(prompt, temperature=0.6, max_tokens=512)


def _generate_prop_prompt(prop: Prop, script: ScriptData) -> str:
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""
    prompt = f"""You are an expert AI prompt engineer for {script.visual_style}.
{art_block}

Prop: Name={prop.name} | Category={prop.category} | Description={prop.description}

Generate a prop visual prompt in {script.language} (55-95 words):
1. Form & Silhouette [shape, scale, outline]
2. Material & Texture
3. Color & Finish [MUST harmonize with project palette]
4. Craft & Details [logos, engravings, patterns]
5. Presentation [studio/cinematic lighting, neutral background]
6. Technical Quality: {script.style_prompt}

Object-only shot, NO people/hands visible.
Output ONLY the prompt text."""
    return api.chat(prompt, temperature=0.6, max_tokens=400)


def _generate_all_scene_prompts(script: ScriptData, scenes=None):
    """批量生成场景提示词（一次 API 调用）"""
    targets = scenes if scenes is not None else script.scenes
    print(f"   🏞️  批量生成 {len(targets)} 个场景视觉提示词...")
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""
    scenes_list = "\n".join(
        f"Scene {i+1} (ID: {s.id}) | Location: {s.location} | Time: {s.time} | Atmosphere: {s.atmosphere}"
        for i, s in enumerate(targets)
    )
    prompt = f"""You are an expert cinematographer and AI prompt engineer for {script.visual_style}.
Generate scene visual prompts for ALL {len(targets)} scenes in a SINGLE response.

## GLOBAL ART DIRECTION (MANDATORY)
{art_block}

## Genre: {script.genre}
## Technical Quality: {script.style_prompt}

## Scenes to Generate:
{scenes_list}

## REQUIRED PROMPT STRUCTURE (for EACH scene, in {script.language}):
1. Environment [architectural/natural elements, ABSOLUTELY NO PEOPLE]
2. Lighting [MUST follow project lighting style]
3. Composition [camera angle, framing, depth layers]
4. Atmosphere [mood, weather, particles]
5. Color Palette [MUST use project palette]
6. Technical Quality: {script.style_prompt}

⚠️ ABSOLUTELY NO PEOPLE, characters, or figures in any scene prompt.

## OUTPUT FORMAT
{{"scenes":[{{"id":"scene_id","visualPrompt":"single paragraph, 70-110 words"}}]}}
The "scenes" array MUST have exactly {len(targets)} items."""

    data = api.chat_json(prompt, temperature=0.5, max_tokens=4096)
    prompt_map = {s["id"]: s.get("visualPrompt", "") for s in data.get("scenes", [])}
    for scene in targets:
        if scene.id in prompt_map:
            scene.visual_prompt = prompt_map[scene.id]
            print(f"   ✅ 场景 [{scene.id}] 提示词就绪")
        else:
            scene.visual_prompt = _generate_scene_prompt(scene, script)
            print(f"   🔄 场景 [{scene.id}] 回退单独生成")


def _generate_all_prop_prompts(script: ScriptData, props=None):
    """批量生成道具提示词（一次 API 调用）"""
    targets = props if props is not None else script.props
    print(f"   🔧 批量生成 {len(targets)} 个道具视觉提示词...")
    art_block = script.art_direction.to_prompt_block() if script.art_direction else ""
    props_list = "\n".join(
        f"Prop {i+1} (ID: {p.id}) | Name: {p.name} | Category: {p.category} | Description: {p.description}"
        for i, p in enumerate(targets)
    )
    prompt = f"""You are an expert AI prompt engineer for {script.visual_style}.
Generate visual prompts for ALL {len(targets)} props in a SINGLE response.

## GLOBAL ART DIRECTION (MANDATORY)
{art_block}

## Genre: {script.genre}
## Technical Quality: {script.style_prompt}

## Props to Generate:
{props_list}

## REQUIRED PROMPT STRUCTURE (for EACH prop, in {script.language}):
1. Form & Silhouette [shape, scale, outline]
2. Material & Texture
3. Color & Finish [MUST harmonize with project palette]
4. Craft & Details [logos, engravings, patterns]
5. Presentation [studio/cinematic lighting, neutral background]
6. Technical Quality: {script.style_prompt}

Object-only shot, NO people/hands visible.

## OUTPUT FORMAT
{{"props":[{{"id":"prop_id","visualPrompt":"single paragraph, 55-95 words"}}]}}
The "props" array MUST have exactly {len(targets)} items."""

    data = api.chat_json(prompt, temperature=0.5, max_tokens=4096)
    prompt_map = {p["id"]: p.get("visualPrompt", "") for p in data.get("props", [])}
    for prop in targets:
        if prop.id in prompt_map:
            prop.visual_prompt = prompt_map[prop.id]
            print(f"   ✅ 道具 [{prop.name}] 提示词就绪")
        else:
            prop.visual_prompt = _generate_prop_prompt(prop, script)
            print(f"   🔄 道具 [{prop.name}] 回退单独生成")


# ─────────────────────────────────────────────
# 完整流水线入口
# ─────────────────────────────────────────────

def parse_and_enrich(raw_text: str, visual_style: str = "3D温馨动漫",
                     style_prompt: str = "3D animation style, warm colors, cinematic quality",
                     language: str = "zh") -> ScriptData:
    """完整 Agent1+Agent2 流水线"""
    script = parse_script_structure(raw_text, language)
    script.visual_style = visual_style
    script.style_prompt = style_prompt
    script = enrich_script_visuals(script)
    return script
