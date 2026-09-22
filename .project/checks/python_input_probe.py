"""Execute the Python input behavior cases, rejecting skipped or empty cohorts."""
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
suite=unittest.defaultTestLoader.loadTestsFromName('gfootball.frame_sync.test_graphical_input')
result=unittest.TextTestRunner(verbosity=2).run(suite)
passed=result.wasSuccessful() and result.testsRun>=9 and not result.skipped
print(json.dumps(dict(passed=passed,skipped=len(result.skipped),assertions=result.testsRun)))
raise SystemExit(0 if passed else 1)
