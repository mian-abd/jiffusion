"""DSPy COPRO instruction optimization: Vibe Proxy proposes, Jev selects."""

import argparse
import ast
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from pprint import pformat
import re
from threading import Lock

# Keep optional DSPy caches with ignored experiment output, not in the user's home.
os.environ.setdefault("DSPY_CACHEDIR", str(Path(__file__).parent / "runs/.dspy-cache"))
import dspy
from dotenv import load_dotenv
from typesafe_sdk import TypeSafeClient

from jiffusion import MODEL, jev_pick_ascii
from optimization_data import DATASET, FAMILIES, build_comparisons
from prompts import ASCII_LEGEND, CHOICE_INSTRUCTIONS, PROPOSAL_POLICY


def validate_instructions(instructions):
    """Reject obvious specialization. This guard is not a proof of generalization."""
    if not isinstance(instructions, str) or not 20 <= len(instructions) <= 1200:
        raise ValueError("Instructions must contain 20-1200 characters")
    banned = (r"\b(circl\w*|round\w*|squar\w*|triang\w*|rectang\w*|ellip\w*|oval\w*|"
              r"diamond\w*|pentagon\w*|hexagon\w*|stars?|cross(?:es)?|ducks?|"
              r"c\d+|dataset\w*|gold|reference|training|examples?|templates?)\b")
    if re.search(banned, instructions, re.I) or re.search(r"[.:=\-#]{5,}", instructions):
        raise ValueError("Instructions contain a named shape, template, ID, or evaluation-only concept")
    if "prompt" not in instructions.lower() or "candidates" not in instructions.lower():
        raise ValueError("Instructions must reference prompt and candidates")
    return instructions


class ProposalAdapter(dspy.ChatAdapter):
    def __init__(self, policy=PROPOSAL_POLICY):
        super().__init__()
        self.policy = policy

    def __call__(self, lm, lm_kwargs, signature, demos, inputs):
        signature = signature.with_instructions(self.policy + "\n\n" + signature.instructions)
        return super().__call__(lm, lm_kwargs, signature, demos, inputs)


class VibeProxyLM(dspy.LM):
    """The proxy returns one completion even when n>1; expand n into serial calls."""

    def __call__(self, prompt=None, messages=None, **kwargs):
        count = kwargs.pop("n", 1)
        outputs = []
        for _ in range(count):
            outputs.extend(super().__call__(prompt=prompt, messages=messages, n=1, **kwargs))
        return outputs

    def inspect_history(self, n=1, file=None):
        # COPRO calls this inside debug f-strings even when debug logging is off.
        # Proposals and scores already have a dedicated artifact.
        return None


class JevBackend:
    def __init__(self, client, output, model=MODEL, max_calls=10000):
        self.client, self.model = client, model
        self.output = Path(output)
        self.cache = {}
        self.lock = Lock()
        self.calls = 0
        self.max_calls = max_calls

    def __deepcopy__(self, memo):
        # DSPy clones prompt parameters, while all clones share this service/cache.
        return self

    def pick(self, instructions, prompt, candidates):
        request = dict(model=self.model, instructions=instructions, prompt=prompt,
                       legend=ASCII_LEGEND, candidates=candidates)
        key = sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            if self.calls >= self.max_calls:
                raise RuntimeError("Jev evaluation call budget exhausted")
            self.calls += 1
        winner, detail = jev_pick_ascii(self.client, prompt, candidates, model=self.model,
                                      instructions=instructions)
        with self.lock:
            self.cache[key] = winner
            with (self.output / "jev-calls.jsonl").open("a") as stream:
                stream.write(json.dumps(dict(key=key, request=request, winner=winner, detail=detail)) + "\n")
        return winner


class SelectArtwork(dspy.Signature):
    prompt: str = dspy.InputField()
    candidates: list[str] = dspy.InputField()
    winner: int = dspy.OutputField()


class JevPredict(dspy.Predict):
    """A learnable DSPy signature, executed by the exact production Choice request."""

    def __init__(self, backend, instructions=CHOICE_INSTRUCTIONS):
        super().__init__(SelectArtwork.with_instructions(instructions))
        self.backend = backend

    def forward(self, *, prompt, candidates):
        if self.demos:
            raise ValueError("Demonstrations are disabled for this selector")
        try:
            instructions = validate_instructions(self.signature.instructions)
        except ValueError:
            # COPRO can discard an invalid proposal without making any Jev calls.
            return dspy.Prediction(winner=-1, valid=False)
        winner = self.backend.pick(instructions, prompt, candidates)
        return self._forward_postprocess([{"winner": winner}], self.signature,
                                         prompt=prompt, candidates=candidates)


class ArtworkSelector(dspy.Module):
    def __init__(self, backend, instructions=CHOICE_INSTRUCTIONS):
        super().__init__()
        self.select = JevPredict(backend, instructions)

    def forward(self, prompt, candidates):
        return self.select(prompt=prompt, candidates=candidates)


def accuracy(example, prediction, trace=None):
    return float(prediction.winner == example.winner)


def examples(rows):
    return [dspy.Example(**row).with_inputs("prompt", "candidates") for row in rows]


def summarize(result):
    buckets = defaultdict(list)
    pairs = defaultdict(list)
    for example, prediction, score in result.results:
        for name in ("family", "style", "kind", "order"):
            buckets[f"{name}:{getattr(example, name)}"].append(score)
        pairs[example.pair_id].append(score)
    return dict(
        accuracy=result.score / 100, comparisons=len(result.results),
        both_orders_correct=sum(all(scores) for scores in pairs.values()) / len(pairs),
        breakdown={name: sum(scores) / len(scores) for name, scores in sorted(buckets.items())},
    )


def export_prompt(instructions, source, destination):
    """Replace only the constant's expression; never execute generated Python."""
    validate_instructions(instructions)
    source = Path(source).read_text()
    tree = ast.parse(source)
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "CHOICE_INSTRUCTIONS" for t in node.targets)]
    if len(assignments) != 1:
        raise ValueError("Expected one CHOICE_INSTRUCTIONS assignment")
    node = assignments[0]
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [f"CHOICE_INSTRUCTIONS = {pformat(instructions, width=96)}\n"]
    destination = Path(destination)
    destination.write_text("".join(lines))


def optimize(backend, proposal_lm, splits, output, *, breadth=3, depth=2, threads=4):
    output = Path(output)
    data = {name: examples(rows) for name, rows in splits.items()}
    baseline = ArtworkSelector(backend)
    eval_kwargs = dict(num_threads=threads, display_progress=False, display_table=False)
    optimizer = dspy.COPRO(prompt_model=proposal_lm, metric=accuracy, breadth=breadth,
                           depth=depth, init_temperature=1.0)
    # COPRO sees only instructions and aggregate training scores, never the art or shape names.
    with dspy.context(adapter=ProposalAdapter(), max_errors=1):
        compiled = optimizer.compile(baseline, trainset=data["train"], eval_kwargs=eval_kwargs)
    proposals = []
    for candidate in compiled.candidate_programs:
        instruction = candidate["instruction"]
        try:
            validate_instructions(instruction)
            valid = True
        except ValueError:
            valid = False
        proposals.append(dict(instructions=instruction, training_accuracy=candidate["score"] / 100, valid=valid))
    (output / "proposals.json").write_text(json.dumps(proposals, indent=2) + "\n")
    # Choose the best legal training candidate; ties keep the shorter instruction.
    legal = [row for row in proposals if row["valid"]]
    best = max(legal, key=lambda row: (row["training_accuracy"], -len(row["instructions"])))
    candidate = ArtworkSelector(backend, best["instructions"])
    evaluate = dspy.Evaluate(devset=data["validation"], metric=accuracy, max_errors=1, **eval_kwargs)
    validation_before = evaluate(baseline)
    validation_after = evaluate(candidate)
    # Freeze the decision before touching the test labels. No gain => keep the original.
    improved = validation_after.score > validation_before.score
    selected = candidate if improved else baseline
    instruction = selected.select.signature.instructions
    (output / "selected.json").write_text(json.dumps(dict(
        instructions=instruction, selected_on="validation", improved=improved,
        baseline_validation=summarize(validation_before), candidate_validation=summarize(validation_after),
    ), indent=2) + "\n")
    export_prompt(instruction, Path(__file__).with_name("prompts.py"), output / "prompts.py")
    selected.save(str(output / "selector.json"))
    # The final test cannot influence selection or proposals. It may veto deployment.
    test_before = evaluate(baseline, devset=data["test"])
    test_after = evaluate(selected, devset=data["test"])
    report = dict(
        optimizer="DSPy COPRO, instruction only", dspy_version=dspy.__version__,
        model=backend.model, proposal_model=proposal_lm.model, families=FAMILIES,
        split_sizes={name: len(rows) for name, rows in splits.items()},
        instructions=instruction, improved_on_validation=improved,
        deployment_approved=improved and test_after.score > test_before.score,
        validation_baseline=summarize(validation_before), validation_candidate=summarize(validation_after),
        test_baseline=summarize(test_before), test_selected=summarize(test_after),
        jev_calls=backend.calls, proposals=proposals,
        limitations="Synthetic reconstruction/style preferences, not human semantic judgments. "
                    "Mirrored orders and variants are correlated. Unseen primitive families are not arbitrary clipart. "
                    "Pairwise accuracy does not establish success from random noise or with larger candidate sets.",
    )
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path, default=Path("runs") / ("dspy-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    parser.add_argument("--proposal-base-url", default="http://localhost:8317/v1")
    parser.add_argument("--proposal-model", default="openai/gpt-6-astra")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--breadth", type=int, default=3)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-jev-calls", type=int, default=10000)
    parser.add_argument("--prepare-only", action="store_true", help="Build splits without any API calls")
    parser.add_argument("--apply", action="store_true", help="Apply only if validation AND final test improve")
    args = parser.parse_args()
    if args.breadth < 2 or min(args.depth, args.threads, args.max_jev_calls) < 1:
        parser.error("breadth must be >=2 and depth, threads, and call budget must be positive")
    splits = build_comparisons(args.dataset, args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, rows in splits.items():
        (args.output / f"{name}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = dict(status="prepared", applied=False, created_at=datetime.now(timezone.utc).isoformat(),
                    arguments={key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
                    families=FAMILIES, sizes={key: len(rows) for key, rows in splits.items()},
                    dataset_sha256=sha256(json.dumps(splits, sort_keys=True).encode()).hexdigest())
    manifest_path = args.output / "run.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Prepared {manifest['sizes']} at {args.output}", flush=True)
    if args.prepare_only:
        return
    load_dotenv(Path(__file__).with_name(".env"))
    if not os.environ.get("TYPESAFE_API_KEY"):
        parser.error("Add TYPESAFE_API_KEY to .env")
    # Proxy owns authentication. The placeholder is not an OpenAI credential.
    proposal_lm = VibeProxyLM(args.proposal_model, api_base=args.proposal_base_url,
                             api_key=os.environ.get("VIBE_PROXY_API_KEY", "vibeproxy"),
                             temperature=1.0, max_tokens=4000, timeout=120, num_retries=1, cache=False)
    try:
        with TypeSafeClient(api_key=os.environ["TYPESAFE_API_KEY"], timeout=60) as client:
            backend = JevBackend(client, args.output, model=args.model, max_calls=args.max_jev_calls)
            report = optimize(backend, proposal_lm, splits, args.output,
                              breadth=args.breadth, depth=args.depth, threads=args.threads)
        if args.apply and report["deployment_approved"]:
            path = Path(__file__).with_name("prompts.py")
            export_prompt(report["instructions"], path, path)
            manifest["applied"] = True
        manifest["status"] = "complete"
        print(json.dumps({key: report[key] for key in
                          ("improved_on_validation", "deployment_approved", "jev_calls")}), flush=True)
        print(f"Results: {args.output / 'report.json'}", flush=True)
    except BaseException:
        manifest["status"] = "failed"
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
