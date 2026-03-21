import base64
import json
import os

import requests
from PIL import Image


def validate_image(image_path: str) -> bool:
    try:
        with Image.open(image_path) as img:
            img.verify()
        with Image.open(image_path) as img:
            img.load()
        return True
    except Exception as e:
        print(f"Warning: Image '{image_path}' is invalid or corrupted: {e}")
        return False


def image_to_data_uri(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def generate_image(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    api_key = os.getenv("ARK_API_KEY") or os.getenv("VOLCENGINE_API_KEY")
    if not api_key:
        return "ARK_API_KEY is not set"

    # Parse prompt file (JSON or plain text)
    with open(prompt_file, "r", encoding="utf-8") as f:
        content = f.read().strip()

    try:
        data = json.loads(content)
        parts = []
        for field in ("prompt", "style", "composition", "color_palette", "lighting", "effects", "consistency_note"):
            if data.get(field):
                parts.append(data[field])
        prompt = " ".join(parts)
    except (json.JSONDecodeError, TypeError):
        prompt = content

    # Filter invalid reference images
    valid_refs = [r for r in reference_images if validate_image(r)]
    skipped = len(reference_images) - len(valid_refs)
    if skipped:
        print(f"Note: {skipped} reference image(s) skipped due to validation failure.")

    # Build request payload
    payload = {
        "model": "doubao-seedream-5-0-260128",
        "prompt": prompt,
        "size": "2K",
        "response_format": "url",
        "stream": False,
        "watermark": False,
        "sequential_image_generation": "disabled",
    }

    # Attach reference images for style consistency (image-to-image)
    if valid_refs:
        payload["image"] = [image_to_data_uri(r) for r in valid_refs]

    response = requests.post(
        "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    result = response.json()

    image_url = result["data"][0]["url"]

    # Download and save the image
    img_response = requests.get(image_url, timeout=60)
    img_response.raise_for_status()
    with open(output_file, "wb") as f:
        f.write(img_response.content)

    return f"Successfully generated image to {output_file}"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate images using Volcengine ARK Seedream")
    parser.add_argument("--prompt-file", required=True, help="Absolute path to prompt file (text or JSON)")
    parser.add_argument("--reference-images", nargs="*", default=[], help="Absolute paths to reference images")
    parser.add_argument("--output-file", required=True, help="Output path for generated image")
    parser.add_argument("--aspect-ratio", required=False, default="16:9", help="Aspect ratio (16:9, 4:3, 1:1, 9:16)")

    args = parser.parse_args()

    try:
        print(generate_image(args.prompt_file, args.reference_images, args.output_file, args.aspect_ratio))
    except Exception as e:
        print(f"Error while generating image: {e}")
