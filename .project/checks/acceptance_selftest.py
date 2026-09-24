#!/usr/bin/env python3
"""Run the permanent acceptance-checker regressions as part of the formal gate."""
import importlib.util
import io
import json
import sys
import unittest
from native_boundary import ROOT, require

def main():
    counts = {}
    total = 0
    for name, minimum in (("acceptance_inputs_test", 8), ("loading_acceptance_test", 13)):
        path = ROOT / ".project/tests" / (name + ".py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        output = io.StringIO()
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
        if not result.wasSuccessful() or result.skipped or result.testsRun < minimum:
            print(output.getvalue(), file=sys.stderr)
            raise RuntimeError("Acceptance self-test coverage failed: " + name)
        counts[name] = result.testsRun
        total += result.testsRun
    print(json.dumps({"passed": True, "checks": total, "assertions": total,
                      "skipped": 0, "modules": counts}))

if __name__ == "__main__":
    main()
