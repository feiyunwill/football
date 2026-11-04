"""Execute the frozen primary PPO protocol serially and audit raw evidence."""
import argparse
import os
import threading
import time
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from validate import ROOT, sha, source_fingerprint
import quality

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


class IndexCpuMonitor:
    @staticmethod
    def ticks():
        values={}
        for path in Path('/proc').iterdir():
            if not path.name.isdigit(): continue
            try:
                if (path/'comm').read_text().strip()=='codebase-memory':
                    fields=(path/'stat').read_text().rsplit(')',1)[1].split()
                    values[path.name]=int(fields[11])+int(fields[12])
            except (OSError,ValueError): pass
        return values

    def __enter__(self):
        self.samples=[]; self.stop=threading.Event()
        self.before=self.ticks(); self.started=time.monotonic()
        self.thread=threading.Thread(target=self.sample,daemon=True); self.thread.start()
        return self

    def sample(self):
        previous=self.before; tick=self.started
        while True:
            stopping=self.stop.wait(1)
            now=time.monotonic(); current=self.ticks()
            cpu=sum(max(0,value-previous.get(pid,value)) for pid,value in current.items())/os.sysconf('SC_CLK_TCK')
            self.samples.append(dict(seconds=now-tick,cpu_seconds=cpu,cores=cpu/(now-tick)))
            previous=current; tick=now
            if stopping: break

    def __exit__(self,*unused):
        self.stop.set(); self.thread.join(timeout=5)
        if self.thread.is_alive(): raise RuntimeError('Index monitor failed to stop')

    def report(self):
        return dict(mean_cores=sum(s['cpu_seconds'] for s in self.samples)/sum(s['seconds'] for s in self.samples),
                    p95_cores=float(np.percentile([s['cores'] for s in self.samples],95)),samples=self.samples,
                    scope='Read-only proc sampling each second across build/start/warmup/timed loop/close; no index or system settings changed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--work-root',type=Path,required=True)
    args=parser.parse_args()
    protocol_dir = args.protocol.resolve()
    protocol = read(protocol_dir / 'protocol.json')
    runner = HERE / 'profile_pipeline_ppo.py'
    assert sha(runner) == protocol['runner_sha256']
    assert sha(Path(__file__)) == protocol['suite_sha256']
    assert source_fingerprint()['sha256'] == protocol['source_sha256']
    quality.verify(ROOT / protocol['quality'])
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    (output / 'protocol.json').write_bytes((protocol_dir / 'protocol.json').read_bytes())
    (output / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    results = {}
    for comparison in ('engine_pipeline', 'worker_scaling'):
        pairs = []
        for pair in range(protocol['pairs']):
            runs = {}
            for label in (('a', 'b') if pair % 2 == 0 else ('b', 'a')):
                name = f'{comparison}-{pair}-{label}'
                directory = output / name
                workers = 1 if comparison == 'worker_scaling' and label == 'a' else 4
                command = [sys.executable, str(runner), '--build-root',
                           '/tmp/football-native-assessment-20261015', '--work-root',
                           str(args.work_root.resolve() / name),
                           '--output', str(directory), '--workers', str(workers),
                           '--updates', str(protocol['updates_per_run']), '--seconds', '600']
                if comparison == 'engine_pipeline' and label == 'a':
                    command += ['--stage', protocol['baseline']]
                monitor=IndexCpuMonitor()
                with monitor, (output / (name + '.log')).open('w') as log:
                    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                   check=True, timeout=900)
                monitor_report=monitor.report()
                (directory/'index-cpu.json').write_text(json.dumps(monitor_report,indent=2)+'\n')
                assert monitor_report['mean_cores'] <= protocol['environment_gate']['maximum_index_mean_cores']
                assert monitor_report['p95_cores'] <= protocol['environment_gate']['maximum_index_p95_cores']
                run = read(directory / 'report.json')
                assert run['passed'] and run['workers_reaped']
                assert run['source_before'] == run['source_after'] == source_fingerprint()
                assert run['environment_before'] == run['environment_after']
                assert run['artifacts'] == run['artifacts_after']
                assert run['tooling'] == run['tooling_after']
                assert run['exit_codes'] == [0] * workers
                assert run['parent_before']['fds'] == run['parent_after_close']['fds']
                for filename in ('iterations.jsonl', 'resources.jsonl'):
                    assert sha(directory / filename) == run[filename + '_sha256']
                assert sha(directory / 'latest-checkpoint.json') == run['checkpoint_sha256']
                for artifact, digest in run['artifacts'].items():
                    assert sha(Path(artifact)) == digest
                runs[label] = (directory, run)
                print(json.dumps(dict(comparison=comparison, pair=pair, label=label,
                                      tps=run['transitions_per_second'])), flush=True)
            left, right = [runs[label][1] for label in ('a', 'b')]
            assert left['environment_before'] == right['environment_before']
            assert left['transitions'] == right['transitions']
            assert left['replay_sha256'] == right['replay_sha256']
            states = [read(runs[label][0] / 'latest-checkpoint.json')['state'] for label in ('a', 'b')]
            assert states[0] == states[1]
            streams = [(runs[label][0] / 'iterations.jsonl').read_text().splitlines() for label in ('a', 'b')]
            assert len(streams[0]) == len(streams[1]) == protocol['updates_per_run']
            for a, b in zip(*streams, strict=True):
                a, b = json.loads(a), json.loads(b)
                assert (a['version'], a['transitions'], a['update']) == (b['version'], b['transitions'], b['update'])
            pairs.append(dict(ratio=left['duration_seconds'] / right['duration_seconds'],
                              replay_sha256=left['replay_sha256'], learner_equal=True,
                              receipts={str(d / 'report.json'): sha(d / 'report.json') for d, _ in runs.values()}))
        ratios = np.array([p['ratio'] for p in pairs])
        rng = np.random.default_rng(protocol['bootstrap']['seed'])
        draws = np.median(rng.choice(ratios, (protocol['bootstrap']['draws'], len(ratios))), axis=1)
        low, high = np.percentile(draws, [2.5, 97.5]).tolist()
        median = float(np.median(ratios))
        gate = protocol['gates'][comparison]
        results[comparison] = dict(pairs=pairs, median_speedup=median, ci95=[low, high],
                                   accepted=median >= gate['median_speedup_min'] and low > gate['paired_bootstrap_95_lower_min'])
        (output / 'report.json').write_text(json.dumps(dict(status='running', results=results), indent=2) + '\n')
    report = dict(status='completed', results=results, all_primary_gates_passed=all(r['accepted'] for r in results.values()),
                  protocol_sha256=sha(protocol_dir / 'protocol.json'), source_sha256=source_fingerprint()['sha256'],
                  runner_sha256=sha(runner), suite_sha256=sha(Path(__file__)),
                  scope='Primary actual PPO loop only; excludes startup/warmup/final save/close; not learning competence or matrix acceptance')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
