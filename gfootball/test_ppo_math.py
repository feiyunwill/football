"""Independent NumPy losses/numerical gradients and Adam/GAE for actual C++ fixtures."""
import json
import os
import subprocess
import unittest
import numpy as np


@unittest.skipUnless(os.environ.get('GFOOTBALL_PPO_MATH_CONTRACT'),
                     'Run the isolated validator to build the C++ PPO contract')
class PpoMathTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    run = subprocess.run([os.environ['GFOOTBALL_PPO_MATH_CONTRACT']], capture_output=True, timeout=60)
    if run.returncode: raise RuntimeError(run.stderr.decode())
    cls.data = json.loads(run.stdout)

  def test_losses_and_full_gradients_against_independent_numerical_reference(self):
    data = self.data
    weights = np.asarray(data['parameters'], dtype=np.float64)
    observation = np.asarray(data['input'], dtype=np.float32).astype(np.float64)
    def objective(parameters, fixture):
      hidden = np.tanh(parameters[:460].reshape(2, 230) @ observation + parameters[460:462])
      output = parameters[462:540].reshape(39, 2) @ hidden + parameters[540:]
      logits = output[:38].reshape(2, 19)
      shifted = logits - logits.max(axis=1, keepdims=True)
      log_probabilities = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
      entropy = -(np.exp(log_probabilities) * log_probabilities).sum()
      log_probability = log_probabilities[0, 3] + log_probabilities[1, 7]
      ratio = np.exp(log_probability - fixture['old_log_probability'])
      advantage = fixture['advantage']
      loss = -min(ratio * advantage, np.clip(ratio, .8, 1.2) * advantage)
      loss += .5 * .5 * (output[-1] - fixture['target']) ** 2 - .01 * entropy
      return loss, ratio, entropy
    for fixture in data['fixtures']:
      loss, ratio, entropy = objective(weights, fixture)
      self.assertAlmostEqual(fixture['loss'], loss, delta=1e-13)
      self.assertAlmostEqual(fixture['ratio'], ratio, delta=1e-13)
      self.assertAlmostEqual(fixture['entropy'], entropy, delta=1e-13)
      numerical = np.empty_like(weights)
      for index in range(len(weights)):
        plus, minus = weights.copy(), weights.copy()
        plus[index] += 1e-6; minus[index] -= 1e-6
        numerical[index] = (objective(plus, fixture)[0] - objective(minus, fixture)[0]) / 2e-6
      np.testing.assert_allclose(fixture['gradient'], numerical, rtol=0, atol=2e-7)
    self.assertTrue(data['passed'])
    self.assertGreater(data['parameter_delta'], 0)
    self.assertEqual(data['optimizer_steps'], 4)

  def test_gae_terminal_truncation_and_population_normalization(self):
    # Last episode terminal does not enter the preceding truncated episode.
    delta_live = 1 + .99 * 3 - 2
    delta_horizon = 2 + .99 * 4 - 3
    delta_terminal = 3 - 4
    expected = np.array([delta_live + .99 * .95 * delta_horizon, delta_horizon, delta_terminal])
    np.testing.assert_allclose(self.data['gae'], expected, rtol=0, atol=1e-13)
    normalized = (expected - expected.mean()) / (expected.std(ddof=0) + 1e-8)
    np.testing.assert_allclose(self.data['normalized_advantages'], normalized, rtol=0, atol=1e-13)

  def test_adam_first_two_steps_and_bias_correction(self):
    weights = np.asarray(self.data['parameters'], dtype=np.float64)
    first = np.zeros_like(weights); second = np.zeros_like(weights)
    for step, pair, prefix in ((1, (.25, -.5), 'adam'), (2, (-.125, .75), 'adam_step2')):
      gradient = np.zeros_like(weights); gradient[:2] = pair
      first = .9 * first + (1 - .9) * gradient
      second = .999 * second + (1 - .999) * gradient ** 2
      corrected_first = first / (1 - .9 ** step)
      corrected_second = second / (1 - .999 ** step)
      weights = weights - .0003 * corrected_first / (np.sqrt(corrected_second) + 1e-8)
      np.testing.assert_allclose(self.data[prefix + '_weights'], weights, rtol=0, atol=1e-14)
      np.testing.assert_allclose(self.data[prefix + '_first'], first, rtol=0, atol=1e-15)
      np.testing.assert_allclose(self.data[prefix + '_second'], second, rtol=0, atol=1e-15)


if __name__ == '__main__': unittest.main()
