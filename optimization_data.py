"""Deterministic preference tasks; gold art and labels are evaluation-only."""

from hashlib import sha256
import json
from pathlib import Path
import random

from prompts import PALETTE

DATASET = Path(__file__).parent / "dataset/gold/shapes-250"
# Keep near relatives together, as well as every variant and corruption of a source.
FAMILIES = {
    "train": ("triangle", "pentagon", "hexagon", "star", "cross"),
    "validation": ("circle", "ellipse"),
    "test": ("square", "rectangle", "diamond"),
}
STYLE_DISTRACTOR = {
    "filled": "outline", "outline": "filled", "negative": "negative-outline",
    "negative-outline": "negative", "hole": "filled",
}


def load_references(directory=DATASET):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["palette"] != PALETTE or manifest["size"] != 20:
        raise ValueError("Expected the 20x20 five-level reference dataset")
    records = []
    for entry in manifest["examples"]:
        path = directory / entry["file"]
        if path.resolve().parent != directory.resolve():
            raise ValueError("Reference path must stay inside the dataset")
        prompt, *rows = path.read_text().splitlines()
        art = "\n".join(rows)
        if (prompt != entry["prompt"] or len(rows) != 20
                or any(len(row) != 20 or set(row) - set(PALETTE) for row in rows)
                or sha256(art.encode()).hexdigest() != entry["sha256"]):
            raise ValueError(f"Invalid reference: {entry['file']}")
        records.append({**entry, "art": art})
    ids = [entry["id"] for entry in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate reference IDs")
    return records


def corrupt(art, positions, count):
    """Nested damage to distinct pixels; each edit increases reference pixel error."""
    pixels = list(art.replace("\n", ""))
    for index in positions[:count]:
        pixels[index] = PALETTE[4 if PALETTE.index(pixels[index]) <= 2 else 0]
    return "\n".join("".join(pixels[i:i + 20]) for i in range(0, 400, 20))


def build_comparisons(directory=DATASET, seed=0):
    records = load_references(directory)
    lookup = {(r["shape"], r["style"], r["variant"]["name"]): r for r in records}
    splits = {name: [] for name in FAMILIES}
    for record in records:
        split = next((name for name, shapes in FAMILIES.items() if record["shape"] in shapes), None)
        if split is None:
            raise ValueError(f"Assign a split for family {record['shape']}")
        rng = random.Random(f"{seed}:{record['id']}")
        positions = rng.sample(range(400), 400)
        wrong_style = lookup[(record["shape"], STYLE_DISTRACTOR[record["style"]],
                              record["variant"]["name"])]["art"]
        pairs = [
            ("local_damage", corrupt(record["art"], positions, 4), corrupt(record["art"], positions, 12)),
            ("heavy_damage", corrupt(record["art"], positions, 40), corrupt(record["art"], positions, 120)),
            ("style", record["art"], wrong_style),
        ]
        for kind, better, worse in pairs:
            if better == worse:
                raise ValueError("A preference pair must contain different images")
            for order in (0, 1):
                splits[split].append(dict(
                    prompt=record["prompt"], candidates=[better, worse] if order == 0 else [worse, better],
                    winner=order, source_id=record["id"], family=record["family_id"],
                    style=record["style"], kind=kind, pair_id=f"{record['id']}:{kind}", order=order,
                ))
    return splits
