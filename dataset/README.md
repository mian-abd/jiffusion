# Clipart references

The [shapes-250 batch](gold/shapes-250) contains 250 generated primary-shape references, IDs `013`–`262`. It balances ten shapes, five styles, and five size/position variants. Browse the [overview](gold/shapes-250/overview.png) or [batch details](gold/shapes-250/README.md). The ten earlier starter files remain in `gold/`; use `Path("dataset/gold").rglob("*.txt")` to include nested batches, or select the batch directory to load exactly 250 records.

Each reference is one plain-text file in `gold/`:

```text
003-a-filled-circle.txt
004-a-circle-outline.txt
263-a-duck.txt
```

The filename starts with a stable ID padded to at least three digits, followed by a readable prompt slug. Multiple drawings can have the same prompt with different IDs.

The first line is the exact target prompt. Everything after its first newline is the ASCII artwork. There is no metadata header or required separator. Any blank line after the prompt is part of the canvas.

Use a monospace font when viewing or editing. Files use UTF-8 with LF line endings. Converted artwork is a square grid, 20×20 by default, containing only the five characters in `PALETTE` in [prompts.py](../prompts.py):

| Character | Brightness | Approximate grayscale value |
| --- | --- | --- |
| `.` | White | 255 |
| `:` | Light gray | 191 |
| `-` | Medium gray | 128 |
| `=` | Dark gray | 64 |
| `#` | Black | 0 |

The Python generator, converter, and Jev legend use this same convention. The generator currently proposes binary pixels; the converter can produce all five levels. The prompt line is natural language and is not restricted to this palette.

Convert an image from the project root:

```sh
uv run image_to_ascii.py duck.png --prompt "a duck" --id 263
```

This creates `dataset/gold/263-a-duck.txt`. Use `--size 10` or `--size 5` for smaller square grids, and `--output-dir` for a different destination. Use separate destination trees for different resolutions of the same ID. Existing IDs anywhere inside a destination tree are rejected, even if the prompt slug differs.

The converter accepts raster formats supported by Pillow, such as PNG, JPEG, and WebP. It applies EXIF orientation, composites transparency onto white, converts to grayscale, resizes to fit the canvas while preserving aspect ratio, centers the image with white padding, and maps each pixel to its nearest allowed brightness level. It uses no dithering. Images in animated files use the first frame. No API key is needed.

Each character represents a square pixel for the model and renderer; terminal glyph proportions can make the text preview look taller.

For example, load a file without stripping its artwork:

```python
prompt, artwork = path.read_text(encoding="utf-8").split("\n", 1)
```

The two user-provided ducks are preserved verbatim in `examples/001-a-duck.txt` and `examples/002-a-duck.txt`, including spaces and their wider character vocabulary. These illustrate the file format and are not palette-valid training records. Keep their original whitespace when editing or loading them. Do not guess brightness mappings for those symbols; use the source images for conversion.

References `003`–`012` in `gold/` are newly authored starter drawings using the allowed palette. Review them before treating them as approved gold labels. No candidate preferences, train/test splits, or DSPy optimization results are claimed by this starter set. `263-a-duck.txt` in the command above is an example output filename; supply an actual input image to create it.

Later, comparison records can refer to these IDs while the reference artwork stays in these text files. Keep every derived mutation and resolution of one reference in the same dataset split.
