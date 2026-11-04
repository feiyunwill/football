"""Thirty-minute final-source PPO baseline with observed foreign-load gates."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import numpy as np
import quality
from validate import sha, source_fingerprint

COMPILERS = {'cc1plus', 'c++', 'g++', 'gcc', 'clang', 'clang++', 'ninja', 'make', 'cmake', 'rustc'}


class HostMonitor:
    def snapshot(self):
        rows = {}
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            try:
                text = (path / 'stat').read_text()
                fields = text.rsplit(')', 1)[1].split()
                rows[int(path.name)] = dict(parent=int(fields[1]), start=int(fields[19]),
                                            ticks=int(fields[11])+int(fields[12]),
                                            comm=text[text.index('(')+1:text.rindex(')')])
            except (OSError, ValueError, IndexError):
                pass
        return rows

    def own(self, pid, rows):
        visited = set()
        while pid in rows and pid not in visited:
            if pid == os.getpid():
                return True
            visited.add(pid); pid = rows[pid]['parent']
        return False

    def __enter__(self):
        self.rows = self.snapshot(); self.tick = time.monotonic()
        self.samples = []; self.compiler_seen = False; self.error = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True); self.thread.start()
        return self

    def loop(self):
        try:
            previous = {(pid, r['start']): r['ticks'] for pid, r in self.rows.items()}
            while True:
                stopped = self.stop.wait(1)
                now = time.monotonic(); rows = self.snapshot()
                seconds = now-self.tick; foreign = index = 0; compilers = []
                for pid, row in rows.items():
                    delta = max(0, row['ticks']-previous.get((pid, row['start']), 0))
                    if not self.own(pid, rows):
                        foreign += delta
                        if row['comm'] in COMPILERS:
                            compilers.append(dict(pid=pid, comm=row['comm']))
                    if row['comm'] == 'codebase-memory':
                        index += delta
                hz = os.sysconf('SC_CLK_TCK')
                self.samples.append(dict(seconds=seconds, foreign_cores=foreign/hz/seconds,
                                         index_cores=index/hz/seconds, foreign_compilers=compilers))
                self.compiler_seen |= bool(compilers)
                previous = {(pid, r['start']): r['ticks'] for pid, r in rows.items()}
                self.tick = now
                if stopped:
                    break
        except BaseException as error:
            self.error = repr(error)

    def __exit__(self, *unused):
        self.stop.set(); self.thread.join(timeout=5)
        if self.thread.is_alive() or self.error:
            raise RuntimeError('Host monitor failed: ' + str(self.error))

    def report(self):
        values = self.samples
        mean = lambda key: sum(v[key]*v['seconds'] for v in values)/sum(v['seconds'] for v in values)
        return dict(foreign_mean_cores=mean('foreign_cores'),
                    foreign_p95_cores=float(np.percentile([s['foreign_cores'] for s in values], 95)),
                    index_mean_cores=mean('index_cores'),
                    index_p95_cores=float(np.percentile([s['index_cores'] for s in values], 95)),
                    compiler_seen=self.compiler_seen, samples=values,
                    scope='Read-only one-second /proc sampling; excludes wrapper and all descendant processes. Bounds observed WSL load, not physical host isolation; short-lived processes between samples may be missed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--quality', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    here = Path(__file__).resolve().parent
    accepted = quality.verify(args.quality)
    protocol = dict(minimum_seconds=1800, preflight_seconds=10, maximum_foreign_mean_cores=.25,
                    maximum_foreign_p95_cores=.25, maximum_index_mean_cores=.25,
                    maximum_index_p95_cores=.25, foreign_compilers_allowed=0,
                    compiler_detection='Interrupt run gracefully if a foreign compiler appears; retain rejected run',
                    source_sha256=source_fingerprint()['sha256'], quality=accepted,
                    tooling={p.name: sha(p) for p in (Path(__file__), here/'profile_sustained_ppo.py',
                             here/'analyze_sustained_ppo.py', here/'verify_sustained_checkpoint.py')})
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    with HostMonitor() as preflight:
        time.sleep(10)
    initial = preflight.report(); (output/'preflight.json').write_text(json.dumps(initial, indent=2)+'\n')
    def quiet(r):
        return not r['compiler_seen'] and all(r[k] <= .25 for k in
            ('foreign_mean_cores', 'foreign_p95_cores', 'index_mean_cores', 'index_p95_cores'))
    if not quiet(initial):
        (output/'report.json').write_text(json.dumps(dict(passed=False, status='preflight_not_quiet'))+'\n')
        return 1
    with HostMonitor() as monitor, (output/'run.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(here/'profile_sustained_ppo.py'),
            '--build-root', str(args.build_root), '--work-root', str(args.work_root),
            '--output', str(output/'evidence'), '--seconds', '1800'], stdout=log, stderr=subprocess.STDOUT)
        interrupted = False
        while process.poll() is None:
            if monitor.compiler_seen and not interrupted:
                try:
                    process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
                interrupted = True
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    host = monitor.report(); (output/'host-load.json').write_text(json.dumps(host, indent=2)+'\n')
    result = dict(passed=False, process_exit=process.returncode, environment_passed=quiet(host))
    if process.returncode == 0 and quiet(host):
        for script, name in (('analyze_sustained_ppo.py', 'analysis'), ('verify_sustained_checkpoint.py', 'frozen')):
            subprocess.run([sys.executable, str(here/script), '--evidence', str(output/'evidence'),
                            '--output', str(output/name)], check=True)
        quality.verify(args.quality)
        assert source_fingerprint()['sha256'] == protocol['source_sha256']
        assert all(sha(here/name)==digest for name,digest in protocol['tooling'].items())
        result['passed'] = True
    result['scope'] = 'Final-source duration, checkpoint, resources and observed low-foreign-load baseline; no worker speedup or learning inference'
    (output/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
