"""Statistical report checks without running engine training."""
import unittest
import numpy as np
from validate_learning import paired_interval, successes
from decide_candidate import decision


class LearningStudyTest(unittest.TestCase):
    def test_success_requires_real_goal_not_shaped_reward(self):
        evaluation = {'strategies': [{'name': 'argmax', 'episodes': [
            {'controlled_score_delta': 0, 'reward': 10},
            {'controlled_score_delta': -1, 'reward': 0},
            {'controlled_score_delta': 1, 'reward': 1}]}]}
        self.assertEqual(successes(evaluation, 'argmax'), [0, 0, 1])

    def test_identical_matched_results_have_zero_difference(self):
        data = [[0, 1, 1], [1, 0, 1], [0, 0, 1]]
        self.assertEqual(paired_interval(data, data, 100), dict(mean=0., low=0., high=0.))

    def test_shared_episode_uncertainty_does_not_disappear_with_more_seeds(self):
        # Every model fails/succeeds on the same scenario: seeds are not extra
        # independent evidence about scenario difficulty.
        final = np.tile([0, 0, 1, 1], (5, 1))
        baseline = np.zeros_like(final)
        interval = paired_interval(final, baseline, 1000)
        self.assertEqual(interval['mean'], .5)
        self.assertLess(interval['low'], .3)
        self.assertGreater(interval['high'], .7)

    def test_training_seed_variation_is_retained(self):
        final = [[0] * 30, [1] * 30]
        interval = paired_interval(final, np.zeros_like(final), 1000)
        self.assertEqual(interval['low'], 0.)
        self.assertEqual(interval['high'], 1.)

    def test_primary_screen_cannot_authorize_retention(self):
        report = dict(passed=True, scope='primary_only', workloads=[dict(
            players=1, cadence=10, feedback=False, paired_cpu_speedups=[1.2]*8)])
        result = decision(report)
        self.assertTrue(result['primary_passed'])
        self.assertFalse(result['retain'])
        self.assertEqual(result['action'], 'full_matrix_required')

    def test_secondary_regression_rejects_an_improved_primary(self):
        workloads = [dict(players=p, cadence=c, feedback=f,
                     paired_cpu_speedups=[1.2 if (p,c,f) == (1,10,False) else .95]*8)
                     for p in (1,11) for c in (2,10) for f in (False,True)]
        result = decision(dict(passed=True, scope='full_matrix', workloads=workloads))
        self.assertFalse(result['retain'])
        self.assertEqual(result['action'], 'reject')


if __name__ == '__main__':
    unittest.main()
