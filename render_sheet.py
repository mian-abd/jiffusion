"""Render run frames to a PNG contact sheet without extra dependencies."""

import argparse
from pathlib import Path
import struct
import zlib

from jiffusion import PALETTE

SCALE, GAP, BACKGROUND = 8, 12, 96


def parse_grid(text):
    return [[PALETTE.index(char) for char in line] for line in text.rstrip("\n").split("\n")]


def frames_from_run(run, steps=None):
    """Frames saved in frames.md: all steps, or the listed 1-based step numbers."""
    blocks = (run / "frames.md").read_text(encoding="utf-8").split("```text\n")[1:]
    frames = [parse_grid(block.split("```")[0]) for block in blocks]
    if steps is None:
        return frames
    return [frames[min(step, len(frames)) - 1] for step in steps]


def write_png(path, rows):
    """Write 8-bit grayscale PNG from a list of equal-length byte rows."""
    height, width = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + bytes(row) for row in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def sheet(grids, columns):
    """Tile grids left to right, wrapping after `columns`; white=255, black=0."""
    size = max(len(grid) for grid in grids)
    tile = size * SCALE + GAP
    rows_count = (len(grids) + columns - 1) // columns
    canvas = [[BACKGROUND] * (columns * tile + GAP) for _ in range(rows_count * tile + GAP)]
    for index, grid in enumerate(grids):
        top, left = GAP + (index // columns) * tile, GAP + (index % columns) * tile
        for y, row in enumerate(grid):
            for x, value in enumerate(row):
                shade = round(255 * (4 - value) / 4)
                for dy in range(SCALE):
                    canvas[top + y * SCALE + dy][left + x * SCALE:left + (x + 1) * SCALE] = [shade] * SCALE
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="run directories")
    parser.add_argument("--steps", type=int, nargs="*", help="show these steps of each run (default: final only)")
    parser.add_argument("--columns", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    grids = []
    for run in args.runs:
        frames = frames_from_run(run, args.steps or None)
        grids.extend(frames if args.steps else frames[-1:])
    columns = args.columns or (len(args.steps) if args.steps else len(args.runs))
    write_png(args.output, sheet(grids, columns))
    print(f"Wrote {args.output.resolve()} ({len(grids)} frames, {columns} per row)")


if __name__ == "__main__":
    main()
