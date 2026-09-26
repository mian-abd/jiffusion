"""Optimize Jev instructions by scoring complete noise-to-image generation runs."""

import argparse
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from PIL import Image, ImageDraw
from typesafe_sdk import TypeSafeClient

from jiffusion import MODEL, run
from optimization_data import DATASET, FAMILIES, load_references
from optimize_prompts import dspy, ProposalAdapter, VibeProxyLM, export_prompt, validate_instructions
from prompts import CHOICE_INSTRUCTIONS, DIFFUSION_PROPOSAL_POLICY, PALETTE, PROPOSAL_POLICY


def build_tasks(styles=("filled",), seeds=(0, 1, 2), directory=DATASET):
    """One target per family/style, with all five placements used only for grading."""
    groups = defaultdict(list)
    for row in load_references(directory):
        if row["style"] in styles:
            groups[(row["shape"], row["style"], row["prompt"])].append(row["art"])
    splits = {name: [] for name in FAMILIES}
    for index, (split, families) in enumerate(FAMILIES.items()):
        for (family, style, prompt), references in groups.items():
            if family in families:
                splits[split].append(dict(prompt=prompt, seed=seeds[index], family=family,
                                         style=style, references=references))
    if any(not rows for rows in splits.values()):
        raise ValueError("Every split needs at least one task")
    return splits


def foreground_iou(art, reference):
    """Soft foreground IoU uses all five levels; empty background earns nothing."""
    rows, gold = art.splitlines(), reference.splitlines()
    if len(rows) != 20 or any(len(row) != 20 or set(row) - set(PALETTE) for row in rows):
        return 0.0
    background = PALETTE.index(gold[0][0]) / 4
    predicted = [abs(PALETTE.index(c) / 4 - background) for row in rows for c in row]
    expected = [abs(PALETTE.index(c) / 4 - background) for row in gold for c in row]
    union = sum(max(a, b) for a, b in zip(predicted, expected))
    return sum(min(a, b) for a, b in zip(predicted, expected)) / union if union else 0.0


def final_image_score(example, prediction, trace=None):
    return max(foreground_iou(prediction.art, reference) for reference in example.references)


class Rollouts:
    def __init__(self, output, *, steps=750, candidates=2, max_calls=24000, client_factory=TypeSafeClient):
        self.output = Path(output)
        self.steps, self.candidates, self.max_calls = steps, candidates, max_calls
        self.client_factory = client_factory
        self.cache = {}
        self.reserved_calls = 0
        self.lock = Lock()

    def __deepcopy__(self, memo):
        return self

    def generate(self, instructions, prompt, seed, selector="jev"):
        settings = dict(instructions=instructions, prompt=prompt, seed=seed, selector=selector,
                        steps=self.steps, candidates=self.candidates, model=MODEL, size=20)
        key = sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            if selector == "jev":
                if self.reserved_calls + self.steps > self.max_calls:
                    raise RuntimeError("Full-generation Jev call budget exhausted")
                self.reserved_calls += self.steps
        path = self.output / "rollouts" / key
        kwargs = dict(**settings, output=path, verbose=False)
        if selector == "jev":
            with self.client_factory(timeout=60) as client:
                run(client, **kwargs)
        else:
            run(None, **kwargs)
        result = dict(art=(path / "final.txt").read_text().rstrip("\n"), path=str(path))
        with self.lock:
            self.cache[key] = result
        print(f"Completed {selector}: {prompt}, seed {seed}, {self.steps} steps [{key[:8]}]", flush=True)
        return result


class GenerateArtwork(dspy.Signature):
    prompt: str = dspy.InputField()
    seed: int = dspy.InputField()
    art: str = dspy.OutputField()


class FullGeneration(dspy.Predict):
    """The optimizable instruction is applied at EVERY Jev call inside one rollout."""

    def __init__(self, rollouts, instructions=CHOICE_INSTRUCTIONS):
        super().__init__(GenerateArtwork.with_instructions(instructions))
        self.rollouts = rollouts

    def forward(self, *, prompt, seed):
        if self.demos:
            raise ValueError("Demonstrations are disabled")
        try:
            instructions = validate_instructions(self.signature.instructions)
        except ValueError:
            return dspy.Prediction(art="", path="")
        result = self.rollouts.generate(instructions, prompt, seed)
        return dspy.Prediction(**result)


def summarize(result):
    return dict(mean_iou=sum(score for _, _, score in result.results) / len(result.results),
                runs=[dict(prompt=example.prompt, family=example.family, style=example.style,
                           seed=example.seed, iou=score, path=prediction.path)
                      for example, prediction, score in result.results])


def make_gallery(splits, reports, output):
    """One row per target; render the real final grids with square pixels."""
    rows = [row for split in splits.values() for row in split]
    columns = ("reference", *reports)
    width, height = 185, 145
    canvas = Image.new("RGB", (width * len(columns), height * len(rows) + 35), "#eeeeee")
    draw = ImageDraw.Draw(canvas)
    for column, name in enumerate(columns):
        draw.text((column * width + 8, 10), name, fill="black")
    for index, row in enumerate(rows):
        for column, name in enumerate(columns):
            y = index * height + 35
            if name == "reference":
                art, label = row["references"][0], f"{row['family']} / {row['style']}"
            else:
                matches = [r for r in reports[name] if r["prompt"] == row["prompt"] and r["seed"] == row["seed"]]
                if not matches:
                    continue
                record = matches[0]
                art = (Path(record["path"]) / "final.txt").read_text().strip()
                label = f"IoU {record['iou']:.3f}, seed {row['seed']}"
            image = Image.new("L", (20, 20))
            image.putdata([round(255 * (4 - PALETTE.index(c)) / 4) for c in art if c != "\n"])
            canvas.paste(image.resize((100, 100), Image.Resampling.NEAREST), (column * width + 8, y + 24))
            draw.text((column * width + 8, y + 5), label, fill="black")
    canvas.save(Path(output) / "finals.png")


def optimize(rollouts, proposal_lm, splits, output, *, breadth=2, depth=2, threads=5):
    output = Path(output)
    data = {name: [dspy.Example(**row).with_inputs("prompt", "seed") for row in rows]
            for name, rows in splits.items()}
    baseline = FullGeneration(rollouts)
    options = dict(num_threads=threads, display_progress=False, display_table=False)
    copro = dspy.COPRO(prompt_model=proposal_lm, metric=final_image_score, breadth=breadth,
                       depth=depth, init_temperature=1.0)
    with dspy.context(adapter=ProposalAdapter(PROPOSAL_POLICY + DIFFUSION_PROPOSAL_POLICY), max_errors=1):
        compiled = copro.compile(baseline, trainset=data["train"], eval_kwargs=options)
    proposals = []
    for candidate in compiled.candidate_programs:
        try:
            validate_instructions(candidate["instruction"])
            valid = True
        except ValueError:
            valid = False
        proposals.append(dict(instructions=candidate["instruction"], train_iou=candidate["score"] / 100, valid=valid))
    (output / "proposals.json").write_text(json.dumps(proposals, indent=2) + "\n")
    # Freeze the strongest legal training candidate before validation/test.
    best = max((r for r in proposals if r["valid"]), key=lambda r: (r["train_iou"], -len(r["instructions"])))
    candidate = FullGeneration(rollouts, best["instructions"])
    evaluate = dspy.Evaluate(devset=data["validation"], metric=final_image_score, max_errors=1, **options)
    summaries = {}
    # Training evaluations reuse complete rollout results; no duplicate API requests.
    for name, program in (("baseline", baseline), ("candidate", candidate)):
        summaries[f"train_{name}"] = summarize(evaluate(program, devset=data["train"]))
        summaries[f"validation_{name}"] = summarize(evaluate(program))
    improved = summaries["validation_candidate"]["mean_iou"] > summaries["validation_baseline"]["mean_iou"]
    selected = candidate if improved else baseline
    selection = dict(instructions=selected.signature.instructions, validation_improved=improved)
    (output / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    # Report this already-fixed candidate even if validation vetoed it; no feedback to COPRO.
    for name, program in (("baseline", baseline), ("candidate", candidate)):
        summaries[f"test_{name}"] = summarize(evaluate(program, devset=data["test"]))
    random_rows = []
    for examples in data.values():
        for example in examples:
            result = dspy.Prediction(**rollouts.generate(CHOICE_INSTRUCTIONS, example.prompt, example.seed, "random"))
            random_rows.append(dict(prompt=example.prompt, family=example.family, style=example.style,
                                    seed=example.seed, path=result.path, iou=final_image_score(example, result)))
    deployment_approved = improved and summaries["test_candidate"]["mean_iou"] > summaries["test_baseline"]["mean_iou"]
    report = dict(objective="Mean final soft foreground IoU after full generation, NOT choice accuracy",
                  generator="grayscale-delta-patches-v3", palette=PALETTE,
                  steps=rollouts.steps, candidates=rollouts.candidates, size=20, families=FAMILIES,
                  proposal_model=proposal_lm.model, jev_model=MODEL, proposals=proposals,
                  baseline_instructions=CHOICE_INSTRUCTIONS, candidate_instructions=best["instructions"],
                  selection=selection, deployment_approved=deployment_approved,
                  jev_calls=rollouts.reserved_calls, summaries=summaries, random=random_rows,
                  limitations="Small pilot with one seed per target; fixed-pose geometric overlap is not semantic quality. "
                              "References affect only grading. No gain proves convergence or generalization to arbitrary objects.")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    export_prompt(best["instructions"], Path(__file__).with_name("prompts.py"), output / "candidate-prompts.py")
    make_gallery(splits, {"baseline": sum([summaries[f"{s}_baseline"]["runs"] for s in splits], []),
                         "candidate": sum([summaries[f"{s}_candidate"]["runs"] for s in splits], []),
                         "random": random_rows}, output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs") / datetime.now().strftime("diffusion-dspy-%Y%m%d-%H%M%S"))
    parser.add_argument("--steps", type=int, default=750)
    parser.add_argument("--candidates", type=int, default=2)
    parser.add_argument("--styles", nargs="+", choices=("filled", "outline", "negative", "negative-outline", "hole"), default=["filled"])
    parser.add_argument("--breadth", type=int, default=2)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--threads", type=int, default=5)
    parser.add_argument("--max-jev-calls", type=int, default=24000)
    parser.add_argument("--proposal-model", default="openai/gpt-6-astra")
    parser.add_argument("--proposal-base-url", default="http://localhost:8317/v1")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if min(args.steps, args.threads, args.depth, args.max_jev_calls) < 1 or args.breadth < 2 or not 2 <= args.candidates <= 255:
        parser.error("Use positive steps/depth/threads/budget, breadth >=2, and 2-255 candidates")
    splits = build_tasks(styles=tuple(dict.fromkeys(args.styles)))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "tasks.json").write_text(json.dumps(splits, indent=2) + "\n")
    manifest = dict(status="prepared", settings={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                    dataset_sha256=sha256(json.dumps(splits, sort_keys=True).encode()).hexdigest(),
                    protocol="Fixed resolution, five-level palette, patch and brightness limits taper 4/2/1, no current-frame option. "
                             "Train seed 0; validation seed 1; test seed 2. Compare final image only.")
    manifest_path = args.output / "run.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if args.prepare_only:
        print(f"Prepared {sum(map(len, splits.values()))} full-generation tasks at {args.output}")
        return
    load_dotenv(Path(__file__).with_name(".env"))
    if not os.environ.get("TYPESAFE_API_KEY"):
        parser.error("Set TYPESAFE_API_KEY in .env")
    lm = VibeProxyLM(args.proposal_model, api_base=args.proposal_base_url,
                     api_key=os.environ.get("VIBE_PROXY_API_KEY", "vibeproxy"), temperature=1.0,
                     max_tokens=4000, timeout=120, num_retries=1, cache=False)
    rollouts = Rollouts(args.output, steps=args.steps, candidates=args.candidates, max_calls=args.max_jev_calls)
    try:
        manifest["status"] = "running"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        optimize(rollouts, lm, splits, args.output, breadth=args.breadth, depth=args.depth, threads=args.threads)
        manifest["status"] = "complete"
    except BaseException:
        manifest["status"] = "failed"
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Results: {args.output / 'report.json'}", flush=True)


if __name__ == "__main__":
    main()
