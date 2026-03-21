#!/usr/bin/env python3
"""
漫剧生成器 - 基于 Seedance 的漫画风格短剧生成工具
支持图生视频，以主角图片为基础生成漫剧分镜
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Optional


def _load_env_file(path: Path):
    """解析并加载单个 .env 文件，不覆盖已有环境变量"""
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


def load_env():
    """按优先级加载 .env 文件（系统环境变量优先）"""
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
    for env_file in candidates:
        _load_env_file(env_file)


def require_env_key(key: str) -> str:
    """获取必要的环境变量，不存在则抛出异常"""
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"缺少必要的环境变量: {key}\n请在 .env 文件中配置: {key}=your-api-key")
    return value


# 加载环境变量
load_env()

# 默认配置
DEFAULT_MODEL = "doubao-seedance-1-5-pro-251215"
DEFAULT_RATIO = "9:16"  # 漫剧常用竖屏
DEFAULT_RESOLUTION = "1080p"
DEFAULT_DURATION = 5  # 每个分镜5秒

# 漫剧风格预设
MANGA_STYLE_PROMPT = "漫画风格，手绘质感，柔和的色彩过渡，线条清晰，日式或国漫风格，温馨治愈，电影级构图，高细节"

# 漫剧分镜模板
DRAMA_TEMPLATES = {
    "introduction": {
        "name": "主角登场",
        "description": "介绍主角，展示角色特征",
        "default_prompt": "{character}站在画面中央，微笑看向镜头，背景是柔和的光晕，漫画风格，温馨氛围，{style}"
    },
    "action": {
        "name": "动作场景",
        "description": "主角进行某个动作",
        "default_prompt": "{character}正在{action}，表情生动，动作流畅，漫画风格，{style}"
    },
    "emotion": {
        "name": "情感表达",
        "description": "表达某种情感",
        "default_prompt": "{character}露出{emotion}的表情，眼神传达情感，漫画风格，{style}"
    },
    "interaction": {
        "name": "互动场景",
        "description": "与环境或其他元素互动",
        "default_prompt": "{character}与{object}互动，场景温馨，漫画风格，{style}"
    },
    "ending": {
        "name": "结尾定格",
        "description": "漫剧结尾，定格画面",
        "default_prompt": "{character}的定格画面，{ending_scene}，漫画风格，温馨治愈，{style}"
    }
}


def generate_scene_prompt(
    template_key: str,
    character_desc: str,
    style: str = MANGA_STYLE_PROMPT,
    **kwargs
) -> str:
    """根据模板生成分镜提示词"""
    template = DRAMA_TEMPLATES.get(template_key, DRAMA_TEMPLATES["introduction"])
    prompt = template["default_prompt"].format(
        character=character_desc,
        style=style,
        **kwargs
    )
    return prompt


def create_drama_script(
    title: str,
    character_desc: str,
    scenes: List[Dict],
    output_file: str = None
) -> str:
    """
    创建漫剧脚本
    
    Args:
        title: 漫剧标题
        character_desc: 主角描述
        scenes: 分镜列表，每个分镜包含 type, prompt, duration
        output_file: 输出文件路径
    
    Returns:
        脚本内容（JSON 格式）
    """
    script = {
        "title": title,
        "character": character_desc,
        "style": "漫画风格",
        "total_scenes": len(scenes),
        "scenes": []
    }
    
    for i, scene in enumerate(scenes, 1):
        scene_data = {
            "scene_number": i,
            "type": scene.get("type", "introduction"),
            "name": DRAMA_TEMPLATES.get(scene.get("type", "introduction"), {}).get("name", "自定义场景"),
            "prompt": scene.get("prompt", ""),
            "duration": scene.get("duration", DEFAULT_DURATION),
            "ratio": scene.get("ratio", DEFAULT_RATIO),
            "resolution": scene.get("resolution", DEFAULT_RESOLUTION)
        }
        script["scenes"].append(scene_data)
    
    script_json = json.dumps(script, indent=2, ensure_ascii=False)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(script_json)
        print(f"✅ 脚本已保存: {output_file}")
    
    return script_json


def generate_scene_video(
    scene: Dict,
    character_images: List[str],
    model: str = DEFAULT_MODEL,
    output_dir: str = "~/Desktop",
    send_feishu: bool = False
) -> str:
    """
    生成分镜视频

    Args:
        scene: 分镜数据
        character_images: 角色图片路径列表（支持多角色）
        model: 模型 ID
        output_dir: 输出目录
        send_feishu: 是否发送到飞书

    Returns:
        生成的视频路径
    """
    from seedance_video import generate_video_task

    print(f"\n🎬 生成分镜 {scene['scene_number']}: {scene['name']}")
    print(f"📝 提示词: {scene['prompt'][:80]}...")

    video_path = generate_video_task(
        prompt=scene['prompt'],
        image_paths=character_images,
        model=model,
        duration=scene['duration'],
        ratio=scene['ratio'],
        resolution=scene['resolution'],
        output_dir=output_dir,
        send_feishu=send_feishu
    )

    return video_path


def generate_drama(
    script_file: str,
    character_images: List[str],
    output_dir: str = "~/Desktop",
    send_feishu: bool = False
) -> List[str]:
    """
    根据脚本生成完整漫剧

    Args:
        script_file: 脚本文件路径
        character_images: 角色图片路径列表（支持多角色）
        output_dir: 输出目录
        send_feishu: 是否发送到飞书

    Returns:
        生成的视频路径列表
    """
    with open(script_file, 'r', encoding='utf-8') as f:
        script = json.load(f)

    print(f"\n{'='*60}")
    print(f"🎭 开始生成漫剧: {script['title']}")
    print(f"{'='*60}")
    print(f"👤 角色: {script['character']}")
    print(f"🖼️  参考图片: {len(character_images)} 张")
    print(f"📊 分镜数: {script['total_scenes']}")
    print(f"🎨 风格: {script['style']}")
    print()

    output_path = Path(output_dir).expanduser()
    drama_dir = output_path / f"drama_{script['title'].replace(' ', '_')}"
    drama_dir.mkdir(parents=True, exist_ok=True)

    video_files = []
    for scene in script['scenes']:
        try:
            video_path = generate_scene_video(
                scene=scene,
                character_images=character_images,
                output_dir=str(drama_dir),
                send_feishu=send_feishu
            )
            video_files.append(video_path)
        except Exception as e:
            print(f"❌ 分镜 {scene['scene_number']} 生成失败: {e}")

    print(f"\n{'='*60}")
    print(f"✅ 漫剧生成完成!")
    print(f"📁 输出目录: {drama_dir}")
    print(f"🎬 生成视频: {len(video_files)} 个")
    print(f"{'='*60}")

    return video_files


def quick_generate(
    character_images: List[str],
    theme: str,
    num_scenes: int = 3,
    output_dir: str = "~/Desktop",
    send_feishu: bool = False
) -> List[str]:
    """
    快速生成漫剧 - 自动创建脚本并生成

    Args:
        character_images: 角色图片路径列表（支持多角色）
        theme: 漫剧主题/剧情描述
        num_scenes: 分镜数量
        output_dir: 输出目录
        send_feishu: 是否发送到飞书

    Returns:
        生成的视频路径列表
    """
    from seedance_video import analyze_image

    print(f"🔍 分析角色图片（共 {len(character_images)} 张）...")
    character_desc = " 和 ".join(analyze_image(img) for img in character_images)
    print(f"👤 角色特征: {character_desc[:100]}...")
    print()
    
    # 根据主题自动创建分镜
    scenes = []
    scene_types = ["introduction", "action", "emotion", "interaction", "ending"]
    
    for i in range(min(num_scenes, len(scene_types))):
        scene_type = scene_types[i]
        
        if scene_type == "introduction":
            prompt = generate_scene_prompt(
                "introduction",
                character_desc,
                ending_scene="介绍主角"
            )
        elif scene_type == "action":
            prompt = generate_scene_prompt(
                "action",
                character_desc,
                action="进行日常活动"
            )
        elif scene_type == "emotion":
            prompt = generate_scene_prompt(
                "emotion",
                character_desc,
                emotion="开心"
            )
        elif scene_type == "interaction":
            prompt = generate_scene_prompt(
                "interaction",
                character_desc,
                object="周围的环境"
            )
        else:  # ending
            prompt = generate_scene_prompt(
                "ending",
                character_desc,
                ending_scene="温馨的结尾"
            )
        
        # 添加主题上下文
        prompt = f"{theme}主题，{prompt}"
        
        scenes.append({
            "type": scene_type,
            "prompt": prompt,
            "duration": DEFAULT_DURATION,
            "ratio": DEFAULT_RATIO,
            "resolution": DEFAULT_RESOLUTION
        })
    
    # 创建临时脚本
    script_file = Path(output_dir).expanduser() / f"drama_script_{int(os.path.getmtime(character_images[0]))}.json"
    create_drama_script(
        title=f"漫剧-{theme}",
        character_desc=character_desc,
        scenes=scenes,
        output_file=str(script_file)
    )

    # 生成漫剧
    return generate_drama(
        script_file=str(script_file),
        character_images=character_images,
        output_dir=output_dir,
        send_feishu=send_feishu
    )


def main():
    parser = argparse.ArgumentParser(
        description="漫剧生成器 - 基于 Seedance 的漫画风格短剧生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 快速生成漫剧（自动创建脚本）
  python3 manga_drama.py generate --image /path/to/character.png --theme "校园日常"
  
  # 根据脚本生成漫剧
  python3 manga_drama.py from-script --script drama_script.json --image /path/to/character.png
  
  # 创建脚本模板
  python3 manga_drama.py create-script --output my_drama.json
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # generate - 快速生成
    p_generate = subparsers.add_parser("generate", help="快速生成漫剧")
    p_generate.add_argument("--image", "-i", required=True, action="append", dest="images", help="角色图片路径（可多次传入支持多角色）")
    p_generate.add_argument("--theme", "-t", required=True, help="漫剧主题/剧情")
    p_generate.add_argument("--scenes", "-n", type=int, default=3, help="分镜数量（默认3）")
    p_generate.add_argument("--output", "-o", default="~/Desktop", help="输出目录")
    p_generate.add_argument("--send-feishu", action="store_true", help="发送到飞书")

    # from-script - 根据脚本生成
    p_from_script = subparsers.add_parser("from-script", help="根据脚本生成漫剧")
    p_from_script.add_argument("--script", "-s", required=True, help="脚本文件路径")
    p_from_script.add_argument("--image", "-i", required=True, action="append", dest="images", help="角色图片路径（可多次传入支持多角色）")
    p_from_script.add_argument("--output", "-o", default="~/Desktop", help="输出目录")
    p_from_script.add_argument("--send-feishu", action="store_true", help="发送到飞书")
    
    # create-script - 创建脚本模板
    p_create = subparsers.add_parser("create-script", help="创建脚本模板")
    p_create.add_argument("--output", "-o", required=True, help="输出脚本文件路径")
    p_create.add_argument("--title", default="我的漫剧", help="漫剧标题")
    p_create.add_argument("--character", default="可爱的主角", help="主角描述")
    p_create.add_argument("--num-scenes", type=int, default=3, help="分镜数量")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # 设置 API Key
    require_env_key("ARK_API_KEY")
    
    try:
        if args.command == "generate":
            video_files = quick_generate(
                character_images=args.images,
                theme=args.theme,
                num_scenes=args.scenes,
                output_dir=args.output,
                send_feishu=args.send_feishu
            )
            print(f"\n🎉 漫剧生成完成! 共 {len(video_files)} 个视频")
            for i, vf in enumerate(video_files, 1):
                print(f"   分镜{i}: {vf}")
        
        elif args.command == "from-script":
            video_files = generate_drama(
                script_file=args.script,
                character_images=args.images,
                output_dir=args.output,
                send_feishu=args.send_feishu
            )
            print(f"\n🎉 漫剧生成完成! 共 {len(video_files)} 个视频")
        
        elif args.command == "create-script":
            # 创建脚本模板
            scenes = []
            for i in range(args.num_scenes):
                scene_type = ["introduction", "action", "emotion", "interaction", "ending"][i % 5]
                scenes.append({
                    "type": scene_type,
                    "prompt": f"请修改此分镜{i+1}的提示词",
                    "duration": DEFAULT_DURATION
                })
            
            create_drama_script(
                title=args.title,
                character_desc=args.character,
                scenes=scenes,
                output_file=args.output
            )
            print(f"\n✅ 脚本模板已创建: {args.output}")
            print("📝 请编辑脚本文件，修改分镜提示词后使用 from-script 命令生成漫剧")
    
    except Exception as e:
        print(f"\n❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
