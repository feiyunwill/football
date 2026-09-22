# 2026-09-10: isolated installed Gymnasium replaces obsolete Gym plugin metadata checks.
# #!/usr/bin/env python3
# """Verify actual package metadata and lazy Gym registration in fresh processes."""
# import argparse
# import hashlib
# import json
# import os
# from pathlib import Path
# import subprocess
# import sys
# 
# ROOT = Path(__file__).resolve().parents[2]
# 
# 
# def main():
#     parser = argparse.ArgumentParser(description=__doc__)
#     parser.add_argument('--output', type=Path, required=True)
#     args = parser.parse_args()
#     output = args.output.resolve()
#     output.mkdir(parents=True, exist_ok=False)
#     metadata = output / 'metadata'
#     metadata.mkdir()
#     paths = [Path(__file__), ROOT / 'setup.py', ROOT / 'pyproject.toml',
#              ROOT / 'gfootball/__init__.py', ROOT / 'gfootball/env/__init__.py']
#     paths.extend((ROOT / 'gfootball/frame_sync').glob('*.py'))
#     sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
#     before = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
#     commands = [('metadata', [sys.executable, '-c',
#         'import setuptools.build_meta as b,sys; '
#         'print(b.prepare_metadata_for_build_wheel(sys.argv[1]))', str(metadata)])]
#     probe = '''
# import importlib.metadata, json, sys
# order = sys.argv[1]
# if order == 'data_first':
#     # 2026-09-10: use the actual data module name in the import-order probe.
#     # import gfootball.frame_sync.save
#     import gfootball.frame_sync.save_data
#     assert not any(name in sys.modules for name in ('gym', 'numpy', 'cv2', 'gfootball_engine'))
# import gym
# import gfootball
# from gym.envs.registration import registry
# specs = registry.env_specs if hasattr(registry, 'env_specs') else registry
# key = 'GFootball-11_vs_11_easy_stochastic-SMM-v0'
# assert key in specs
# assert specs[key].entry_point == 'gfootball.env:create_environment'
# count = len(specs)
# gfootball.register_gym_envs()
# gfootball.register_gym_envs()
# assert len(specs) == count
# assert 'gfootball_engine' not in sys.modules and 'gfootball.env' not in sys.modules
# plugins = list(importlib.metadata.entry_points(group='gym.envs'))
# assert any(p.name == 'gfootball' and p.value == 'gfootball:register_gym_envs' for p in plugins)
# print(json.dumps(dict(passed=True, assertions=6 if order == 'data_first' else 5,
#                      order=order, gym=gym.__version__, registered=count)))
# '''
#     commands += [(order, [sys.executable, '-c', probe, order])
#                  for order in ('gym_first', 'data_first')]
#     environment = dict(os.environ)
#     environment['PYTHONPATH'] = os.pathsep.join((str(metadata), str(ROOT),
#                                                environment.get('PYTHONPATH', '')))
#     results = {}
#     for name, argv in commands:
#         log = output / (name + '.log')
#         with log.open('xb') as stream:
#             result = subprocess.run(argv, cwd=ROOT, env=environment,
#                                     stdout=stream, stderr=subprocess.STDOUT,
#                                     timeout=90, check=False)
#         if result.returncode:
#             raise RuntimeError(f'{name} failed; see {log}')
#         if name != 'metadata':
#             results[name] = json.loads(log.read_text(encoding='utf-8').splitlines()[-1])
#     if {p.relative_to(ROOT).as_posix(): sha(p) for p in paths} != before:
#         raise RuntimeError('Registration sources changed during validation')
#     report = dict(passed=True, assertions=sum(r['assertions'] for r in results.values()),
#                   skipped=0, results=results, sources=before,
#                   logs={p.name: sha(p) for p in output.glob('*.log')},
#                   metadata={p.relative_to(metadata).as_posix(): sha(p)
#                             for p in metadata.rglob('*') if p.is_file()},
#                   python=sys.version, executable=sys.executable,
#                   package_build_executed=False, dependency_compatibility_accepted=False,
#                   actual_Gym_registration=True, formal_product_acceptance=False)
#     (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
#     print(json.dumps({k: v for k, v in report.items() if k not in ('sources', 'metadata')}, indent=2))
# 
# 
# if __name__ == '__main__':
#     main()

#!/usr/bin/env python3
"""Verify installed Gymnasium registration in isolated fresh Python processes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = [Path(__file__), ROOT / 'setup.py', ROOT / 'pyproject.toml',
             ROOT / 'requirements.txt', ROOT / 'gfootball/__init__.py',
             ROOT / 'gfootball/gymnasium.py']
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    probe = r'''
import importlib.metadata, json, re, sys
from pathlib import Path
order = sys.argv[1]
assertions = 0
def verify(condition):
    global assertions
    assert condition
    assertions += 1
verify(importlib.util.find_spec('gym') is None)
if order == 'data_first':
    import gfootball.frame_sync.save_data
    verify(not any(n in sys.modules for n in
                   ('gymnasium', 'numpy', 'cv2', 'gfootball_engine')))
import gymnasium as gym
import gfootball.gymnasium
import gfootball
from gymnasium.envs.registration import registry
verify('gfootball_engine' not in sys.modules and 'gfootball.env' not in sys.modules)
key = 'GFootball-11_vs_11_easy_stochastic-SMM-v0'
verify(key in registry)
verify(registry[key].entry_point == 'gfootball.gymnasium:FootballEnv')
verify(registry[key].kwargs == dict(env_name='11_vs_11_easy_stochastic',
                                    representation='extracted'))
verify(not any(k.startswith('GFootball-tests-') for k in registry))
count = len(registry)
gfootball.register_gymnasium_envs()
gfootball.register_gymnasium_envs()
verify(len(registry) == count)
distribution = importlib.metadata.distribution('gfootball')
requirements = distribution.requires
names = {re.split(r'[<>=~! ;\[]', r)[0].lower().replace('_', '-') for r in requirements}
verify('gymnasium' in names and 'gym' not in names)
verify('pygame-ce' in names and 'pygame' not in names)
verify('six' in names)
verify(distribution.metadata['Requires-Python'] == '>=3.10')
verify(not any(p.group == 'gym.envs' for p in distribution.entry_points))
package = Path(gfootball.__file__).resolve().parent
verify('site-packages' in package.parts)
verify(Path(distribution.locate_file('gfootball/__init__.py')).resolve() == package / '__init__.py')
import hashlib
files = ['__init__.py', 'gymnasium.py', 'env/legacy_api.py', 'env/__init__.py']
installed = {'gfootball/' + name: hashlib.sha256((package / name).read_bytes()).hexdigest()
             for name in files}
print(json.dumps(dict(passed=True, assertions=assertions, order=order,
                     gymnasium=gym.__version__, registered=count,
                     installed_package=str(package), installed_sources=installed,
                     requires=requirements)))
'''
    results = {}
    for order in ('gym_first', 'data_first'):
        log = output / (order + '.log')
        # -I rejects source-checkout/PYTHONPATH shadowing of the installed wheel.
        with log.open('xb') as stream:
            result = subprocess.run([sys.executable, '-I', '-c', probe, order],
                                    cwd=output, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=60, check=False)
        if result.returncode:
            raise RuntimeError(f'{order} failed; see {log}')
        value = json.loads(log.read_text(encoding='utf-8').splitlines()[-1])
        if not value['passed'] or value['assertions'] < 14:
            raise RuntimeError('Incomplete installed registration checks')
        for name, digest in value['installed_sources'].items():
            if sha(ROOT / name) != digest:
                raise RuntimeError('Installed source differs from current checkout: ' + name)
        results[order] = value
    if {p.relative_to(ROOT).as_posix(): sha(p) for p in paths} != before:
        raise RuntimeError('Sources changed during registration checks')
    report = dict(passed=True, assertions=sum(r['assertions'] for r in results.values()),
                  skipped=0, results=results, sources=before,
                  logs={p.name: sha(p) for p in output.glob('*.log')},
                  python=sys.version, executable=sys.executable,
                  installed_distribution_executed=True, actual_Gymnasium_registration=True,
                  old_Gym_installed=False, formal_product_acceptance=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('sources', 'results')}, indent=2))


if __name__ == '__main__':
    main()
