"""Reconcile archived PPO performance and duration receipts without widening claims."""
import hashlib
import json
from pathlib import Path

import numpy as np
import quality
from validate import ROOT, sha, source_fingerprint

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / 'evidence'


def read(path):
    return json.loads(path.read_text())


def main():
    current = source_fingerprint()
    manifest_path = EVIDENCE / 'pipeline-archive-20261017-a/manifest.json'
    manifest = read(manifest_path)
    for name, record in manifest.items():
        assert sha(ROOT / name) == record['sha256']
    verified_quality = quality.verify(EVIDENCE / 'spatial-candidate-quality-20261017-b/report.json')
    summaries = {}
    audited_runs = 0
    scopes = [('primary', 'pipeline-primary-20261017-c')]
    scopes += [(name, f'pipeline-matrix-{name}-20261017-a') for name in ('p1-c2', 'p1-c10', 'p11-c10')]
    for label, name in scopes:
        directory = EVIDENCE / name
        protocol = read(directory / 'protocol.json')
        report = read(directory / 'report.json')
        assert report['status'] == 'completed'
        assert current['sha256'] == report['source_sha256'] == protocol['source_sha256']
        assert sha(directory / 'protocol.json') == report['protocol_sha256']
        assert sha(directory / 'benchmark_pipeline_ppo.py') == report['suite_sha256']
        assert report['runner_sha256'] == protocol['runner_sha256']
        summaries[label] = {}
        for comparison, registered in protocol['gates'].items():
            pairs = report['results'][comparison]['pairs']
            assert len(pairs) == protocol['pairs'] == 8
            ratios = []
            for number, pair in enumerate(pairs):
                runs, states, streams = [], [], []
                for side in ('a', 'b'):
                    folder = directory / f'{comparison}-{number}-{side}'
                    run = read(folder / 'report.json')
                    origin = manifest[str((folder / 'report.json').relative_to(ROOT))]['origin']
                    assert pair['receipts'][origin] == sha(folder / 'report.json')
                    assert run['passed'] and run['source_before'] == run['source_after'] == current
                    assert run['environment_before'] == run['environment_after']
                    assert run['artifacts'] == run['artifacts_after'] and run['tooling'] == run['tooling_after']
                    assert run['workers_reaped'] and run['exit_codes'] == [0] * run['protocol']['workers']
                    assert run['parent_before']['fds'] == run['parent_after_close']['fds']
                    assert run['updates'] == protocol['updates_per_run'] == 64
                    for key in ('players', 'cadence'):
                        assert run['protocol'][key] == protocol['primary'][key]
                    for filename in ('iterations.jsonl', 'resources.jsonl'):
                        assert sha(folder / filename) == run[filename + '_sha256']
                    assert sha(folder / 'latest-checkpoint.json') == run['checkpoint_sha256']
                    for tool, digest in run['tooling'].items():
                        assert sha(folder / tool) == digest
                    index = read(folder / 'index-cpu.json')
                    assert index['mean_cores'] <= protocol['environment_gate']['maximum_index_mean_cores']
                    assert index['p95_cores'] <= protocol['environment_gate']['maximum_index_p95_cores']
                    states.append(read(folder / 'latest-checkpoint.json')['state'])
                    rows = [json.loads(line) for line in (folder / 'iterations.jsonl').read_text().splitlines()]
                    assert len(rows) == run['updates']
                    assert sum(row['transitions'] for row in rows) == run['transitions']
                    streams.append([(row['version'], row['transitions'], row['update']) for row in rows])
                    runs.append(run)
                    audited_runs += 1
                assert states[0] == states[1] and streams[0] == streams[1]
                assert runs[0]['replay_sha256'] == runs[1]['replay_sha256'] == pair['replay_sha256']
                assert runs[0]['environment_before'] == runs[1]['environment_before']
                ratio = runs[0]['duration_seconds'] / runs[1]['duration_seconds']
                assert ratio == pair['ratio']
                ratios.append(ratio)
            ratios = np.asarray(ratios)
            rng = np.random.default_rng(protocol['bootstrap']['seed'])
            medians = np.median(rng.choice(ratios, (protocol['bootstrap']['draws'], len(ratios))), axis=1)
            interval = np.percentile(medians, [2.5, 97.5]).tolist()
            median = float(np.median(ratios))
            cost = float(np.median(1 / ratios))
            accepted = (median >= registered['median_speedup_min']
                        and interval[0] > registered['paired_bootstrap_95_lower_min']
                        and cost <= registered.get('maximum_median_cost_ratio', float('inf')))
            stored = report['results'][comparison]
            assert stored['median_speedup'] == median and stored['ci95'] == interval
            assert stored['accepted'] == accepted
            assert accepted
            summaries[label][comparison] = dict(median_speedup=median, ci95=interval,
                                                median_cost_ratio=cost, accepted=accepted)
    sustained = read(EVIDENCE / 'current-sustained-ppo-20261017-a/report.json')
    analysis = read(EVIDENCE / 'current-sustained-analysis-20261017-a/report.json')
    frozen = read(EVIDENCE / 'current-sustained-frozen-20261017-a/report.json')
    context = EVIDENCE / 'current-sustained-context-20261017-a'
    assert sustained['passed'] and analysis['passed'] and frozen['passed']
    assert sustained['source_before'] == sustained['source_after'] == current
    assert sustained['duration_seconds'] >= read(context / 'protocol.json')['minimum_duration_seconds'] == 1800
    assert sustained['workers_reaped'] and sustained['exit_codes'] == [0] * 4
    assert sustained['parent_before']['fds'] == sustained['parent_after_close']['fds']
    for filename in ('report.json', 'iterations.jsonl', 'resources.jsonl', 'latest-checkpoint.json'):
        assert sha(EVIDENCE / 'current-sustained-ppo-20261017-a' / filename) == analysis['receipts'][filename]
    checkpoint = read(EVIDENCE / 'current-sustained-ppo-20261017-a/latest-checkpoint.json')
    payload = json.dumps(checkpoint['state'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    assert frozen['payload_sha256'] == hashlib.sha256(payload).hexdigest()
    assert frozen['version'] == analysis['updates'] == checkpoint['state']['version']
    index = read(context / 'index-cpu.json')
    assert index['mean_cores'] <= .25 and index['p95_cores'] <= .25
    contention = read(context / 'external-contention.json')
    assert contention['processes']
    result = dict(passed=True, source_sha256=current['sha256'], archived_files=len(manifest),
                  audited_fixed_workload_runs=audited_runs, results=summaries, quality=verified_quality,
                  bounded_pipeline_performance_milestone_passed=True,
                  scope='64 PPO updates/run, four complete horizon64 episodes/update, fixed seed42, hidden16, eight alternating pairs. Primary2x scaling plus median cost nonregression across1/11 players x cadence2/10. Includes diagnostics and in-loop saves; excludes startup/warmup/final save/close.',
                  sustained=dict(duration_seconds=analysis['duration_seconds'], updates=analysis['updates'],
                                 transitions=analysis['transitions'], tps=analysis['aggregate_tps'],
                                 memory=analysis['memory'], fds=analysis['fds'], minute_tps=analysis['minute_tps'],
                                 frozen_checkpoint_verified=True, workers_reaped=True,
                                 concurrent_external_build_observed=True, isolated_throughput_proven=False),
                  long_term_goal_complete=False, learning_generalization_proven=False,
                  current_installable_delivery_verified=False,
                  interrupted_batches=['pipeline-primary-20261017-a', 'pipeline-primary-20261017-b'],
                  manifest_sha256=sha(manifest_path), auditor_sha256=sha(Path(__file__)))
    output = EVIDENCE / 'pipeline-completion-audit-20261017-a'
    output.mkdir(exist_ok=False)
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(passed=True, archived_files=len(manifest), audited_runs=audited_runs,
                          bounded_milestone_passed=True, long_term_goal_complete=False)))


if __name__ == '__main__':
    main()
