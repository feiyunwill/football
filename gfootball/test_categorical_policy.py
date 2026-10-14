"""Independent NumPy reference for the actual C++ forward and categorical result."""
import json
import os
import subprocess
import unittest
import numpy as np


@unittest.skipUnless(os.environ.get('GFOOTBALL_CATEGORICAL_CONTRACT'),
                     'Run the isolated validator to build the C++ policy contract')
class CategoricalPolicyTest(unittest.TestCase):
  def test_cpp_network_and_categorical_against_numpy(self):
    run = subprocess.run([os.environ['GFOOTBALL_CATEGORICAL_CONTRACT']], capture_output=True, timeout=30)
    self.assertEqual(run.returncode, 0, run.stderr.decode())
    data = json.loads(run.stdout)
    self.assertTrue(data['passed'])
    parameters = np.asarray(data['parameters'], dtype=np.float64)
    observation = np.asarray(data['input'], dtype=np.float32).astype(np.float64)
    # Decode the documented packed layout, then use independent vector operations.
    hidden = np.tanh(parameters[:230].reshape(2, 115) @ observation + parameters[230:232])
    output = parameters[232:272].reshape(20, 2) @ hidden + parameters[272:]
    logits = output[:19]
    shifted = logits - logits.max()
    log_probabilities = shifted - np.log(np.exp(shifted).sum())
    probabilities = np.exp(log_probabilities)
    entropy = -np.dot(probabilities, log_probabilities)
    np.testing.assert_allclose(data['hidden'], hidden, rtol=0, atol=1e-14)
    np.testing.assert_allclose(data['logits'], logits, rtol=0, atol=1e-14)
    self.assertAlmostEqual(data['value'], output[-1], delta=1e-14)
    self.assertEqual(data['argmax'], int(logits.argmax()))
    self.assertAlmostEqual(data['log_probability'], log_probabilities[logits.argmax()], delta=1e-14)
    self.assertAlmostEqual(data['entropy'], entropy, delta=1e-14)


if __name__ == '__main__': unittest.main()
