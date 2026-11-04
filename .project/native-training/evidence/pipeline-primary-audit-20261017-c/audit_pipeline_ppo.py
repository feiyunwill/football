"""Independently bind primary PPO samples to baseline and retained artifacts."""
import argparse
import json
from pathlib import Path
import numpy as np
from validate import ROOT, sha, source_fingerprint
import quality

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    directory = args.evidence.resolve()
    protocol = read(directory / 'protocol.json')
    result = read(directory / 'report.json')
    assert result['status'] == 'completed'
    assert source_fingerprint()['sha256'] == protocol['source_sha256'] == result['source_sha256']
    assert sha(directory / 'protocol.json') == result['protocol_sha256']
    assert sha(HERE / 'profile_pipeline_ppo.py') == protocol['runner_sha256'] == result['runner_sha256']
    assert sha(directory / 'benchmark_pipeline_ppo.py') == result['suite_sha256']
    accepted_quality = quality.verify(ROOT / protocol['quality'])
    baseline_root = Path(protocol['baseline'])
    baseline = read(baseline_root / 'baseline.json')
    current_stage = Path('/tmp/football-native-assessment-20261015/validation-stage/gfootball_engine')
    baseline_artifacts = {name: sha(baseline_root / 'gfootball_engine' / name) for name in baseline['artifacts']}
    assert baseline_artifacts == baseline['artifacts']
    assert baseline['source']['sha256'] == '7640b9befe4155bf3887f4f98e20fd056fc4d09127636c0d23da4a28a21fb96a'
    spatial_audit = HERE / 'evidence/spatial-audit-20261017-b/report.json'
    assert read(spatial_audit)['passed']
    audited = 0
    for comparison, summary in result['results'].items():
        assert len(summary['pairs']) == protocol['pairs']
        ratios = []
        for number, pair in enumerate(summary['pairs']):
            runs, checkpoints, iterations = [], [], []
            for label in ('a', 'b'):
                folder = directory / f'{comparison}-{number}-{label}'
                run = read(folder / 'report.json')
                assert pair['receipts'][str(folder / 'report.json')] == sha(folder / 'report.json')
                assert run['passed'] and run['workers_reaped']
                assert run['source_before'] == run['source_after'] == source_fingerprint()
                assert run['environment_before'] == run['environment_after']
                assert run['artifacts'] == run['artifacts_after']
                assert run['tooling'] == run['tooling_after']
                workers = 1 if comparison == 'worker_scaling' and label == 'a' else 4
                assert run['exit_codes'] == [0] * workers and run['protocol']['workers'] == workers
                assert run['parent_before']['fds'] == run['parent_after_close']['fds']
                assert run['updates'] == protocol['updates_per_run']
                for key, value in dict(players=11, cadence=2, episodes_per_update=4, horizon=64,
                                       hidden=16, epochs=4, minibatch=64).items():
                    assert run['protocol'][key] == value
                expected_stage = baseline_root / 'gfootball_engine' if comparison == 'engine_pipeline' and label == 'a' else current_stage
                for name in ('_gameplayfootball.so', 'libfootball_engine.so'):
                    artifact = expected_stage / name
                    assert run['artifacts'][str(artifact)] == sha(artifact)
                for name, digest in run['artifacts'].items():
                    assert sha(Path(name)) == digest
                for name, digest in run['tooling'].items():
                    assert sha(folder / name) == digest
                for name in ('iterations.jsonl', 'resources.jsonl'):
                    assert sha(folder / name) == run[name + '_sha256']
                assert sha(folder / 'latest-checkpoint.json') == run['checkpoint_sha256']
                checkpoints.append(read(folder / 'latest-checkpoint.json')['state'])
                rows = [json.loads(line) for line in (folder / 'iterations.jsonl').read_text().splitlines()]
                assert len(rows) == protocol['updates_per_run']
                for version, row in enumerate(rows, 1):
                    assert row['version'] == version
                    assert all(value >= 0 for value in row['stages'].values())
                    assert sum(row['stages'].values()) <= row['iteration_ns']
                assert sum(row['transitions'] for row in rows) == run['transitions']
                assert run['transitions_per_second'] == run['transitions'] / run['duration_seconds']
                iterations.append([(r['version'], r['transitions'], r['update']) for r in rows])
                monitor=read(folder/'index-cpu.json')
                samples=monitor['samples']
                mean=sum(row['cpu_seconds'] for row in samples)/sum(row['seconds'] for row in samples)
                p95=float(np.percentile([row['cores'] for row in samples],95))
                assert monitor['mean_cores']==mean and monitor['p95_cores']==p95
                assert mean<=protocol['environment_gate']['maximum_index_mean_cores']
                assert p95<=protocol['environment_gate']['maximum_index_p95_cores']
                runs.append(run)
                audited += 1
            assert checkpoints[0] == checkpoints[1] and iterations[0] == iterations[1]
            assert runs[0]['replay_sha256'] == runs[1]['replay_sha256'] == pair['replay_sha256']
            assert runs[0]['environment_before'] == runs[1]['environment_before']
            ratio = runs[0]['duration_seconds'] / runs[1]['duration_seconds']
            assert pair['ratio'] == ratio
            ratios.append(ratio)
        rng = np.random.default_rng(protocol['bootstrap']['seed'])
        draws = np.median(rng.choice(ratios, (protocol['bootstrap']['draws'], len(ratios))), axis=1)
        interval = np.percentile(draws, [2.5, 97.5]).tolist()
        assert summary['ci95'] == interval and summary['median_speedup'] == float(np.median(ratios))
        gate = protocol['gates'][comparison]
        assert summary['accepted'] == (summary['median_speedup'] >= gate['median_speedup_min'] and interval[0] > gate['paired_bootstrap_95_lower_min'])
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    report = dict(passed=True, audited_runs=audited, source_sha256=source_fingerprint()['sha256'],
                  results=result['results'], all_primary_gates_passed=result['all_primary_gates_passed'],
                  quality=accepted_quality, baseline_source_sha256=baseline['source']['sha256'],
                  baseline_artifacts=baseline_artifacts,
                  receipts={str(path): sha(path) for path in (directory / 'report.json', directory / 'protocol.json',
                                                             baseline_root / 'baseline.json', spatial_audit)},
                  auditor_sha256=sha(Path(__file__)),
                  scope='Audit passing means evidence reconciles, even when a performance gate fails. No matrix or learning acceptance.')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True, audited_runs=audited, all_primary_gates_passed=result['all_primary_gates_passed'])))


if __name__ == '__main__':
    main()
