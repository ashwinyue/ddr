"""
drama-show 数据模型
对应 BigBanana types.ts 核心数据结构
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class ColorPalette:
    primary: str = ""
    secondary: str = ""
    accent: str = ""
    skin_tones: str = ""
    saturation: str = ""
    temperature: str = ""


@dataclass
class CharacterDesignRules:
    proportions: str = ""
    eye_style: str = ""
    line_weight: str = ""
    detail_level: str = ""


@dataclass
class ArtDirection:
    """全局美术指导文档 — 所有后续 prompt 的风格锚点"""
    color_palette: ColorPalette = field(default_factory=ColorPalette)
    character_design_rules: CharacterDesignRules = field(default_factory=CharacterDesignRules)
    lighting_style: str = ""
    texture_style: str = ""
    mood_keywords: list[str] = field(default_factory=list)
    consistency_anchors: str = ""  # 注入所有 prompt 的 80-120 词主风格段落

    def to_prompt_block(self) -> str:
        """生成注入 prompt 的美术指导段落"""
        cp = self.color_palette
        cd = self.character_design_rules
        return (
            f"⚠️ GLOBAL ART DIRECTION (MANDATORY):\n"
            f"{self.consistency_anchors}\n"
            f"Color Palette: Primary={cp.primary}, Secondary={cp.secondary}, "
            f"Accent={cp.accent}, SkinTones={cp.skin_tones}, "
            f"Saturation={cp.saturation}, Temperature={cp.temperature}\n"
            f"Character Design: Proportions={cd.proportions}, Eyes={cd.eye_style}, "
            f"LineWeight={cd.line_weight}, Detail={cd.detail_level}\n"
            f"Lighting: {self.lighting_style} | Texture: {self.texture_style}\n"
            f"Mood: {', '.join(self.mood_keywords)}"
        )

    @classmethod
    def from_dict(cls, d: dict) -> ArtDirection:
        cp_raw = d.get("colorPalette") or d.get("color_palette") or {}
        cd_raw = d.get("characterDesignRules") or d.get("character_design_rules") or {}
        return cls(
            color_palette=ColorPalette(
                primary=cp_raw.get("primary", ""),
                secondary=cp_raw.get("secondary", ""),
                accent=cp_raw.get("accent", ""),
                skin_tones=cp_raw.get("skinTones") or cp_raw.get("skin_tones", ""),
                saturation=cp_raw.get("saturation", ""),
                temperature=cp_raw.get("temperature", ""),
            ),
            character_design_rules=CharacterDesignRules(
                proportions=cd_raw.get("proportions", ""),
                eye_style=cd_raw.get("eyeStyle") or cd_raw.get("eye_style", ""),
                line_weight=cd_raw.get("lineWeight") or cd_raw.get("line_weight", ""),
                detail_level=cd_raw.get("detailLevel") or cd_raw.get("detail_level", ""),
            ),
            lighting_style=d.get("lightingStyle") or d.get("lighting_style", ""),
            texture_style=d.get("textureStyle") or d.get("texture_style", ""),
            mood_keywords=d.get("moodKeywords") or d.get("mood_keywords") or [],
            consistency_anchors=d.get("consistencyAnchors") or d.get("consistency_anchors", ""),
        )


@dataclass
class Character:
    id: str
    name: str
    gender: str = ""
    age: str = ""
    personality: str = ""
    visual_prompt: str = ""
    reference_image_path: Optional[str] = None  # 定妆图路径

    @classmethod
    def from_dict(cls, d: dict) -> Character:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            gender=d.get("gender", ""),
            age=d.get("age", ""),
            personality=d.get("personality", ""),
            visual_prompt=d.get("visualPrompt") or d.get("visual_prompt", ""),
        )


@dataclass
class Scene:
    id: str
    location: str = ""
    time: str = ""
    atmosphere: str = ""
    visual_prompt: str = ""
    reference_image_path: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> Scene:
        return cls(
            id=d.get("id", ""),
            location=d.get("location", ""),
            time=d.get("time", ""),
            atmosphere=d.get("atmosphere", ""),
            visual_prompt=d.get("visualPrompt") or d.get("visual_prompt", ""),
        )


@dataclass
class Prop:
    id: str
    name: str = ""
    category: str = ""
    description: str = ""
    visual_prompt: str = ""
    reference_image_path: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> Prop:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            category=d.get("category", ""),
            description=d.get("description", ""),
            visual_prompt=d.get("visualPrompt") or d.get("visual_prompt", ""),
        )


@dataclass
class StoryParagraph:
    id: int
    text: str
    scene_ref_id: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> StoryParagraph:
        return cls(
            id=d.get("id", 0),
            text=d.get("text", ""),
            scene_ref_id=d.get("sceneRefId") or d.get("scene_ref_id", ""),
        )


@dataclass
class ShotQualityAssessment:
    score: float = 0.0
    grade: str = "fail"  # pass / warning / fail
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.grade == "pass"


@dataclass
class Keyframe:
    id: str
    type: str  # 'start' | 'end'
    visual_prompt: str = ""
    image_path: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> Keyframe:
        return cls(
            id=d.get("id", ""),
            type=d.get("type", "start"),
            visual_prompt=d.get("visualPrompt") or d.get("visual_prompt", ""),
        )


@dataclass
class Shot:
    id: str
    scene_id: str
    action_summary: str = ""
    dialogue: str = ""
    camera_movement: str = ""
    shot_size: str = ""
    characters: list[str] = field(default_factory=list)   # character IDs
    props: list[str] = field(default_factory=list)          # prop IDs
    keyframes: list[Keyframe] = field(default_factory=list)
    video_path: Optional[str] = None
    quality: Optional[ShotQualityAssessment] = None

    @property
    def start_keyframe(self) -> Optional[Keyframe]:
        return next((k for k in self.keyframes if k.type == "start"), None)

    @property
    def end_keyframe(self) -> Optional[Keyframe]:
        return next((k for k in self.keyframes if k.type == "end"), None)

    @classmethod
    def from_dict(cls, d: dict) -> Shot:
        kfs = [Keyframe.from_dict(k) for k in d.get("keyframes", [])]
        return cls(
            id=d.get("id", ""),
            scene_id=d.get("sceneId") or d.get("scene_id", ""),
            action_summary=d.get("actionSummary") or d.get("action_summary", ""),
            dialogue=d.get("dialogue", ""),
            camera_movement=d.get("cameraMovement") or d.get("camera_movement", ""),
            shot_size=d.get("shotSize") or d.get("shot_size", ""),
            characters=d.get("characters", []),
            props=d.get("props", []),
            keyframes=kfs,
        )


@dataclass
class ScriptData:
    """完整项目数据，贯穿全流程"""
    title: str = ""
    genre: str = ""
    logline: str = ""
    original_story: str = ""  # 原始故事文本，用于断点恢复后重新解析
    language: str = "zh"
    visual_style: str = "3D温馨动漫"
    style_prompt: str = "3D animation style, warm colors, high quality render, cinematic"
    art_direction: Optional[ArtDirection] = None
    characters: list[Character] = field(default_factory=list)
    scenes: list[Scene] = field(default_factory=list)
    props: list[Prop] = field(default_factory=list)
    story_paragraphs: list[StoryParagraph] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)

    def get_character(self, cid: str) -> Optional[Character]:
        return next((c for c in self.characters if c.id == cid), None)

    def get_scene(self, sid: str) -> Optional[Scene]:
        return next((s for s in self.scenes if s.id == sid), None)

    def get_prop(self, pid: str) -> Optional[Prop]:
        return next((p for p in self.props if p.id == pid), None)

    def to_dict(self) -> dict:
        """序列化为 dict，用于保存进度"""
        import dataclasses
        return dataclasses.asdict(self)

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"💾 进度已保存: {path}")
