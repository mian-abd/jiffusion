# 250 primary-shape references

Exactly 250 unique text records, IDs `013`–`262`. Each file contains its target prompt on the first line and a 20×20 ASCII image on the next 20 lines. The only artwork symbols are `.:-=#`, ordered from white to black.

The set contains 25 examples of each shape: circle, square, triangle, rectangle, ellipse, diamond, pentagon, hexagon, five-pointed star, and cross.

There are 50 examples of each style:

- Filled black shape on white.
- Black outline on white.
- White shape cut out of a black background.
- White outline on black.
- Filled black shape with a small circular white hole.

Each shape/style combination has five size and position variants: large, small, left, right, and upper. Outline widths also vary. Prompts describe the shape, fill, and polarity without requiring a particular position.

All artwork is constructed from geometry at 320×320, then passed through the project's image-to-ASCII converter. No API or generative model labels the examples. Gray levels represent antialiased edges; no dithering or random pixel noise is added.

The [overview](overview.png) and [per-shape contact sheets](previews) are reconstructed from the actual quantized text, so they show exactly the grid values in the records. All ten contact sheets were visually reviewed. Automated checks verify dimensions, vocabulary, unique artwork, unclipped borders, connected foregrounds, and the intended number of enclosed holes.

[manifest.json](manifest.json) records each ID, filename, prompt, shape, style, geometric parameters, and an artwork hash. `family_id` groups all 25 versions of a primitive together; `variant_id` identifies its size/position configuration. These are controlled variations of ten primitive families, not 250 unrelated drawings. Keep related examples and their later corruptions together when designing train/test splits.

To reproduce the batch in a fresh directory, run from the project root:

```sh
uv run generate_shapes.py --output-dir /tmp/shapes-250-rebuilt --start-id 13
```

Existing output directories are refused. [The DSPy optimizer](../../../optimize_prompts.py) derives paired damage/style comparisons from these clean targets and holds entire related families together across training, validation, and test. See the [optimization workflow](../../../README.md#optimize-the-shared-instruction-with-dspy).
