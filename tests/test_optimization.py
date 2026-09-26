import ast
from collections import Counter
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

if importlib.util.find_spec("dspy") is None:
    raise unittest.SkipTest("Install optimization dependencies with uv sync --extra optimize")

import optimize_prompts as opt
from dspy.utils import DummyLM
from optimization_data import build_comparisons
from prompts import ASCII_LEGEND, CHOICE_INSTRUCTIONS, PROPOSAL_POLICY
from test_jiffusion import choose_last


class OptimizationTests(unittest.TestCase):
    def test_family_splits_and_mirrored_labels(self):
        splits = build_comparisons()
        self.assertEqual({name: len(rows) for name, rows in splits.items()},
                         {"train": 750, "validation": 300, "test": 450})
        seen = set()
        seen_art = set()
        for rows in splits.values():
            ids = {row["source_id"] for row in rows}
            self.assertFalse(seen & ids)
            seen |= ids
            artwork = {art for row in rows for art in row["candidates"]}
            self.assertFalse(seen_art & artwork)
            seen_art |= artwork
            for left, right in zip(rows[::2], rows[1::2]):
                self.assertEqual(left["candidates"], right["candidates"][::-1])
                self.assertEqual(left["winner"], 0)
                self.assertEqual(right["winner"], 1)
                self.assertNotEqual(*left["candidates"])
            self.assertEqual(Counter(row["winner"] for row in rows)[0], len(rows) // 2)
        self.assertEqual(len(seen), 250)
        self.assertEqual(splits, build_comparisons())
        self.assertNotEqual(splits, build_comparisons(seed=1))

    def test_labels_and_metadata_do_not_enter_model_inputs(self):
        rows = build_comparisons()["train"][:2]
        for example in opt.examples(rows):
            self.assertEqual(set(example.inputs().keys()), {"prompt", "candidates"})

    def test_signature_instructions_reach_production_request_and_cache_is_scoped(self):
        client = Mock()
        client.system_one.side_effect = choose_last
        with tempfile.TemporaryDirectory() as directory:
            backend = opt.JevBackend(client, directory)
            selector = opt.ArtworkSelector(backend)
            updated = "Choose the candidates whose overall image best matches prompt, using the legend."
            selector.select.signature = selector.select.signature.with_instructions(updated)
            self.assertIs(selector.deepcopy().select.backend, backend)
            for _ in range(2):
                self.assertEqual(selector(prompt="an unfamiliar object", candidates=[".", "#"]).winner, 1)
            self.assertEqual(client.system_one.call_count, 1)
            request = client.system_one.call_args.kwargs
            self.assertEqual(set(request["state"]), {"prompt", "legend", "candidates"})
            self.assertEqual(request["state"]["legend"], ASCII_LEGEND)
            self.assertEqual(request["questions"]["best"].instructions, updated)
            selector.select.signature = selector.select.signature.with_instructions(CHOICE_INSTRUCTIONS)
            selector(prompt="an unfamiliar object", candidates=[".", "#"])
            self.assertEqual(client.system_one.call_count, 2)

    def test_shape_specific_proposals_and_demos_cannot_reach_jev(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            program = opt.ArtworkSelector(opt.JevBackend(client, directory),
                                          "If prompt is a circle, prefer round candidates.")
            self.assertEqual(program(prompt="a circle", candidates=[".", "#"]).winner, -1)
            client.system_one.assert_not_called()
            program.select.demos = [opt.dspy.Example(prompt="anything", candidates=[".", "#"], winner=0)]
            with self.assertRaisesRegex(ValueError, "Demonstrations"):
                program(prompt="anything", candidates=[".", "#"])

    def test_service_errors_are_not_cached_as_labels_and_budget_stops_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            client.system_one.side_effect = RuntimeError("unavailable")
            backend = opt.JevBackend(client, directory, max_calls=1)
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                backend.pick(CHOICE_INSTRUCTIONS, "artwork", [".", "#"])
            self.assertEqual(backend.cache, {})
            with self.assertRaisesRegex(RuntimeError, "budget"):
                backend.pick(CHOICE_INSTRUCTIONS, "artwork", [".", "#"])
            self.assertEqual(client.system_one.call_count, 1)

    def test_export_changes_only_instruction_constant(self):
        instruction = "Choose from candidates using prompt and the legend; compare the overall image."
        source = Path(opt.__file__).with_name("prompts.py")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "prompts.py"
            opt.export_prompt(instruction, source, target)
            before, after = ast.parse(source.read_text()), ast.parse(target.read_text())
            def constants(tree):
                return {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                        if isinstance(node, ast.Assign)}
            expected = constants(before)
            expected["CHOICE_INSTRUCTIONS"] = instruction
            self.assertEqual(constants(after), expected)

    def test_proxy_expands_n_into_individual_calls(self):
        lm = opt.VibeProxyLM("openai/test", api_base="http://localhost:8317/v1", api_key="placeholder", cache=False)
        with patch.object(opt.dspy.LM, "__call__", side_effect=[["one"], ["two"]]) as call:
            self.assertEqual(lm("input", n=2), ["one", "two"])
            self.assertEqual([entry.kwargs["n"] for entry in call.call_args_list], [1, 1])

    def test_real_copro_pipeline_with_fake_services(self):
        instruction = "Compare candidates against prompt as a complete image, using the provided legend."
        proposal = DummyLM([dict(proposed_instruction=instruction, proposed_prefix_for_output_field="Winner:")])
        proposal.inspect_history = Mock()
        # Controlled backend: proposed instruction is better on training/validation,
        # but fails the held-out test. Test must not change the selected instruction.
        class Backend:
            model, calls = "fake-jev", 0
            def __deepcopy__(self, memo):
                return self
            def pick(self, instructions, prompt, candidates):
                self.calls += 1
                return int(instructions != instruction or prompt == "held out")
        row = dict(prompt="arbitrary art", candidates=[".", "#"], winner=0, family="fake",
                   style="filled", kind="style", pair_id="one", order=0)
        splits = {"train": [row], "validation": [row], "test": [{**row, "prompt": "held out"}]}
        with tempfile.TemporaryDirectory() as directory:
            report = opt.optimize(Backend(), proposal, splits, directory, breadth=2, depth=1, threads=1)
            self.assertEqual(report["instructions"], instruction)
            self.assertEqual(report["test_selected"]["accuracy"], 0)
            self.assertTrue(report["improved_on_validation"])
            self.assertFalse(report["deployment_approved"])
            self.assertIn(PROPOSAL_POLICY, proposal.history[0]["messages"][0]["content"])
            self.assertNotIn("arbitrary art", str(proposal.history[0]["messages"]))
            state = json.loads((Path(directory) / "selector.json").read_text())
            self.assertEqual(state["select"]["demos"], [])


if __name__ == "__main__":
    unittest.main()
