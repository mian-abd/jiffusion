"""Exact prompt text sent to Jev by the grid search.

The target goes in state.prompt, the legend in state.legend, and the
selection question in questions.best.instructions. A CLI positional prompt
overrides DEFAULT_PROMPT. The generated ASCII grids go in state.candidates.
"""

# Light to dark; shared by the generator and image-to-ASCII converter.
PALETTE = ".:-=#"

DEFAULT_PROMPT = "a circle"

EXPLICIT_CIRCLE_PROMPT = (
    "One filled black disk on a white background, with a smooth round boundary."
)

ASCII_LEGEND = (
    "Each candidate is ASCII art, not prose. Each character represents one square pixel: "
    ". is white, : is light gray, - is medium gray, = is dark gray, and # is black. "
    "Newlines separate rows, top to bottom. "
    "Read the arrangement of characters as a two-dimensional image."
)

CHOICE_INSTRUCTIONS = (
    "Which ASCII-art grid in `candidates` best depicts `prompt`? "
    "Choose the closest visual resemblance, even if all candidates are poor."
)

# Only the shared Choice instructions are optimized. Never optimize the target or legend.
PROPOSAL_POLICY = (
    "Optimize one universal instruction for a text-only visual selector. The state contains "
    "`prompt` (the requested image), `legend` (the fixed brightness encoding), and "
    "`candidates` (candidate IDs mapped to ASCII pixel grids). The selector returns one ID. "
    "Read the grids as two-dimensional images using the legend. Keep the instruction under "
    "1200 characters. It must work for arbitrary objects, artwork, backgrounds, and styles. "
    "Do not name any particular shape or object, describe a particular object's geometry, "
    "provide examples or ASCII templates, or add conditional rules for particular targets. "
    "Do not mention datasets, gold references, labels, corruption levels, or training. "
    "Do not favor a candidate ID, candidate order, a fixed color, fill, symmetry, size, "
    "or position. These preferences must come from the requested image. "
    "Only propose the selection instruction; the caller already supplies the legend. "
    "The output prefix is unused by the typed selector; keep it as Winner:."
)

DIFFUSION_PROPOSAL_POLICY = (
    " The instruction is reused at every step of a generation loop starting from random "
    "pixels. Each step offers only fresh mutations; the current image cannot be kept. "
    "Scores measure the final image after the entire loop, not isolated choice accuracy. "
    "Seek consistent progress toward the requested appearance even when all choices look "
    "like noise. Do not put this optimization setup or the scoring metric in the instruction."
)
