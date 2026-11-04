#!/usr/bin/env python3
"""Apply the O3 pre-registered thresholds to paired raw CPU measurements."""
import argparse
import json
from pathlib import Path
import numpy as np


def decision(report):
    if not report.get('passed'):
        raise ValueError('Comparison failed')
    rng = np.random.default_rng(20261015)
    results = []
    for workload in report['workloads']:
        ratios = np.asarray(workload['paired_cpu_speedups'], dtype=float)
        if len(ratios) < 8 or not np.all(np.isfinite(ratios)) or np.any(ratios <= 0):
            raise ValueError('Need eight finite positive paired samples')
        bootstrap = np.median(ratios[rng.integers(len(ratios), size=(10000, len(ratios)))], axis=1)
        speedup = float(np.median(ratios))
        results.append(dict(players=workload['players'], cadence=workload['cadence'],
            feedback=workload['feedback'], speedup=speedup, cost_reduction=1-1/speedup,
            interval=[float(np.quantile(bootstrap,.025)),float(np.quantile(bootstrap,.975))]))
    primary = next(r for r in results if (r['players'],r['cadence'],r['feedback']) == (1,10,False))
    primary_passed = primary['cost_reduction'] >= .10 and primary['interval'][0] > 1
    full = report.get('scope') == 'full_matrix' and len(results) == 8
    secondary_passed = all(r['speedup'] >= 1/1.03 for r in results)
    return dict(primary_passed=primary_passed, full_matrix=full,
                retain=primary_passed and full and secondary_passed,
                action='full_matrix_required' if primary_passed and not full else
                       'retain_pending_long_soak' if primary_passed and secondary_passed else 'reject',
                workloads=results,
                limitation='Paired bootstrap describes this machine/workload only; eight pairs give limited precision')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output file')
    result = decision(json.loads(args.report.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
