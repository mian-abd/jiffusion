"""Convert a raster image to an ID-prompt.txt dataset record with five brightness levels."""

import argparse
from pathlib import Path
import re

from PIL import Image, ImageOps

from prompts import PALETTE


def to_ascii(image, size=20):
    """Fit to a square white canvas, then quantize to the shared light-to-dark palette."""
    if size < 1:
        raise ValueError("Size must be positive")
    image = ImageOps.exif_transpose(image).convert("RGBA")
    white = Image.new("RGBA", image.size, "white")
    gray = Image.alpha_composite(white, image).convert("L")
    scale = min(size / gray.width, size / gray.height)
    dimensions = (max(1, round(gray.width * scale)), max(1, round(gray.height * scale)))
    gray = gray.resize(dimensions, Image.Resampling.LANCZOS)
    canvas = Image.new("L", (size, size), 255)
    canvas.paste(gray, ((size - gray.width) // 2, (size - gray.height) // 2))
    pixels = canvas.load()
    return "\n".join(
        "".join(PALETTE[round((255 - pixels[x, y]) * (len(PALETTE) - 1) / 255)]
                for x in range(size))
        for y in range(size)
    )


def write_example(source, *, prompt, example_id, size=20, output_dir=Path("dataset/gold")):
    if not prompt.strip() or "\n" in prompt or "\r" in prompt:
        raise ValueError("Prompt must be one nonempty line")
    if example_id < 1:
        raise ValueError("ID must be positive")
    prompt = prompt.strip()
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-") or "clipart"
    output_dir = Path(output_dir)
    if any(output_dir.rglob(f"{example_id:03}-*.txt")):
        raise FileExistsError(f"ID {example_id:03} already exists in {output_dir}")
    with Image.open(source) as image:
        artwork = to_ascii(image, size)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{example_id:03}-{slug}.txt"
    with output.open("x", encoding="utf-8", newline="\n") as file:
        file.write(prompt + "\n" + artwork + "\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="source PNG, JPEG, WebP, or other Pillow-supported raster image")
    parser.add_argument("--prompt", required=True, help="target description written on the first line")
    parser.add_argument("--id", dest="example_id", type=int, required=True, help="positive dataset ID")
    parser.add_argument("--size", type=int, default=20, help="square output size (default: 20)")
    parser.add_argument("--output-dir", type=Path, default=Path("dataset/gold"))
    args = parser.parse_args()
    try:
        output = write_example(args.image, prompt=args.prompt, example_id=args.example_id,
                               size=args.size, output_dir=args.output_dir)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        parser.error(str(exc))
    print(output.resolve())


if __name__ == "__main__":
    main()
