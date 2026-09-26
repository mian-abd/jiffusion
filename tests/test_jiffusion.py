from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import Mock

from typesafe_sdk import SystemOneResponse

from jiffusion import MODEL, brightness_schedule, jev_pick, mutate, random_grid, render, resize_grid, resolution_schedule, run, schedule
from prompts import ASCII_LEGEND, CHOICE_INSTRUCTIONS, PALETTE


def choose_last(**request):
    keys = list(request["questions"]["best"].criteria)
    return SystemOneResponse(
        model=MODEL, usage={"input_tokens":100,"output_tokens":10},
        answers={"best": {"type":"choice", "choice":keys[-1], "confidence":1.0,
                          "probabilities":{key: float(key == keys[-1]) for key in keys}}},
    )


class GridTests(unittest.TestCase):
    def test_random_grid_shape_range_and_seed(self):
        grid = random_grid(20, random.Random(7))
        self.assertEqual(grid, random_grid(20, random.Random(7)))
        self.assertEqual(len(grid), 20)
        self.assertTrue(all(len(row) == 20 for row in grid))
        self.assertEqual({v for row in grid for v in row}, set(range(5)))
        for y in range(0, 20, 4):
            for x in range(0, 20, 4):
                block = {grid[row][col] for row in range(y, y+4) for col in range(x, x+4)}
                self.assertEqual(len(block), 1)

    def test_mutations_paint_one_square_and_leave_parent_intact(self):
        for level in range(5):
            for size in (1, 3, 20):
                for width in (1, 2, 4):
                    original = [[level] * size for _ in range(size)]
                    child = mutate(original, width, random.Random(0))
                    changed = [(y, x) for y in range(size) for x in range(size)
                               if child[y][x] != original[y][x]]
                    self.assertEqual(len(changed), min(width, size)**2)
                    self.assertEqual(max(y for y,x in changed)-min(y for y,x in changed)+1, min(width, size))
                    self.assertEqual(max(x for y,x in changed)-min(x for y,x in changed)+1, min(width, size))
                    self.assertTrue(all(v in range(5) for row in child for v in row))
                    self.assertTrue(all(v == level for row in original for v in row))

    def test_mixed_patch_is_painted_uniformly_and_changes_at_least_one_pixel(self):
        grid = [[4 * ((x + y) % 2) for x in range(20)] for y in range(20)]
        rng = Mock()
        rng.randrange.side_effect = [7, 5]
        rng.choice.return_value = 4
        child = mutate(grid, 4, rng)
        self.assertEqual({child[y][x] for y in range(7, 11) for x in range(5, 9)}, {4})
        for y in range(20):
            for x in range(20):
                if not (7 <= y < 11 and 5 <= x < 9):
                    self.assertEqual(child[y][x], grid[y][x])
        self.assertNotEqual(child, grid)

    def test_coarse_grid_handles_nonmultiples_and_small_sizes(self):
        for size in (1, 3, 21):
            grid = random_grid(size, random.Random(0))
            self.assertEqual(len(grid), size)
            self.assertTrue(all(len(row) == size for row in grid))
            self.assertTrue(all(v in range(5) for row in grid for v in row))

    def test_brightness_limits_preserve_range_and_force_changes_at_endpoints(self):
        rng = random.Random(23)
        for limit in (1, 2, 4):
            for old in range(5):
                for _ in range(30):
                    value = mutate([[old]], 1, rng, limit)[0][0]
                    self.assertTrue(0 <= value <= 4)
                    self.assertTrue(0 < abs(value - old) <= limit)
            grid = [[(x + y) % 5 for x in range(20)] for y in range(20)]
            child = mutate(grid, 4, rng, limit)
            differences = [abs(a-b) for before, after in zip(grid, child) for a,b in zip(before, after)]
            self.assertTrue(0 < max(differences) <= limit)
            self.assertLessEqual(sum(bool(d) for d in differences), 16)
        self.assertEqual(brightness_schedule(750), [0] + [4] * 74 + [2] * 225 + [1] * 450)
        self.assertEqual(brightness_schedule(1), [0])

    def test_render_preserves_rows_and_columns_as_ascii(self):
        self.assertEqual(render([[0, 0, 0], [1, 2, 3], [4, 0, 0]]), "...\n:-=\n#..")

    def test_nearest_neighbor_enlargement_preserves_blocks(self):
        self.assertEqual(resize_grid([[0, 4], [4, 0]], 4), [
            [0, 0, 4, 4], [0, 0, 4, 4], [4, 4, 0, 0], [4, 4, 0, 0],
        ])

    def test_schedule(self):
        stages = schedule(500)
        self.assertEqual(stages, [0] + [4] * 49 + [2] * 150 + [1] * 300)
        self.assertEqual(schedule(1), [0])
        self.assertEqual(len(schedule(2)), 2)
        self.assertEqual(schedule(500, 1), [0] + [1] * 499)
        self.assertEqual(resolution_schedule(20, 500, True), [5] * 150 + [10] * 150 + [20] * 200)
        self.assertEqual(resolution_schedule(20, 500), [20] * 500)
        self.assertEqual(resolution_schedule(20, 1, True), [20])
        self.assertEqual(resolution_schedule(20, 2, True), [10, 20])


class IntegrationTests(unittest.TestCase):
    def test_choice_maps_back_to_original_grid(self):
        client = Mock()
        client.system_one.side_effect = choose_last
        grids = [[[0]], [[4]]]
        index, detail = jev_pick(client, "a duck", grids)
        self.assertEqual(index, 1)
        self.assertEqual(detail["model"], MODEL)
        state = client.system_one.call_args.kwargs["state"]
        self.assertEqual(state["prompt"], "a duck")
        self.assertEqual(state["candidates"], {"c000": ".", "c001": "#"})
        self.assertEqual(state["legend"], ASCII_LEGEND)
        self.assertEqual(client.system_one.call_args.kwargs["questions"]["best"].instructions, CHOICE_INSTRUCTIONS)

    def test_progressive_loop_mutates_after_each_resolution_change(self):
        client = Mock()
        client.system_one.side_effect = choose_last
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / "run"
            run(client, size=20, steps=10, candidates=2, progressive=True, output=output)
            records = [json.loads(line) for line in (output / "steps.jsonl").read_text().splitlines()]
            self.assertEqual(client.system_one.call_count, 10)
            self.assertEqual([row['grid_size'] for row in records], [5] * 3 + [10] * 3 + [20] * 4)
            for before, after in zip(records, records[1:]):
                old_rows = before['candidates'][before['selected_index']].splitlines()
                size = after['grid_size']
                expected_parent = [''.join(old_rows[y * len(old_rows) // size][x * len(old_rows) // size]
                                           for x in range(size)) for y in range(size)]
                self.assertEqual(after['changed_pixels'], 1)
                self.assertFalse(after['unchanged'])
                for candidate in after['candidates']:
                    rows = candidate.splitlines()
                    self.assertEqual(len(rows), size)
                    self.assertTrue(all(len(row) == size for row in rows))
                    self.assertEqual(sum(a != b for a, b in zip('\n'.join(expected_parent), candidate)), 1)
            self.assertEqual(len((output / 'final.txt').read_text().splitlines()), 20)
            manifest = json.loads((output / 'run.json').read_text())
            self.assertEqual(manifest['legend'], ASCII_LEGEND)
            self.assertEqual(manifest['question'], CHOICE_INSTRUCTIONS)

    def test_loop_saves_50_frames_and_never_offers_current_frame(self):
        client = Mock()
        client.system_one.side_effect = choose_last
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / "run"
            run(client, size=4, steps=50, candidates=3, output=output)
            records = [json.loads(line) for line in (output / "steps.jsonl").read_text().splitlines()]
            self.assertEqual(client.system_one.call_count, 50)
            self.assertEqual(len(records), 50)
            self.assertEqual(len(records[0]["candidates"]), 3)
            for previous, following in zip(records, records[1:]):
                self.assertEqual(len(following["candidates"]), 3)
                self.assertNotIn(previous["candidates"][previous["selected_index"]], following["candidates"])
                self.assertFalse(following["unchanged"])
                self.assertGreater(following["changed_pixels"], 0)
                parent = previous['candidates'][previous['selected_index']].replace('\n', '')
                for child in following['candidates']:
                    delta = max(abs(PALETTE.index(a)-PALETTE.index(b))
                                for a,b in zip(parent, child.replace('\n', '')))
                    self.assertTrue(0 < delta <= following['brightness_limit'])
            last = records[-1]
            self.assertEqual((output / "final.txt").read_text(), last["candidates"][last["selected_index"]] + "\n")
            self.assertEqual((output / "frames.md").read_text().count("```text"), 50)
            self.assertEqual(json.loads((output / "run.json").read_text())["status"], "complete")
            self.assertTrue((output / "final.svg").is_file())
            with self.assertRaises(FileExistsError):
                run(client, output=output)

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
                run(client, size=4, steps=3, candidates=2, output=output)
            summary = json.loads((output / "run.json").read_text())
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["completed_steps"], 1)
            self.assertEqual((output / "frames.md").read_text().count("```text"), 1)
            self.assertTrue((output / "final.svg").is_file())

    def test_random_baseline_reproduces_without_api(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            paths = [Path(directory) / name for name in ("a", "b")]
            for output in paths:
                run(None, size=8, steps=3, candidates=2, output=output, selector="random")
            self.assertEqual((paths[0] / "final.txt").read_text(), (paths[1] / "final.txt").read_text())


if __name__ == "__main__":
    unittest.main()
