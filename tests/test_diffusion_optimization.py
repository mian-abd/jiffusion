import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

if importlib.util.find_spec("dspy") is None:
    raise unittest.SkipTest("Install with uv sync --extra optimize")

import optimize_diffusion as opt
from prompts import CHOICE_INSTRUCTIONS
from test_jiffusion import choose_last
from dspy.utils import DummyLM


class DiffusionOptimizationTests(unittest.TestCase):
    def test_references_are_grading_only_and_families_and_seeds_are_disjoint(self):
        splits = opt.build_tasks()
        self.assertEqual([len(rows) for rows in splits.values()], [5, 2, 3])
        seen = set()
        for seed, rows in enumerate(splits.values()):
            families = {row['family'] for row in rows}
            self.assertFalse(seen & families)
            seen |= families
            for row in rows:
                self.assertEqual(len(row['references']), 5)
                self.assertEqual(row['seed'], seed)
                example = opt.dspy.Example(**row).with_inputs('prompt', 'seed')
                self.assertEqual(set(example.inputs().keys()), {'prompt', 'seed'})
        self.assertEqual(sum(map(len, opt.build_tasks(styles=('filled', 'outline')).values())), 20)

    def test_iou_does_not_reward_blank_background_and_handles_polarity(self):
        art = '\n'.join(['.' * 20] * 5 + ['.' * 5 + '#' * 10 + '.' * 5] * 10 + ['.' * 20] * 5)
        blank = '\n'.join(['.' * 20] * 20)
        filled = blank.replace('.', '#')
        self.assertEqual(opt.foreground_iou(art, art), 1)
        self.assertEqual(opt.foreground_iou(blank, art), 0)
        self.assertEqual(opt.foreground_iou(filled, art), .25)
        inverse = art.translate(str.maketrans('.#', '#.'))
        self.assertEqual(opt.foreground_iou(inverse, inverse), 1)
        self.assertEqual(opt.foreground_iou(filled, inverse), 0)
        self.assertEqual(opt.foreground_iou('malformed', art), 0)
        gray = art.replace('#', '-')
        self.assertEqual(opt.foreground_iou(gray, gray), 1)
        self.assertEqual(opt.foreground_iou(art, gray), .5)

    def test_full_loop_uses_instruction_every_step_and_never_offers_parent(self):
        client = Mock()
        client.system_one.side_effect = choose_last
        factory = Mock()
        factory.return_value.__enter__ = Mock(return_value=client)
        factory.return_value.__exit__ = Mock(return_value=False)
        instruction = 'Read candidates as a complete image and select the closest match to prompt.'
        with tempfile.TemporaryDirectory() as directory:
            rollouts = opt.Rollouts(directory, steps=7, client_factory=factory, max_calls=14)
            program = opt.FullGeneration(rollouts, instruction)
            self.assertIs(program.deepcopy().rollouts, rollouts)
            result = program(prompt='something unseen', seed=3)
            self.assertEqual(client.system_one.call_count, 7)
            for call in client.system_one.call_args_list:
                request = call.kwargs
                self.assertEqual(request['questions']['best'].instructions, instruction)
                self.assertEqual(set(request['state']), {'prompt', 'legend', 'candidates'})
            records = [json.loads(line) for line in (Path(result.path) / 'steps.jsonl').read_text().splitlines()]
            for previous, current in zip(records, records[1:]):
                self.assertNotIn(previous['candidates'][previous['selected_index']], current['candidates'])
                self.assertFalse(current['unchanged'])
            self.assertEqual(result.art, records[-1]['candidates'][records[-1]['selected_index']])
            self.assertEqual(program(prompt='something unseen', seed=3).path, result.path)
            self.assertEqual(client.system_one.call_count, 7)
            program.signature = program.signature.with_instructions(CHOICE_INSTRUCTIONS)
            self.assertNotEqual(program(prompt='something unseen', seed=3).path, result.path)
            self.assertEqual(client.system_one.call_count, 14)
            with self.assertRaisesRegex(RuntimeError, 'budget'):
                program(prompt='something unseen', seed=4)

    def test_shape_specific_instruction_cannot_start_a_rollout(self):
        rollouts = Mock()
        program = opt.FullGeneration(rollouts, 'When prompt is a circle, prefer circular candidates.')
        self.assertEqual(program(prompt='a circle', seed=0).art, '')
        rollouts.generate.assert_not_called()

    def test_copro_runs_complete_generations_and_writes_final_gallery(self):
        instruction = 'Read candidates as a complete image and select the closest match to prompt.'
        lm = DummyLM([dict(proposed_instruction=instruction, proposed_prefix_for_output_field='Winner:')])
        lm.inspect_history = Mock()
        client = Mock()
        client.system_one.side_effect = choose_last
        factory = Mock()
        factory.return_value.__enter__ = Mock(return_value=client)
        factory.return_value.__exit__ = Mock(return_value=False)
        splits = {key: rows[:1] for key, rows in opt.build_tasks().items()}
        with tempfile.TemporaryDirectory() as directory:
            rollouts = opt.Rollouts(directory, steps=3, client_factory=factory, max_calls=30)
            report = opt.optimize(rollouts, lm, splits, directory, breadth=2, depth=1, threads=1)
            self.assertFalse(report['deployment_approved'])
            self.assertTrue((Path(directory) / 'finals.png').exists())
            self.assertEqual(report['steps'], 3)
            for path in (Path(directory) / 'rollouts').glob('*/run.json'):
                self.assertEqual(json.loads(path.read_text())['completed_steps'], 3)
            self.assertNotIn(splits['train'][0]['references'][0], str(lm.history))


if __name__ == '__main__':
    unittest.main()
