"""Generate 250 reproducible shape references using the five-level ASCII converter."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageOps

from image_to_ascii import to_ascii
from prompts import PALETTE

SHAPES = ("circle", "square", "triangle", "rectangle", "ellipse", "diamond",
          "pentagon", "hexagon", "star", "cross")
STYLES = ("filled", "outline", "negative", "negative-outline", "hole")
VARIANTS = (
    dict(name="large", center=[10, 10], span=15, stroke=1.25),
    dict(name="small", center=[10, 10], span=12, stroke=1.0),
    dict(name="left", center=[8, 10], span=12, stroke=1.4),
    dict(name="right", center=[12, 10], span=12, stroke=1.2),
    dict(name="upper", center=[10, 8], span=12, stroke=1.1),
)
SIZE = 20
SCALE = 16


def polygon(shape):
    if shape == "triangle":
        return [(0, -.5), (.5, .5), (-.5, .5)]
    if shape == "diamond":
        return [(0, -.5), (.38, 0), (0, .5), (-.38, 0)]
    if shape == "cross":
        return [(-.22, -.5), (.22, -.5), (.22, -.22), (.5, -.22),
                (.5, .22), (.22, .22), (.22, .5), (-.22, .5),
                (-.22, .22), (-.5, .22), (-.5, -.22), (-.22, -.22)]
    sides = {"pentagon": 5, "hexagon": 6, "star": 10}[shape]
    return [((.23 if shape == "star" and i % 2 else .5) * math.cos(-math.pi / 2 + i * math.tau / sides),
             (.23 if shape == "star" and i % 2 else .5) * math.sin(-math.pi / 2 + i * math.tau / sides))
            for i in range(sides)]


def render_shape(shape, style, variant):
    """Construct an oversampled source image; all shading comes from downsampling."""
    mask = Image.new("L", (SIZE * SCALE, SIZE * SCALE), 0)
    draw = ImageDraw.Draw(mask)
    cx, cy = variant["center"]
    span = variant["span"]
    outline = style in ("outline", "negative-outline")
    options = dict(fill=None if outline else 255, outline=255,
                   width=max(1, round(variant["stroke"] * SCALE)) if outline else 1)
    if shape in ("circle", "square", "rectangle", "ellipse"):
        height = span * (0.6 if shape == "rectangle" else 0.7 if shape == "ellipse" else 1)
        bounds = [(cx - span / 2) * SCALE, (cy - height / 2) * SCALE,
                  (cx + span / 2) * SCALE, (cy + height / 2) * SCALE]
        method = draw.ellipse if shape in ("circle", "ellipse") else draw.rectangle
        method(bounds, **options)
    else:
        points = [((cx + x * span) * SCALE, (cy + y * span) * SCALE)
                  for x, y in polygon(shape)]
        draw.polygon(points, **options)
    if style == "hole":
        radius = 1.7 if span >= 15 else 1.5
        draw.ellipse([(cx - radius) * SCALE, (cy - radius) * SCALE,
                      (cx + radius) * SCALE, (cy + radius) * SCALE], fill=0)
    return mask if style.startswith("negative") else ImageOps.invert(mask)


def target_prompt(shape, style):
    name = "five-pointed star" if shape == "star" else shape
    article = "an" if name[0] in "aeiou" else "a"
    return {
        "filled": f"a filled black {name} on a white background",
        "outline": f"a black outline of {article} {name} on a white background",
        "negative": f"a white {name} cut out of a black background",
        "negative-outline": f"a white outline of {article} {name} on a black background",
        "hole": f"a filled black {name} with a small white circular hole on a white background",
    }[style]


def preview(artwork, scale=5):
    rows = artwork.splitlines()
    image = Image.new("L", (SIZE, SIZE))
    image.putdata([round(255 * (1 - PALETTE.index(symbol) / (len(PALETTE) - 1)))
                   for row in rows for symbol in row])
    return image.resize((SIZE * scale, SIZE * scale), Image.Resampling.NEAREST).convert("RGB")


def generate(output, start_id=13):
    output = Path(output)
    if start_id < 1:
        raise ValueError("Starting ID must be positive")
    output.mkdir(parents=True, exist_ok=False)
    (output / "previews").mkdir()
    records, seen = [], set()
    for shape in SHAPES:
        for style in STYLES:
            for variant in VARIANTS:
                example_id = start_id + len(records)
                prompt = target_prompt(shape, style)
                artwork = to_ascii(render_shape(shape, style, variant), SIZE)
                rows = artwork.splitlines()
                assert len(rows) == SIZE and all(len(row) == SIZE for row in rows)
                assert set(artwork) <= set(PALETTE + "\n")
                digest = hashlib.sha256(artwork.encode()).hexdigest()
                if digest in seen:
                    raise ValueError(f"Duplicate rendered artwork: {shape}, {style}, {variant['name']}")
                seen.add(digest)
                background = "#" if style.startswith("negative") else "."
                border = rows[0] + rows[-1] + "".join(row[0] + row[-1] for row in rows)
                assert set(border) == {background}, (shape, style, variant, "clipped border")
                assert 12 <= sum(c != background for row in rows for c in row) <= 300
                if style == "hole" or "outline" in style:
                    cx, cy = variant["center"]
                    assert rows[cy][cx] == background, (shape, style, variant, "missing interior")
                slug = re.sub(r"[^a-z0-9]+", "-", prompt).strip("-")
                filename = f"{example_id:03}-{slug}.txt"
                (output / filename).write_text(prompt + "\n" + artwork + "\n", encoding="utf-8")
                records.append(dict(id=f"{example_id:03}", file=filename, prompt=prompt,
                                    shape=shape, style=style, variant=variant,
                                    family_id=shape, variant_id=f"{shape}-{variant['name']}",
                                    sha256=digest))
    assert len(records) == 250
    manifest = dict(version=1, size=SIZE, palette=PALETTE, supersampling=SCALE,
                    generator="generate_shapes.py", provenance="procedurally constructed geometry",
                    records=len(records), shapes=dict(Counter(r["shape"] for r in records)),
                    styles=dict(Counter(r["style"] for r in records)), examples=records)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    make_previews(output, records)
    print(f"Created {len(records)} unique {SIZE}x{SIZE} references in {output.resolve()}")
    return output


def make_previews(output, records):
    """Render the quantized text itself so previews show exactly what Jev receives."""
    style_labels = ("Filled", "Outline", "White cutout", "White outline", "Circular hole")
    overview = Image.new("RGB", (1195, 715), "#eeeeee")
    overall = ImageDraw.Draw(overview)
    overall.text((10, 10), "250 references - five variants per style - rendered from the actual ASCII grids", fill="black")
    for col, label in enumerate(style_labels):
        overall.text((90 + col * 220, 35), label, fill="black")
    for shape_index, shape in enumerate(SHAPES):
        sheet = Image.new("RGB", (680, 685), "#eeeeee")
        draw = ImageDraw.Draw(sheet)
        draw.text((15, 10), f"{shape.upper()} - actual 20x20 ASCII pixels", fill="black")
        for style_index, label in enumerate(style_labels):
            draw.text((35 + style_index * 130, 35), label, fill="black")
        overall.text((8, 79 + shape_index * 64), shape, fill="black")
        for record in (r for r in records if r["shape"] == shape):
            style_index = STYLES.index(record["style"])
            variant_index = next(i for i, v in enumerate(VARIANTS) if v["name"] == record["variant"]["name"])
            artwork = (output / record["file"]).read_text().split("\n", 1)[1]
            x, y = 25 + style_index * 130, 70 + variant_index * 120
            sheet.paste(preview(artwork), (x, y))
            draw.text((x, y - 15), f"{record['id']} {record['variant']['name']}", fill="black")
            ox, oy = 90 + style_index * 220 + variant_index * 44, 65 + shape_index * 64
            overview.paste(preview(artwork, 2), (ox, oy))
        sheet.save(output / "previews" / f"{shape}.png")
    overview.save(output / "overview.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("dataset/gold/shapes-250"))
    parser.add_argument("--start-id", type=int, default=13)
    args = parser.parse_args()
    try:
        generate(args.output_dir, args.start_id)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
