from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import Mock

from typesafe_sdk import SystemOneResponse

from jiffusion import (CURRENT, DENOISERS, KEEP, LEVELS, MIN_EXTENT, MODEL, PRIMITIVES, TRANSFORMS,
                       anneal, blend, blob_from_noise, composition, denoise, footprint, jev_pick, jev_score, largest_component,
                       mutate, noise, noise_grid, render, run, schedule, transform)


def respond(choice, keys):
    return SystemOneResponse(
        model=MODEL, usage={"input_tokens": 100, "output_tokens": 10},
        answers={"best": {"type": "choice", "choice": choice, "confidence": 1.0,
                          "probabilities": {key: float(key == choice) for key in keys}}},
    )


def choose_last(**request):
    keys = list(request["questions"]["best"].criteria)
    return respond([key for key in keys if key != KEEP][-1], keys)


def choose_keep(**request):
    keys = list(request["questions"]["best"].criteria)
    return respond(KEEP if KEEP in keys else keys[0], keys)


def score_by_ink(**request):
    """Fake Score: more black pixels -> higher score, so the loop accepts only darker frames.
    Also answers the confirmation Choice by picking the darker of the two grids."""
    if "best" in request["questions"]:
        keys = list(request["questions"]["best"].criteria)
        darker = max(keys, key=lambda key: request["state"]["candidates"][key].count("█"))
        return respond(darker, keys)
    answers = {}
    for key, text in request["state"]["frames"].items():
        pixels = len(text.replace("\n", ""))
        score = min(3.0, 3.0 * text.count("█") / pixels)
        answers[key] = {"type": "score", "score": score, "confidence": 0.9,
                        "legend": dict(enumerate(LEVELS)),
                        "probabilities": {i: float(i == round(score)) for i in range(4)}}
    return SystemOneResponse(model=MODEL, usage={"input_tokens": 100, "output_tokens": 10}, answers=answers)


class GridTests(unittest.TestCase):
    def test_noise_grid_is_seeded_grayscale_noise(self):
        for size in (1, 3, 20, 21):
            grid = noise_grid(size, random.Random(7))
            self.assertEqual(grid, noise_grid(size, random.Random(7)))
            self.assertEqual(len(grid), size)
            self.assertTrue(all(len(row) == size for row in grid))
            self.assertTrue({v for row in grid for v in row} <= {0, 1, 2, 3, 4})
        self.assertEqual({v for row in noise_grid(20, random.Random(0)) for v in row}, {0, 1, 2, 3, 4})

    def test_noise_counts_shades_and_speckles(self):
        self.assertEqual(noise([[0, 0], [0, 0]]), 0)
        self.assertEqual(noise([[4, 4], [4, 4]]), 0)
        self.assertEqual(noise([[4, 4, 0], [4, 4, 0], [0, 0, 0]]), 0)
        self.assertEqual(noise([[0, 0, 0], [0, 2, 0], [0, 0, 0]]), 1)  # a shade
        self.assertEqual(noise([[0, 0, 0], [0, 4, 0], [0, 0, 0]]), 1)  # a speckle
        self.assertEqual(noise([[0, 0, 0], [0, 4, 4], [0, 0, 0]]), 0)  # two connected pixels are not noise

    def test_anneal_hits_budget_and_keeps_binary_pixels(self):
        grid = noise_grid(12, random.Random(3))
        for target in (50, 10, 0):
            result = anneal(grid, target, random.Random(0))
            self.assertLessEqual(noise(result), target)
            self.assertEqual(anneal(grid, target, random.Random(0)), result)
        clean = anneal(grid, 0, random.Random(0))
        self.assertTrue({v for row in clean for v in row} <= {0, 4})
        self.assertEqual(anneal(clean, 0, random.Random(1)), clean)
        self.assertEqual(anneal(grid, 1000, random.Random(0)), grid)

    def test_blend_fades_noise_into_the_clean_estimate(self):
        noise_frame, clean = [[0, 4, 2]], [[4, 4, 0]]
        self.assertEqual(blend(noise_frame, clean, 0.0), noise_frame)
        self.assertEqual(blend(noise_frame, clean, 1.0), clean)
        self.assertEqual(blend(noise_frame, clean, 0.5), [[2, 4, 1]])

    def test_starting_estimates_are_clean_and_seed_dependent(self):
        noise_frame = noise_grid(20, random.Random(0))
        blob = blob_from_noise(noise_frame, random.Random(1))
        self.assertEqual(noise(blob), 0)
        self.assertTrue({v for row in blob for v in row} <= {0, 4})
        ink = sum(v == 4 for row in blob for v in row)
        self.assertTrue(0 < ink <= 0.35 * 400, ink)
        self.assertEqual(largest_component(blob), blob)  # a single connected region
        self.assertNotEqual(blob, blob_from_noise(noise_grid(20, random.Random(9)), random.Random(1)))
        shape = composition(20, random.Random(2))
        self.assertIn(4, {v for row in shape for v in row})
        self.assertTrue({v for row in shape for v in row} <= {0, 4})

    def test_denoise_operators_change_a_box_and_only_that_box(self):
        grid = noise_grid(12, random.Random(5))
        seen = set()
        for seed in range(40):
            result = denoise(grid, 6, random.Random(seed))
            if result is None:
                continue
            child, edit = result
            seen.add(edit["kind"])
            y0, x0, y1, x1 = edit["bbox"]
            changed = [(y, x) for y in range(12) for x in range(12) if child[y][x] != grid[y][x]]
            self.assertTrue(changed)
            self.assertEqual(len(changed), edit["pixels"])
            self.assertTrue(all(y0 <= y <= y1 and x0 <= x <= x1 for y, x in changed))
            self.assertLessEqual(max(y1 - y0, x1 - x0) + 1, 6)
        self.assertEqual(seen, set(DENOISERS))
        self.assertIsNone(denoise([[0] * 6 for _ in range(6)], 4, random.Random(0)))

    def test_footprints_are_bounded_and_nonempty(self):
        rng = random.Random(0)
        for kind in PRIMITIVES:
            for size in (2, 5, 20):
                for extent in (2, 4, 12, 40):
                    pixels = footprint(kind, size, extent, rng)
                    self.assertTrue(pixels, (kind, size, extent))
                    ys, xs = [y for y, _ in pixels], [x for _, x in pixels]
                    self.assertTrue(0 <= min(ys) and max(ys) < size)
                    self.assertTrue(0 <= min(xs) and max(xs) < size)
                    bound = min(extent, size) if kind != "line" else min(2 * extent + 2, size)
                    self.assertLessEqual(max(ys) - min(ys) + 1, bound)
                    self.assertLessEqual(max(xs) - min(xs) + 1, bound)

    def test_ring_is_hollow(self):
        rng = Mock()
        rng.randint.side_effect = [12, 12]
        rng.randrange.side_effect = [4, 4]
        pixels = footprint("ring", 20, 12, rng)
        self.assertNotIn((9, 9), pixels)
        self.assertIn((4, 9), pixels)

    def test_mutations_change_pixels_and_leave_parent_intact(self):
        for level in (0, 4):
            for size in (1, 3, 20):
                for extent in (2, 4, 12):
                    original = [[level] * size for _ in range(size)]
                    child, edit = mutate(original, extent, random.Random(0))
                    changed = [(y, x) for y in range(size) for x in range(size)
                               if child[y][x] != original[y][x]]
                    self.assertGreater(len(changed), 0)
                    self.assertEqual(len(changed), edit["pixels"])
                    self.assertIn(edit["kind"], PRIMITIVES + TRANSFORMS + DENOISERS)
                    if edit["kind"] in PRIMITIVES:
                        self.assertEqual(edit["color"], "white" if level == 4 else "black")
                    self.assertTrue(all(v in (0, 4) for row in child for v in row))
                    self.assertTrue(all(v == level for row in original for v in row))

    def test_transform_keeps_ink_inside_grid_and_skips_blank(self):
        self.assertIsNone(transform([[0] * 6 for _ in range(6)], random.Random(0)))
        grid = [[4 if 1 <= y <= 3 and 1 <= x <= 2 else 0 for x in range(8)] for y in range(8)]
        for seed in range(20):
            result = transform(grid, random.Random(seed))
            if result is None:
                continue
            child, edit = result
            self.assertIn(edit["kind"], TRANSFORMS)
            self.assertEqual(len(child), 8)
            self.assertIn(4, {v for row in child for v in row})
            self.assertNotEqual(child, grid)
            self.assertEqual(edit["pixels"], sum(a != b for ra, rb in zip(grid, child) for a, b in zip(ra, rb)))

    def test_forced_color_flips_when_nothing_would_change(self):
        white = [[0] * 8 for _ in range(8)]
        child, edit = mutate(white, 4, random.Random(1), color=0)
        self.assertEqual(edit["color"], "black")
        self.assertNotEqual(child, white)

    def test_render_preserves_whitespace(self):
        self.assertEqual(render([[0, 0, 0], [1, 2, 3], [4, 0, 0]]), "   \n░▒▓\n█  ")

    def test_schedule_shrinks_to_min_extent(self):
        stages = schedule(500, 20)
        self.assertEqual(stages[0], 0)
        self.assertEqual(stages[1], 12)
        self.assertEqual(stages[-1], MIN_EXTENT)
        self.assertEqual(stages[1:], sorted(stages[1:], reverse=True))
        self.assertEqual(len(stages), 500)
        self.assertEqual(schedule(1), [0])
        self.assertEqual(schedule(2), [0, MIN_EXTENT])
        self.assertEqual(schedule(3), [0, 8, MIN_EXTENT])
        self.assertTrue(all(stage >= MIN_EXTENT for stage in schedule(50, 5)[1:]))


class IntegrationTests(unittest.TestCase):
    def test_choice_maps_back_to_original_grid(self):
        client = Mock()
        client.system_one.side_effect = choose_last
        grids = [[[0]], [[4]]]
        index, detail = jev_pick(client, "a duck", grids)
        self.assertEqual(index, 1)
        self.assertEqual(detail["model"], MODEL)
        request = client.system_one.call_args.kwargs
        self.assertEqual(request["state"]["prompt"], "a duck")
        self.assertEqual(request["state"]["candidates"], {"c000": " ", "c001": "█"})
        self.assertNotIn("current", request["state"])
        self.assertNotIn(KEEP, request["questions"]["best"].criteria)

    def test_current_frame_adds_keep_option(self):
        client = Mock()
        client.system_one.side_effect = choose_keep
        index, _ = jev_pick(client, "a duck", [[[0]], [[4]]], current=[[4]])
        self.assertIsNone(index)
        request = client.system_one.call_args.kwargs
        self.assertEqual(request["state"]["current"], "█")
        self.assertEqual(list(request["questions"]["best"].criteria), ["c000", "c001", KEEP])

    def test_loop_saves_frames_and_logs_edits(self):
        client = Mock()
        client.system_one.side_effect = choose_last
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / "run"
            run(client, size=6, steps=50, candidates=3, output=output, selector="jev")
            records = [json.loads(line) for line in (output / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(client.system_one.call_count, 50)
            self.assertEqual(len(records), 50)
            self.assertEqual(records[0]["edits"], [None] * 3)
            for previous, following in zip(records, records[1:]):
                self.assertEqual(len(following["candidates"]), 3)
                self.assertNotIn(previous["candidates"][previous["selected_index"]], following["candidates"])
                self.assertFalse(following["kept"])
                self.assertGreater(following["changed_pixels"], 0)
                self.assertTrue(all(edit["kind"] in PRIMITIVES + TRANSFORMS + DENOISERS for edit in following["edits"]))
                self.assertLessEqual(previous["alpha"], following["alpha"])
            last = records[-1]
            self.assertEqual(last["alpha"], 1.0)
            self.assertEqual((output / "final.txt").read_text(encoding="utf-8"),
                             last["candidates"][last["selected_index"]] + "\n")
            self.assertEqual((output / "x0.txt").read_text(encoding="utf-8"), last["x0"] + "\n")
            # Step 0 is the raw noise the run started from.
            self.assertEqual((output / "frames.md").read_text(encoding="utf-8").count("```text"), 51)
            self.assertEqual(json.loads((output / "run.json").read_text())["status"], "complete")
            self.assertTrue((output / "final.svg").is_file())
            with self.assertRaises(FileExistsError):
                run(client, output=output)

    def test_keep_preserves_frame_and_grows_extent(self):
        client = Mock()
        client.system_one.side_effect = choose_keep
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / "run"
            run(client, size=20, steps=4, candidates=2, output=output, selector="jev")
            records = [json.loads(line) for line in (output / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["kept"] for r in records], [False, True, True, True])
            self.assertEqual([r["changed_pixels"] for r in records[1:]], [0, 0, 0])
            self.assertEqual([r["selected_index"] for r in records[1:]], [None] * 3)
            planned = schedule(4, 20)
            self.assertEqual(records[1]["extent"], planned[1])
            self.assertEqual(records[2]["extent"], round(planned[2] * 1.5))
            self.assertEqual(records[3]["extent"], round(planned[3] * 1.5 ** 2))
            # The clean estimate stays put while the viewer's frame keeps revealing it.
            self.assertEqual(len({r["x0"] for r in records}), 1)
            alphas = [r["alpha"] for r in records]
            self.assertEqual(alphas, sorted(alphas))
            self.assertEqual(alphas[-1], 1.0)

    def test_score_request_rates_current_and_candidates(self):
        client = Mock()
        client.system_one.side_effect = score_by_ink
        scores, detail = jev_score(client, "a duck", [[[0, 0]], [[4, 4]]], current=[[4, 0]])
        self.assertEqual(scores, {CURRENT: 1.5, "c000": 0.0, "c001": 3.0})
        request = client.system_one.call_args.kwargs
        self.assertEqual(list(request["state"]["frames"]), [CURRENT, "c000", "c001"])
        self.assertEqual(list(request["questions"]), [CURRENT, "c000", "c001"])
        self.assertEqual(request["questions"]["c001"].criteria, LEVELS)
        self.assertEqual(detail["scores"]["c001"]["confidence"], 0.9)

    def test_score_selector_accepts_only_improvements_and_stops_early(self):
        client = Mock()
        client.system_one.side_effect = score_by_ink
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / "run"
            run(client, size=8, steps=200, candidates=4, output=output, selector="score", stop_at=2.9, patience=10)
            records = [json.loads(line) for line in (output / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
            summary = json.loads((output / "run.json").read_text())
            self.assertEqual(summary["status"], "complete")
            self.assertTrue(summary.get("stopped_early"))
            self.assertIn(summary["stop_reason"], ("target", "plateau"))
            self.assertLess(len(records), 200)
            scores = [r["current_score"] for r in records]
            self.assertEqual(scores, sorted(scores))
            self.assertEqual(records[-1]["alpha"], 1.0)
            accepted = [r for r in records[1:] if not r["kept"]]
            self.assertTrue(accepted)
            for record in records[1:]:
                self.assertIn(CURRENT, record["scores"])
                if record["kept"]:
                    self.assertEqual(record["changed_pixels"], 0)
                    self.assertIsNone(record["selected_index"])
                else:
                    self.assertEqual(record["confirmation"]["candidate"], f"c{record['selected_index']:03}")
                    self.assertIn("answer", record["confirmation"])

    def test_confirmation_veto_keeps_current(self):
        client = Mock()

        def score_high_but_veto(**request):
            if "best" in request["questions"]:
                keys = list(request["questions"]["best"].criteria)
                lighter = min(keys, key=lambda key: request["state"]["candidates"][key].count("█"))
                return respond(lighter, keys)
            return score_by_ink(**request)

        client.system_one.side_effect = score_high_but_veto
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / "run"
            run(client, size=8, steps=6, candidates=4, output=output, selector="score")
            records = [json.loads(line) for line in (output / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(r["kept"] for r in records[1:]))
            self.assertTrue(any("confirmation" in r for r in records[1:]))
            self.assertEqual(len({r["candidates"][r["selected_index"]] for r in records if not r["kept"]}), 1)

    def test_no_keep_hides_current_frame(self):
        client = Mock()
        client.system_one.side_effect = choose_keep
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run(client, size=6, steps=3, candidates=2, output=Path(directory) / "run", selector="jev", allow_keep=False)
            for call in client.system_one.call_args_list:
                self.assertNotIn("current", call.kwargs["state"])
                self.assertNotIn(KEEP, call.kwargs["questions"]["best"].criteria)

    def test_failure_preserves_completed_frames(self):
        client = Mock()
        responses = 0

        def fail_second(**request):
            nonlocal responses
            responses += 1
            if responses == 2:
                raise RuntimeError("service unavailable")
            return choose_last(**request)

        client.system_one.side_effect = fail_second
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / "run"
            with self.assertRaisesRegex(RuntimeError, "service unavailable"):
                run(client, size=4, steps=3, candidates=2, output=output, selector="jev")
            summary = json.loads((output / "run.json").read_text())
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["completed_steps"], 1)
            self.assertEqual((output / "frames.md").read_text(encoding="utf-8").count("```text"), 2)
            self.assertTrue((output / "final.svg").is_file())

    def test_random_baseline_reproduces_without_api(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            paths = [Path(directory) / name for name in ("a", "b")]
            for output in paths:
                run(None, size=8, steps=3, candidates=2, output=output, selector="random")
            self.assertEqual((paths[0] / "final.txt").read_text(encoding="utf-8"),
                             (paths[1] / "final.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
