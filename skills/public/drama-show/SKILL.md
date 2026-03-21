---
name: drama-show
description: 专业漫剧生成器 — 参考 BigBanana AI Director 工业级工作流。输入故事文本，自动完成剧本解析、美术指导、角色/场景资产生成、分镜质量评估、关键帧优化、视频生成、成片合并全流程。支持3D温馨动漫、国漫手绘、日漫、赛博朋克等多种风格预设。当用户想生成专业漫剧、短视频、AI短片时使用此技能。
---

# drama-show — 专业漫剧导演台

基于工业级四阶段工作流，从故事文本到成片一键生成。

## 前置要求

需要设置 `ARK_API_KEY` 环境变量（火山方舟 API Key）。

## 四阶段工作流

```
Phase 01  剧本解析
  Agent1: 结构化解析（角色/场景/道具/段落）
  Agent2: 视觉增强（美术指导文档 + 角色/场景/道具提示词）
  Agent3: 分镜生成（5维质量评分 + 自动修复）

Phase 02  资产生成
  角色定妆参考图（每角色独立）
  场景概念图（无人物）
  道具参考图

Phase 03  导演工作台
  关键帧优化（起止帧双帧协调）
  关键帧图像生成（注入参考图）
  Seedance 视频生成（图生视频）

Phase 04  成片导出
  ffmpeg 标准化 + 拼接
  可选背景音乐混合
  Economy / Balanced / Pro 三档质量
```

## 使用方法

### 快速生成
```bash
cd /path/to/drama-show
python3 scripts/director.py generate \
  --story "狐狸和小兔的奇幻冒险，他们一起寻找失落的魔法星星" \
  --style "3D温馨动漫" \
  --duration 60
```

### 从文件读取故事
```bash
python3 scripts/director.py generate \
  --story-file /path/to/story.txt \
  --style "国漫手绘" \
  --output ~/Desktop/my_drama \
  --duration 90 \
  --bgm /path/to/bgm.mp3
```

### 恢复中断的生成
```bash
python3 scripts/director.py resume \
  --project-dir ~/Desktop/drama_show_xxx/
```

### 只生成脚本和分镜（不生成视频）
```bash
python3 scripts/director.py generate \
  --story "..." \
  --style "日漫" \
  --skip-videos \
  --skip-merge
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--story` | 必填 | 故事文本 |
| `--story-file` | - | 故事文本文件路径 |
| `--style` | 3D温馨动漫 | 视觉风格预设 |
| `--duration` | 60 | 目标总时长（秒） |
| `--shot-duration` | 5 | 每个分镜时长（秒） |
| `--ratio` | 16:9 | 视频比例 16:9 / 9:16 / 1:1 |
| `--quality` | balanced | economy / balanced / pro |
| `--output` | ~/Desktop/drama_xxx | 输出目录 |
| `--bgm` | 无 | 背景音乐文件路径 |
| `--skip-assets` | false | 跳过资产图像生成 |
| `--skip-keyframes` | false | 跳过关键帧优化 |
| `--skip-videos` | false | 跳过视频生成 |
| `--skip-merge` | false | 跳过成片合并 |

## 风格预设

| 预设名 | 风格描述 |
|--------|---------|
| 3D温馨动漫 | Pixar 风 3D 渲染，暖色调，高质感 |
| 国漫手绘 | 手绘线条，水彩色调，温馨氛围 |
| 日漫 | 日式动漫，清晰线条，鲜明色彩 |
| 赛博朋克 | 霓虹暗色，科技感，戏剧性光影 |
| 水墨国风 | 传统水墨，留白构图，诗意意境 |
| 欧美漫画 | 粗线条，平涂色彩，超级英雄美学 |

## 输出结构

```
~/Desktop/drama_show_xxx/
├── progress.json           # 全流程进度（可用于 resume）
├── assets/
│   ├── char_xxx.png        # 角色定妆图
│   ├── scene_xxx.png       # 场景概念图
│   └── prop_xxx.png        # 道具参考图
├── keyframes/
│   └── kf_s1_1_start.png   # 分镜关键帧图
├── videos/
│   └── shot_xxx.mp4        # 各分镜视频
└── 标题_master.mp4         # 最终成片
```

## 核心特性（对标 BigBanana AI Director）

- **三段式 AI 剧本流水线**：结构化 → 视觉增强 → 分镜生成
- **全局美术指导文档**：动态生成风格锚点，注入所有后续提示词
- **5维分镜质量评分**：必填字段/关键帧结构/资产引用/场景差异/提示词丰富度
- **双帧关键帧优化**：起止帧协调一致，镜头运动轨迹清晰可推导
- **资产一致性**：角色定妆图作为参考注入每个分镜的图像生成
- **断点续生成**：progress.json 记录全流程状态，随时恢复
- **ffmpeg 合成**：三档质量预设，可混合背景音乐
