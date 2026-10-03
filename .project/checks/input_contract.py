#!/usr/bin/env python3
"""Formal shared input acceptance: current Python, native engine and real SDL/XTEST.
No old stage receipt substitutes for execution. No device latency acceptance.
"""
from pathlib import Path
import argparse,gzip,hashlib,json,os,platform,signal,sys,time,shlex,subprocess,tarfile,tempfile
# 2026-09-14: both build modes must contain the actual product entry points.
# from native_boundary import ROOT,require
from native_boundary import ROOT,TARGETS,require
import performance_regression as runner
import match_benchmark as benchmark

# 2026-09-13: include independent product wire/time oracles and self-contained actual replay.
# CONTRACTS={
CONTRACTS={
 # 2026-09-14: real tactical state, actor identity, role symmetry and fresh actions are mandatory.
 'engine_ai_tactics_contract':(7288,{'symmetry_cases':600}),
 'engine_ai_tactics_roles_contract':(3601,{'role_mirror_cases':1800,'failed':0}),
  'engine_ai_tactical_state_contract':(27000,{'frames':960,'actual_gameenv':True}),
 # 2026-09-14: native controls must retain moving touches and stationary ball handling.
 'engine_ai_touch_contract':(586,{'seeds':3,'ball_control_assets':270,'quiet_idle':24,'actual_gameenv':True}),
 # 2026-09-13: native display-only capture keeps default RGB and logical state.
 'engine_frame_capture_contract':(150,{'engine_frames':161,'images':5,'uncaptured_renders':5,'rejections':16,'headless_policy':True,'solid_colours':3,'odd_width':321,'actual_gameenv':True}),
 # 2026-09-13: slow authority lead and real unavailable-player AI recovery are mandatory.
 #     'engine_native_publication_clock_contract':(30559,{'cadence_frames':6000,'concurrent_frames':512,'edge_frames':6}),
 'engine_native_publication_clock_contract':(30559,{'cadence_frames':6000,'concurrent_frames':512,'edge_frames':6,'resync_frames':572,'resync_max_lead':2}),
  'engine_native_bot_selection_contract':(8751,{'prefix_frames':512,'recorded_tail_frames':1566,'unavailable_frames':105,'recovered_frames':66,'opponent_restart_wait_frames':66,'actual_gameenv':True}),
 'engine_native_match_contract':(44000,{'clock_events':10000,'engine_frames':600,'actual_gameenv':True,'native_contract':1}),
 # 2026-09-13: shared history and joined transport ownership are mandatory input contracts.
 'engine_native_transport_pump_contract':(20333,{'ledger_frames':4000,'concurrent_frames':128,'joined_lifetimes':64}),
 # 2026-09-13: render-owner UI service is a mandatory Release/ASan contract.
 'engine_render_service_contract':(20500,{'timeline_events':10000,'nested_lifetimes':64,'thread_owners':8,'render_sampling':True}),
 # 2026-09-13: local input belongs to the consumed fixed deadline, including debt.
 'engine_native_input_timeline_contract':(74000,{'offline_frames':30003,'clock_events':10000,'capture_observations':12000}),
 # 2026-09-13: SDL owner/game worker lifetime and concurrent local input handoff.
 'engine_native_ui_owner_contract':(20000,{'joined_lifetimes':64,'handoff_frames':256,'concurrent_observations':20000}),
 'engine_native_input_buffer_contract':(92699,{'operations':20168}),
 'engine_native_input_admission_contract':(16248,{}),
 'engine_native_presentation_contract':(10102,{'ordinary_frames':1000}),
 'engine_server_input_window_contract':(552018,{'frames':18000,'fixed_bytes':3728}),
 'engine_native_input_gameenv_contract':(3901,{'actual_gameenv':True,'confirmed_frames':82}),
}

def verify_bot_selection_reference():
    """Replay the archived independent semantic oracle before trusting its fixtures."""
    base=ROOT/'.project/optimization/baselines'
    manifest=json.loads((base/'bot_selection_v2.json').read_text())
    ecs=json.loads((base/'ecs_v3.json').read_text())
    require(manifest['format']==2 and manifest['id']=='bot-selection-manual-turn-semantic-20261001' and
            manifest['source_commit']==ecs['source_commit'] and
            manifest['semantic_patch_sha256']==ecs['semantic_patch_sha256'] and
            manifest['engine_sha256']==ecs['binaries']['engine']['sha256'],
            'Bot-selection semantic reference source changed')
    require(benchmark.file_hash(ROOT/'.project/optimization/baselines/ecs_v3_manual_turn.patch')==
            manifest['semantic_patch_sha256'], 'Bot-selection semantic patch changed')
    for relative,expected in (manifest['source_fixture_sha256'] |
                              manifest['aligned_fixture_sha256']).items():
        require(benchmark.file_hash(ROOT/relative)==expected,
                'Bot-selection replay or aligned fixture changed: '+relative)
    patch=manifest['oracle_patch']
    require(benchmark.file_hash(ROOT/patch['path'])==patch['sha256'],
            'Bot-selection oracle source changed')
    def archived(entry):
        path=(ROOT/entry['path']).resolve()
        require(path.is_relative_to(ROOT), 'Bot-selection archive escapes checkout')
        require(benchmark.file_hash(path)==entry['compressed_sha256'],
                'Bot-selection compressed archive changed')
        raw=gzip.decompress(path.read_bytes())
        require(hashlib.sha256(raw).hexdigest()==entry['sha256'],
                'Bot-selection archive decompressed differently')
        return raw
    engine=archived(ecs['binaries']['engine'])
    binary=archived(manifest['oracle_binary'])
    expected=archived(manifest['oracle_output'])
    require(len(expected.splitlines())==manifest['oracle_output']['lines']==603 and
            manifest['contract']=={'prefix_frames':512,'original_tail_frames':57,
                                    'neutral_tail_frames':34,'aligned_tail_frames':91,
                                    'unavailable_frames':30,'recovered_frames':1},
            'Bot-selection reference coverage changed')
    with tempfile.TemporaryDirectory(prefix='football-bot-semantic-oracle-') as directory:
        temporary=Path(directory)
        (temporary/'libfootball_engine.so').write_bytes(engine)
        executable=temporary/'engine_native_bot_selection_contract'
        executable.write_bytes(binary)
        executable.chmod(0o755)
        environment=dict(os.environ,LD_LIBRARY_PATH=str(temporary),
                         GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'))
        environment.pop('LD_PRELOAD',None)
        completed=subprocess.run([str(executable)],cwd=ROOT,env=environment,
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        require(completed.returncode==0 and completed.stdout==expected,
                'Archived bot-selection oracle no longer reproduces')
    requeue=verify_bot_selection_requeue()
    momentum=verify_bot_selection_momentum()
    assist=verify_bot_selection_assist()
    handfeel=verify_bot_selection_ai_mirror()
    return {'manifest_sha256':benchmark.file_hash(base/'bot_selection_v2.json'),
              'oracle_output_sha256':manifest['oracle_output']['sha256'],
              'prefix_frames':512,'aligned_tail_frames':91,**requeue,**momentum,**assist,**handfeel}

def verify_bot_selection_requeue():
    """Keep the archived old oracle while validating a separately versioned turn."""
    base=ROOT/'.project/optimization/baselines'
    path=base/'bot_selection_requeue_20261001.json'
    manifest=json.loads(path.read_text())
    require(manifest['format']==1 and
            manifest['id']=='bot-selection-manual-requeue-20261001' and
            manifest['historical_reference']=='.project/optimization/baselines/bot_selection_v2.json' and
            manifest['raw_oracles']['independent_runs']==2 and
            manifest['contract']=={'prefix_frames':512,'tail_frames':91,
                                   'first_changed_frame':123,'changed_prefix_hashes':389,
                                   'unavailable_frames':18,'recovered_frames':1},
            'Manual-turn replay reference changed')
    source=manifest['candidate_source']
    snapshot=base/'bot_selection_requeue_20261001_source.cpp.gz'
    require(source['path']=='engine/src/onthepitch/player/humanoid/humanoid.cpp' and
            hashlib.sha256(gzip.decompress(snapshot.read_bytes())).hexdigest()==source['sha256'],
            'Archived manual-turn engine source differs from reviewed oracle')
    archive=manifest['archive']
    archive_path=(ROOT/archive['path']).resolve()
    require(archive_path.is_relative_to(ROOT) and
            benchmark.file_hash(archive_path)==archive['sha256'],
            'Manual-turn oracle archive changed')
    with tarfile.open(archive_path,'r:gz') as package:
        recorded=json.load(package.extractfile('manifest.json'))
        require(recorded['format']=='bot-selection-requeue-oracle-v1' and
                set(package.getnames())==set(recorded['files'])|{'manifest.json'},
                'Manual-turn oracle archive has unexpected members')
        raw={name:package.extractfile(name).read() for name in recorded['files']}
    require(all(hashlib.sha256(data).hexdigest()==recorded['files'][name]
                for name,data in raw.items()),'Manual-turn oracle member changed')
    require(recorded['files']['generator.cpp']==archive['generator_sha256'] and
            recorded['files']['candidate.patch']==archive['candidate_patch_sha256'],
            'Manual-turn generator or candidate patch changed')
    for kind in ('hashes','tail'):
        first=raw[f'{kind}-run1.inc']
        require(first==raw[f'{kind}-run2.inc'] and
                hashlib.sha256(first).hexdigest()==
                manifest['raw_oracles'][f'{kind}_sha256'],
                'Manual-turn oracle runs differ')
        require(len(first.splitlines())==(512 if kind=='hashes' else 91),
                'Manual-turn replay coverage changed')
    for relative,expected in manifest['fixtures'].items():
        fixture=(ROOT/relative).resolve()
        require(fixture.is_relative_to(ROOT) and
                benchmark.file_hash(fixture)==expected,
                'Manual-turn fixture changed: '+relative)
        kind='hashes' if 'hashes_' in relative else 'tail'
        require(fixture.read_bytes().partition(b'\n')[2]==raw[f'{kind}-run1.inc'],
                'Manual-turn fixture differs from recorded replay: '+relative)
    old=(ROOT/'engine/tests/fixtures/native_bot_transition_hashes_20261001.inc').read_text().splitlines()[1:]
    new=raw['hashes-run1.inc'].decode().splitlines()
    changed=[i for i,(a,b) in enumerate(zip(old,new)) if a!=b]
    require(len(old)==len(new)==512 and changed and changed[0]==123 and
            len(changed)==389,
            'Manual-turn semantic divergence moved')
    def tail_input(line):
        values=line.strip().rstrip(',').strip('{}').split(',')
        return (float.fromhex(values[0].removesuffix('f')),
                float.fromhex(values[1].removesuffix('f')),int(values[2]))
    old_tail=(ROOT/'engine/tests/fixtures/native_bot_transition_tail_20261001.inc').read_text().splitlines()[1:]
    new_tail=raw['tail-run1.inc'].decode().splitlines()
    require(len(old_tail)==len(new_tail)==91 and
            all(tail_input(a)==tail_input(b) for a,b in zip(old_tail,new_tail)),
            'Manual-turn tail input sequence changed')
    for run in (1,2):
        log=raw[f'run{run}.log'].decode()
        require(log.startswith('exit=0\n') and
                'hash_mismatches=389 / 512' in log and
                '"unavailable_frames":18' in log and
                '"recovered_frames":1' in log,
                'Manual-turn replay run did not complete')
    return {'manual_turn_manifest_sha256':benchmark.file_hash(path),
            'manual_turn_archive_sha256':archive['sha256'],
            'manual_turn_first_changed_frame':123,
            'manual_turn_changed_hashes':389}

def verify_bot_selection_momentum():
    """Validate the next fixed replay without rewriting the earlier oracle."""
    base=ROOT/'.project/optimization/baselines'
    path=base/'bot_selection_momentum_20261001.json'
    manifest=json.loads(path.read_text())
    require(manifest['format']==1 and
            manifest['id']=='bot-selection-manual-momentum-20261001' and
            manifest['historical_reference']=='.project/optimization/baselines/bot_selection_requeue_20261001.json' and
            manifest['raw_oracles']['independent_runs']==2 and
            manifest['contract']=={'prefix_frames':512,'tail_frames':91,
                                   'first_changed_frame_vs_prior':134,
                                   'changed_prefix_hashes_vs_prior':378,
                                   'unavailable_frames':13,'recovered_frames':1},
            'Manual momentum replay reference changed')
    source=manifest['candidate_source']
    current_snapshot=base/'bot_selection_handfeel_20261002_historical_humanoid.cpp.gz'
    require(source['path']=='engine/src/onthepitch/player/humanoid/humanoid.cpp' and
            hashlib.sha256(gzip.decompress(current_snapshot.read_bytes())).hexdigest()==source['sha256'],
            'Archived manual momentum engine source differs from reviewed oracle')
    snapshot=manifest['historical_source_snapshot']
    snapshot_path=(ROOT/snapshot['path']).resolve()
    require(snapshot_path.is_relative_to(ROOT) and
            benchmark.file_hash(snapshot_path)==snapshot['sha256'] and
            hashlib.sha256(gzip.decompress(snapshot_path.read_bytes())).hexdigest()==
            snapshot['decompressed_sha256']==
            json.loads((base/'bot_selection_requeue_20261001.json').read_text())['candidate_source']['sha256'],
            'Archived prior source changed')
    archive=manifest['archive']
    archive_path=(ROOT/archive['path']).resolve()
    require(archive_path.is_relative_to(ROOT) and
            benchmark.file_hash(archive_path)==archive['sha256'],
            'Manual momentum oracle archive changed')
    with tarfile.open(archive_path,'r:gz') as package:
        recorded=json.load(package.extractfile('manifest.json'))
        require(recorded['format']=='bot-selection-momentum-oracle-v1' and
                set(package.getnames())==set(recorded['files'])|{'manifest.json'},
                'Manual momentum archive has unexpected members')
        raw={name:package.extractfile(name).read() for name in recorded['files']}
    require(all(hashlib.sha256(data).hexdigest()==recorded['files'][name]
                for name,data in raw.items()) and
            recorded['files']['generator.cpp']==archive['generator_sha256'] and
            recorded['files']['candidate.patch']==archive['candidate_patch_sha256'],
            'Manual momentum generator, patch or replay member changed')
    for kind in ('hashes','tail'):
        first=raw[f'{kind}-run1.inc']
        require(first==raw[f'{kind}-run2.inc'] and
                hashlib.sha256(first).hexdigest()==manifest['raw_oracles'][f'{kind}_sha256'] and
                len(first.splitlines())==(512 if kind=='hashes' else 91),
                'Manual momentum independent replays differ')
    for relative,expected in manifest['fixtures'].items():
        fixture=(ROOT/relative).resolve()
        kind='hashes' if 'hashes_' in relative else 'tail'
        require(fixture.is_relative_to(ROOT) and
                benchmark.file_hash(fixture)==expected and
                fixture.read_bytes().partition(b'\n')[2]==raw[f'{kind}-run1.inc'],
                'Manual momentum fixture differs from replay: '+relative)
    prior=(ROOT/'engine/tests/fixtures/native_bot_transition_hashes_requeue_20261001.inc').read_text().splitlines()[1:]
    current=raw['hashes-run1.inc'].decode().splitlines()
    changed=[i for i,(a,b) in enumerate(zip(prior,current)) if a!=b]
    require(len(prior)==len(current)==512 and changed[0]==134 and len(changed)==378,
            'Manual momentum semantic divergence moved')
    def tail_input(line):
        values=line.strip().rstrip(',').strip('{}').split(',')
        return (float.fromhex(values[0].removesuffix('f')),
                float.fromhex(values[1].removesuffix('f')),int(values[2]))
    previous_tail=(ROOT/'engine/tests/fixtures/native_bot_transition_tail_requeue_20261001.inc').read_text().splitlines()[1:]
    new_tail=raw['tail-run1.inc'].decode().splitlines()
    require(len(previous_tail)==len(new_tail)==91 and
            all(tail_input(a)==tail_input(b) for a,b in zip(previous_tail,new_tail)),
            'Manual momentum tail input sequence changed')
    for run in (1,2):
        log=raw[f'run{run}.log'].decode()
        require(log.startswith('exit=0\n') and
                'hash_mismatches=389 / 512' in log and
                '"unavailable_frames":13' in log and
                '"recovered_frames":1' in log,
                'Manual momentum replay run did not complete')
    return {'manual_momentum_manifest_sha256':benchmark.file_hash(path),
            'manual_momentum_archive_sha256':archive['sha256'],
            'manual_momentum_first_changed_frame':134,
            'manual_momentum_changed_hashes':378}

def verify_bot_selection_assist():
    """Check the reviewed manual-assist replay and its extended selection tail."""
    base=ROOT/'.project/optimization/baselines'
    path=base/'bot_selection_assist_20261001.json'
    manifest=json.loads(path.read_text())
    require(manifest['format']==1 and
            manifest['id']=='bot-selection-manual-assist-20261001' and
            manifest['historical_reference']=='.project/optimization/baselines/bot_selection_momentum_20261001.json' and
            manifest['raw_oracles']['independent_runs']==2 and
            manifest['contract']=={'prefix_frames':512,'tail_frames':245,
                                   'prior_tail_frames':91,'additional_neutral_frames':154,
                                   'first_changed_frame_vs_prior':138,
                                   'changed_prefix_hashes_vs_prior':374,
                                   'unavailable_frames':30,'recovered_frames':1},
            'Manual assist replay reference changed')
    sources=manifest['candidate_sources']
    controller='engine/src/onthepitch/player/controller/playercontroller.cpp'
    humanoid='engine/src/onthepitch/player/humanoid/humanoid.cpp'
    previous=json.loads((base/'bot_selection_momentum_20261001.json').read_text())
    historical={
        controller:base/'bot_selection_handfeel_20261002_historical_playercontroller.cpp.gz',
        humanoid:base/'bot_selection_handfeel_20261002_historical_humanoid.cpp.gz',
    }
    require(set(sources)=={controller,humanoid} and
            all(hashlib.sha256(gzip.decompress(historical[relative].read_bytes())).hexdigest()==digest
                for relative,digest in sources.items()) and
            sources[humanoid]==previous['candidate_source']['sha256'],
            'Archived manual assist engine source differs from reviewed oracle')
    snapshot=manifest['historical_source_snapshot']
    snapshot_path=(ROOT/snapshot['path']).resolve()
    require(snapshot['path']=='.project/optimization/baselines/bot_selection_momentum_20261001_playercontroller.cpp.gz' and
            snapshot_path.is_relative_to(ROOT) and
            benchmark.file_hash(snapshot_path)==snapshot['sha256'] and
            hashlib.sha256(gzip.decompress(snapshot_path.read_bytes())).hexdigest()==
            snapshot['decompressed_sha256']==
            'b429890cacf04e4fea43a9d3d5bb465a326fc0031f1d7f2ac17199ccea4e9064',
            'Archived pre-assist controller source changed')
    archive=manifest['archive']
    archive_path=(ROOT/archive['path']).resolve()
    require(archive['path']=='.project/optimization/baselines/bot_selection_assist_20261001.tar.gz' and
            archive_path.is_relative_to(ROOT) and
            benchmark.file_hash(archive_path)==archive['sha256'],
            'Manual assist oracle archive changed')
    expected_members={'generator.cpp','candidate.patch',
                      'hashes-run1.inc','hashes-run2.inc','tail-run1.inc','tail-run2.inc',
                      'run1.log','run2.log'}
    with tarfile.open(archive_path,'r:gz') as package:
        recorded=json.load(package.extractfile('manifest.json'))
        require(recorded['format']=='bot-selection-assist-oracle-v1' and
                set(recorded['files'])==expected_members and
                set(package.getnames())==expected_members|{'manifest.json'},
                'Manual assist archive has unexpected members')
        raw={name:package.extractfile(name).read() for name in expected_members}
    require(all(hashlib.sha256(data).hexdigest()==recorded['files'][name]
                for name,data in raw.items()) and
            recorded['files']['generator.cpp']==archive['generator_sha256'] and
            recorded['files']['candidate.patch']==archive['candidate_patch_sha256'],
            'Manual assist generator, patch or replay member changed')
    for kind,frames in (('hashes',512),('tail',245)):
        first=raw[f'{kind}-run1.inc']
        require(first==raw[f'{kind}-run2.inc'] and
                hashlib.sha256(first).hexdigest()==manifest['raw_oracles'][f'{kind}_sha256'] and
                len(first.splitlines())==frames,
                'Manual assist independent replays differ')
    expected_fixtures={f'engine/tests/fixtures/native_bot_transition_{kind}_assist_20261001.inc'
                       for kind in ('hashes','tail')}
    require(set(manifest['fixtures'])==expected_fixtures,
            'Manual assist fixture paths changed')
    for relative,expected in manifest['fixtures'].items():
        fixture=(ROOT/relative).resolve()
        kind='hashes' if 'hashes_' in relative else 'tail'
        require(fixture.is_relative_to(ROOT) and
                benchmark.file_hash(fixture)==expected and
                fixture.read_bytes().partition(b'\n')[2]==raw[f'{kind}-run1.inc'],
                'Manual assist fixture differs from replay: '+relative)
    prior=(ROOT/'engine/tests/fixtures/native_bot_transition_hashes_momentum_20261001.inc').read_text().splitlines()[1:]
    current=raw['hashes-run1.inc'].decode().splitlines()
    changed=[i for i,(a,b) in enumerate(zip(prior,current)) if a!=b]
    require(len(prior)==len(current)==512 and changed[0]==138 and len(changed)==374,
            'Manual assist semantic divergence moved')
    def fields(line):
        return line.strip().rstrip(',').strip('{}').split(',')
    def tail_input(line):
        values=fields(line)
        return (float.fromhex(values[0].removesuffix('f')),
                float.fromhex(values[1].removesuffix('f')),int(values[2]))
    previous_tail=(ROOT/'engine/tests/fixtures/native_bot_transition_tail_momentum_20261001.inc').read_text().splitlines()[1:]
    new_tail=raw['tail-run1.inc'].decode().splitlines()
    require(len(previous_tail)==91 and len(new_tail)==245 and
            all(tail_input(a)==tail_input(b)
                for a,b in zip(previous_tail,new_tail[:91])) and
            all(tail_input(line)==(0.0,0.0,0) for line in new_tail[91:]) and
            int(fields(new_tail[-1])[3])==-1,
            'Manual assist extended tail inputs or selection changed')
    for run in (1,2):
        log=raw[f'run{run}.log'].decode()
        require(log.startswith('exit=0\n') and
                '"recorded_tail_frames":245' in log and
                'additional_tail_frames=154' in log and
                '"unavailable_frames":30' in log and
                '"recovered_frames":1' in log,
                'Manual assist replay run did not complete')
    return {'manual_assist_manifest_sha256':benchmark.file_hash(path),
            'manual_assist_archive_sha256':archive['sha256'],
            'manual_assist_first_changed_frame':138,
            'manual_assist_changed_hashes':374,
            'manual_assist_tail_frames':245}

def verify_bot_selection_handfeel():
    """Keep the previous handfeel oracle independently reviewable."""
    base=ROOT/'.project/optimization/baselines'
    path=base/'bot_selection_handfeel_20261002.json'
    manifest=json.loads(path.read_text())
    contract={'prefix_frames':512,'tail_frames':245,
              'first_changed_frame_vs_prior':0,'changed_prefix_hashes_vs_prior':512,
              'first_unavailable_tail_frame':77,'unavailable_frames':105,
              'recovered_frames':62,'opponent_restart_wait_frames':62}
    require(manifest['format']==1 and
            manifest['id']=='bot-selection-current-handfeel-20261002' and
            manifest['historical_reference']=='.project/optimization/baselines/bot_selection_assist_20261001.json' and
            manifest['contract']==contract and
            manifest['raw_oracles']['independent_runs']==2,
            'Current handfeel reference contract changed')
    historical=json.loads((base/'bot_selection_assist_20261001.json').read_text())
    momentum=json.loads((base/'bot_selection_momentum_20261001.json').read_text())
    for key,expected in (('historical_source_snapshot',momentum['candidate_source']['sha256']),
                         ('historical_controller_snapshot',historical['candidate_sources'][
                             'engine/src/onthepitch/player/controller/playercontroller.cpp'])):
        item=manifest[key]
        snapshot=(ROOT/item['path']).resolve()
        require(snapshot.is_relative_to(ROOT) and
                benchmark.file_hash(snapshot)==item['sha256'] and
                hashlib.sha256(gzip.decompress(snapshot.read_bytes())).hexdigest()==
                item['decompressed_sha256']==expected,
                'Historical handfeel source snapshot changed: '+key)
    archive=manifest['archive']
    archive_path=(ROOT/archive['path']).resolve()
    require(archive_path.is_relative_to(ROOT) and
            benchmark.file_hash(archive_path)==archive['sha256'],
            'Current handfeel oracle archive changed')
    expected_members={'generator.cpp','hashes-run1.inc','hashes-run2.inc',
                      'tail-run1.inc','tail-run2.inc','run1.log','run2.log'}
    with tarfile.open(archive_path,'r:gz') as package:
        recorded=json.load(package.extractfile('manifest.json'))
        require(recorded['format']=='bot-selection-handfeel-oracle-v1' and
                set(recorded['files'])==expected_members and
                set(package.getnames())==expected_members|{'manifest.json'},
                'Current handfeel oracle archive members changed')
        raw={name:package.extractfile(name).read() for name in expected_members}
    require(all(hashlib.sha256(data).hexdigest()==recorded['files'][name]
                for name,data in raw.items()) and
            recorded['files']['generator.cpp']==archive['generator_sha256'],
            'Historical handfeel generator or archive member changed')
    for kind,frames in (('hashes',512),('tail',245)):
        first=raw[f'{kind}-run1.inc']
        require(first==raw[f'{kind}-run2.inc'] and
                hashlib.sha256(first).hexdigest()==manifest['raw_oracles'][f'{kind}_sha256'] and
                len(first.splitlines())==frames,
                'Current handfeel independent replays differ')
        relative=f'engine/tests/fixtures/native_bot_transition_{kind}_handfeel_20261002.inc'
        fixture=(ROOT/relative).resolve()
        require(set(manifest['fixtures'])=={
                    f'engine/tests/fixtures/native_bot_transition_{k}_handfeel_20261002.inc'
                    for k in ('hashes','tail')} and
                fixture.is_relative_to(ROOT) and
                benchmark.file_hash(fixture)==manifest['fixtures'][relative] and
                fixture.read_bytes().partition(b'\n')[2]==first,
                'Current handfeel fixture differs from recorded replay: '+kind)
    previous=(ROOT/'engine/tests/fixtures/native_bot_transition_hashes_assist_20261001.inc').read_text().splitlines()[1:]
    current=raw['hashes-run1.inc'].decode().splitlines()
    changed=[i for i,(a,b) in enumerate(zip(previous,current)) if a!=b]
    require(len(previous)==len(current)==512 and changed[0]==0 and len(changed)==512,
            'Current handfeel semantic divergence changed')
    def fields(line):
        return line.strip().rstrip(',').strip('{}').split(',')
    def tail_input(line):
        values=fields(line)
        return (float.fromhex(values[0].removesuffix('f')),
                float.fromhex(values[1].removesuffix('f')),int(values[2]))
    prior_tail=(ROOT/'engine/tests/fixtures/native_bot_transition_tail_assist_20261001.inc').read_text().splitlines()[1:]
    current_tail=raw['tail-run1.inc'].decode().splitlines()
    selected=[int(fields(line)[3]) for line in current_tail]
    require(len(prior_tail)==len(current_tail)==245 and
            all(tail_input(a)==tail_input(b) for a,b in zip(prior_tail,current_tail)) and
            selected[:77]==[8]*77 and selected[77:182]==[-1]*105 and
            selected[182:]==[9]*63,
            'Current handfeel fixed inputs or real selection transition changed')
    for run in (1,2):
        log=raw[f'run{run}.log'].decode()
        require(log.startswith('exit=0\n') and
                json.loads(log.split('\n',1)[1])=={
                    'passed':True,'assertions':1241,'prefix_frames':512,
                    'recorded_tail_frames':245,'unavailable_frames':105,
                    'skipped':0,'actual_gameenv':True,'recovered_frames':62,
                    'opponent_restart_wait_frames':62},
                'Current handfeel archived replay did not complete')
    return {'manual_handfeel_manifest_sha256':benchmark.file_hash(path),
            'manual_handfeel_archive_sha256':archive['sha256'],
            'manual_handfeel_unavailable_frames':105,
            'manual_handfeel_recovered_frames':62}

def verify_bot_selection_response():
    """Pin the manual-response replay and retain its handfeel predecessor."""
    historical=verify_bot_selection_handfeel()
    base=ROOT/'.project/optimization/baselines'
    path=base/'bot_selection_response_20261002.json'
    manifest=json.loads(path.read_text())
    contract={'prefix_frames':512,'tail_frames':245,
              'first_changed_frame_vs_prior':123,
              'changed_prefix_hashes_vs_prior':389,
              'first_unavailable_tail_frame':73,'unavailable_frames':105,
              'recovered_frames':66,'opponent_restart_wait_frames':66}
    prior=base/'bot_selection_handfeel_20261002.json'
    require(manifest['format']==1 and
            manifest['id']=='bot-selection-manual-response-20261002' and
            manifest['historical_reference']==str(prior.relative_to(ROOT)) and
            manifest['historical_reference_sha256']==benchmark.file_hash(prior) and
            manifest['contract']==contract and
            manifest['raw_oracles']['independent_runs']==2,
            'Manual-response reference contract changed')
    snapshot=manifest['historical_physics_snapshot']
    snapshot_path=(ROOT/snapshot['path']).resolve()
    require(snapshot_path.is_relative_to(ROOT) and
            benchmark.file_hash(snapshot_path)==snapshot['sha256'] and
            hashlib.sha256(gzip.decompress(snapshot_path.read_bytes())).hexdigest()==
            snapshot['decompressed_sha256']==
            '71cbf13098097fcbbceb1270d23d9eb636a16eafc31916827a962ccabb05f7ae',
            'Pre-response physics source snapshot changed')
    expected_sources={
        'engine/src/onthepitch/player/controller/playercontroller.cpp',
        'engine/src/onthepitch/player/humanoid/humanoid.cpp',
        'engine/src/onthepitch/player/humanoid/humanoidbase.cpp'}
    require(set(manifest['candidate_sources'])==expected_sources,
            'Manual-response source scope changed')
    for relative,expected in manifest['candidate_sources'].items():
        source=(ROOT/relative).resolve()
        require(source.is_relative_to(ROOT) and benchmark.file_hash(source)==expected,
                'Manual-response source changed: '+relative)
    archive=manifest['archive']
    archive_path=(ROOT/archive['path']).resolve()
    require(archive_path.is_relative_to(ROOT) and
            benchmark.file_hash(archive_path)==archive['sha256'],
            'Manual-response oracle archive changed')
    expected_members={'generator.cpp','hashes-run1.inc','hashes-run2.inc',
                      'tail-run1.inc','tail-run2.inc','run1.log','run2.log'}
    with tarfile.open(archive_path,'r:gz') as package:
        recorded=json.load(package.extractfile('manifest.json'))
        require(recorded['format']=='bot-selection-response-oracle-v1' and
                set(recorded['files'])==expected_members and
                set(package.getnames())==expected_members|{'manifest.json'},
                'Manual-response oracle archive members changed')
        raw={name:package.extractfile(name).read() for name in expected_members}
    require(all(hashlib.sha256(data).hexdigest()==recorded['files'][name]
                for name,data in raw.items()) and
            recorded['files']['generator.cpp']==archive['generator_sha256'],
            'Manual-response generator or archive member changed')
    fixture_names={
        kind:f'engine/tests/fixtures/native_bot_transition_{kind}_response_20261002.inc'
        for kind in ('hashes','tail')}
    require(set(manifest['fixtures'])==set(fixture_names.values()),
            'Manual-response fixture scope changed')
    for kind,frames in (('hashes',512),('tail',245)):
        first=raw[f'{kind}-run1.inc']
        require(first==raw[f'{kind}-run2.inc'] and
                hashlib.sha256(first).hexdigest()==manifest['raw_oracles'][f'{kind}_sha256'] and
                len(first.splitlines())==frames,
                'Manual-response independent replays differ')
        relative=fixture_names[kind]
        fixture=(ROOT/relative).resolve()
        require(fixture.is_relative_to(ROOT) and
                benchmark.file_hash(fixture)==manifest['fixtures'][relative] and
                fixture.read_bytes().partition(b'\n')[2]==first,
                'Manual-response fixture differs from recorded replay: '+kind)
    previous=(ROOT/'engine/tests/fixtures/native_bot_transition_hashes_handfeel_20261002.inc').read_text().splitlines()[1:]
    current=raw['hashes-run1.inc'].decode().splitlines()
    changed=[i for i,(a,b) in enumerate(zip(previous,current)) if a!=b]
    require(len(previous)==len(current)==512 and changed[0]==123 and
            len(changed)==389 and changed==list(range(123,512)),
            'Manual-response semantic divergence changed')
    def fields(line):
        return line.strip().rstrip(',').strip('{}').split(',')
    prior_tail=(ROOT/'engine/tests/fixtures/native_bot_transition_tail_handfeel_20261002.inc').read_text().splitlines()[1:]
    current_tail=raw['tail-run1.inc'].decode().splitlines()
    selected=[int(fields(line)[3]) for line in current_tail]
    require(len(prior_tail)==len(current_tail)==245 and
            all(fields(a)[:3]==fields(b)[:3]
                for a,b in zip(prior_tail,current_tail)) and
            selected[:73]==[8]*73 and selected[73:178]==[-1]*105 and
            selected[178:]==[9]*67,
            'Manual-response fixed inputs or selection transition changed')
    for run in (1,2):
        log=raw[f'run{run}.log'].decode()
        require(log.startswith('exit=0\n') and
                json.loads(log.split('\n',1)[1])=={
                    'passed':True,'assertions':1249,'prefix_frames':512,
                    'recorded_tail_frames':245,'unavailable_frames':105,
                    'skipped':0,'actual_gameenv':True,'recovered_frames':66,
                    'opponent_restart_wait_frames':66},
                'Manual-response archived replay did not complete')
    return {**historical,
            'manual_response_manifest_sha256':benchmark.file_hash(path),
            'manual_response_archive_sha256':archive['sha256'],
            'manual_response_unavailable_frames':105,
            'manual_response_recovered_frames':66}

def verify_bot_selection_ai_mirror():
    """Validate the current replay and retain the earlier semantic lineage."""
    historical=verify_bot_selection_response()
    base=ROOT/'.project/optimization/baselines'
    path=base/'bot_selection_ai_mirror_20261004.json'
    manifest=json.loads(path.read_text())
    prior=base/'bot_selection_response_20261002.json'
    expected_contract={
        'prefix_frames':512,'tail_frames':1566,'historical_input_frames':245,
        'first_changed_frame_vs_prior':100,
        'changed_prefix_hashes_vs_prior':412,
        'first_unavailable_tail_frame':1394,'unavailable_frames':105,
        'recovered_frames':66,'opponent_restart_wait_frames':66,
        'assertions':3892}
    require(manifest['format']==1 and
            manifest['id']=='bot-selection-ai-mirror-20261004' and
            manifest['historical_reference']==str(prior.relative_to(ROOT)) and
            manifest['historical_reference_sha256']==benchmark.file_hash(prior) and
            manifest['contract']==expected_contract and
            manifest['raw_oracles']['independent_runs']==2,
            'AI mirror bot-selection reference contract changed')
    expected_sources={
        'engine/src/ai/ai_tactics.cpp',
        'engine/src/ai/ai_tactics.hpp',
        'engine/src/frame_sync/bot_takeover.hpp',
        'engine/src/frame_sync/engine_bot_observer.hpp',
        'engine/src/onthepitch/team.cpp'}
    require(set(manifest['candidate_sources'])==expected_sources,
            'AI mirror source scope changed')
    for relative,expected in manifest['candidate_sources'].items():
        source=(ROOT/relative).resolve()
        require(source.is_relative_to(ROOT) and
                benchmark.file_hash(source)==expected,
                'AI mirror source changed: '+relative)
    archive=manifest['archive']
    archive_path=(ROOT/archive['path']).resolve()
    require(archive_path.is_relative_to(ROOT) and
            benchmark.file_hash(archive_path)==archive['sha256'],
            'AI mirror oracle archive changed')
    expected_members={'generator.cpp','hashes-run1.inc','hashes-run2.inc',
                      'tail-run1.inc','tail-run2.inc','run1.log','run2.log'}
    with tarfile.open(archive_path,'r:gz') as package:
        recorded=json.load(package.extractfile('manifest.json'))
        require(recorded['format']=='bot-selection-ai-mirror-oracle-v1' and
                set(recorded['files'])==expected_members and
                set(package.getnames())==expected_members|{'manifest.json'},
                'AI mirror oracle archive members changed')
        raw={name:package.extractfile(name).read() for name in expected_members}
    require(all(hashlib.sha256(data).hexdigest()==recorded['files'][name]
                for name,data in raw.items()) and
            recorded['files']['generator.cpp']==archive['generator_sha256']==
            benchmark.file_hash(ROOT/'engine/tests/engine_native_bot_selection_contract.cpp'),
            'AI mirror generator or archive member changed')
    for kind,frames in (('hashes',512),('tail',1566)):
        first=raw[f'{kind}-run1.inc']
        require(first==raw[f'{kind}-run2.inc'] and
                hashlib.sha256(first).hexdigest()==
                manifest['raw_oracles'][f'{kind}_sha256'] and
                len(first.splitlines())==frames,
                'AI mirror independent replays differ')
        relative=f'engine/tests/fixtures/native_bot_transition_{kind}_ai_mirror_20261004.inc'
        fixture=(ROOT/relative).resolve()
        require(set(manifest['fixtures'])=={
                    f'engine/tests/fixtures/native_bot_transition_{k}_ai_mirror_20261004.inc'
                    for k in ('hashes','tail')} and
                fixture.is_relative_to(ROOT) and
                benchmark.file_hash(fixture)==manifest['fixtures'][relative] and
                fixture.read_bytes().partition(b'\n')[2]==first,
                'AI mirror fixture differs from archived replay: '+kind)
    previous=(ROOT/'engine/tests/fixtures/native_bot_transition_hashes_response_20261002.inc').read_text().splitlines()[1:]
    current=raw['hashes-run1.inc'].decode().splitlines()
    changed=[i for i,(a,b) in enumerate(zip(previous,current)) if a!=b]
    require(len(previous)==len(current)==512 and
            changed==list(range(100,512)),
            'AI mirror prefix divergence changed')
    def fields(line):
        return line.strip().rstrip(',').strip('{}').split(',')
    prior_tail=(ROOT/'engine/tests/fixtures/native_bot_transition_tail_response_20261002.inc').read_text().splitlines()[1:]
    current_tail=raw['tail-run1.inc'].decode().splitlines()
    selected=[int(fields(line)[3]) for line in current_tail]
    require(len(prior_tail)==245 and len(current_tail)==1566 and
            all(fields(a)[:3]==fields(b)[:3]
                for a,b in zip(prior_tail,current_tail[:245])) and
            selected[1394:1499]==[-1]*105 and
            selected[1499:]==[9]*67 and
            all(actor>=0 for actor in selected[:1394]),
            'AI mirror fixed inputs or real selection transition changed')
    expected_report={'passed':True,'assertions':3892,'prefix_frames':512,
                     'recorded_tail_frames':1566,'unavailable_frames':105,
                     'skipped':0,'actual_gameenv':True,'recovered_frames':66,
                     'opponent_restart_wait_frames':66}
    for run in (1,2):
        log=raw[f'run{run}.log'].decode()
        require(log.startswith('exit=0\n') and
                json.loads(log.split('\n',1)[1])==expected_report,
                'AI mirror archived replay did not complete')
    return {**historical,
            'ai_mirror_manifest_sha256':benchmark.file_hash(path),
            'ai_mirror_archive_sha256':archive['sha256'],
            'ai_mirror_unavailable_frames':105,
            'ai_mirror_recovered_frames':66}

def observation():
    socket=Path('/tmp/.X11-unix')
    return dict(namespace=os.readlink('/proc/self/ns/mnt'),
                socket_mode=oct(socket.stat().st_mode&0o7777) if socket.exists() else None,
                xkbcomp_exists=Path('/usr/bin/xkbcomp').exists())

def tactical_coverage(raw, summary):
    """Verify per-scenario actor/set-piece coverage and its aggregate report."""
    cases=[json.loads(line) for line in raw.splitlines() if line.startswith('{"seed":')]
    require(len(cases)==4 and
            {(case.get('seed'),case.get('physics')) for case in cases}==
            {(42,2),(42,10),(43,2),(43,10)},
            'Incomplete tactical scenario matrix')
    require(all(case.get('actual_frames')==240 and
                type(case.get('nonzero_actors')) is int and
                case['nonzero_actors']>=720 and
                type(case.get('restarts')) is int and
                (case['restarts']>0 if case['physics']==10 else case['restarts']>=0)
                for case in cases),
            'Insufficient tactical actor or set-piece coverage')
    require(summary.get('frames')==960 and
            sum(case['nonzero_actors'] for case in cases)==summary.get('nonzero_actors') and
            sum(case['restarts'] for case in cases)==summary.get('restarts'),
            'Tactical scenario totals disagree')
    return (summary['assertions'],
            tuple((case['seed'],case['physics'],case['nonzero_actors'],case['restarts'])
                  for case in cases))


def require_tactical_parity(release, sanitized):
    require(release==sanitized, 'Release/Sanitizer tactical scenarios differ')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=Path('/tmp/football-optimization-native'))
    parser.add_argument('--sanitized-build',type=Path,default=Path('/tmp/football-optimization-sanitized'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--x11-root',type=Path,default=Path(os.environ.get('FOOTBALL_TEST_X11_ROOT',
                        str(Path.home()/'.cache/football-input-x11-20260913-a/root-relocated'))))
    args=parser.parse_args()
    require(platform.system()=='Linux' and sys.flags.optimize==0,'Run this gate with assertions enabled on Linux')
    output=(args.output or ROOT/'.project/optimization/benchmarks'/f'input-contract-{time.time_ns()}').resolve()
    require(output.is_relative_to(ROOT) and not output.exists(),'Use a new workspace evidence directory')
    output.mkdir(parents=True)
    sources=benchmark.source_manifest()
    for path in (ROOT/'engine/tests').glob('engine_native_*'):
        sources[path.relative_to(ROOT).as_posix()]=benchmark.file_hash(path)
    for path in [*(ROOT/'.project/optimization/baselines').glob('bot_selection_v2*'),
                 ROOT/'.project/reports/optimization-bot-selection-semantic-reference-2026-10-01.md']:
        sources[path.relative_to(ROOT).as_posix()]=benchmark.file_hash(path)
    bot_reference=verify_bot_selection_reference()
    fixture=ROOT/'engine/tests/fixtures/frame_simulation_before_input_20260913.inc'
    require(benchmark.file_hash(fixture)=='78adff3d69ab0d8a133a545495aeeec0a04d9a8194ee90e80b6f36b929d1f590',
            'Frozen pre-provider algorithm changed')
    tools=args.x11_root.resolve()
    for name in ('usr/bin/Xvfb','usr/bin/xkbcomp','usr/include/X11/extensions/XTest.h','usr/lib/libXtst.so'):
        require((tools/name).is_file(),'Missing X11 input test dependency: '+str(tools/name))
    dependencies={str(p):benchmark.file_hash(p) for p in sorted(tools.rglob('*')) if p.is_file()}
    environment=dict(os.environ,FOOTBALL_TEST_X11_ROOT=str(tools),PYTHONOPTIMIZE='0',
                     GFOOTBALL_DATA_DIR=str(ROOT/'engine/data'),LIBGL_ALWAYS_SOFTWARE='1')
    for key in ('LD_PRELOAD','DISPLAY','SDL_VIDEODRIVER','LD_LIBRARY_PATH','GFOOTBALL_FONT'):
        environment.pop(key,None)
    before=observation();commands=[];results={};binaries={}
    runner.write_json(output/'sources.json',sources)
    runner.write_json(output/'dependencies.json',dependencies)
    runner.write_json(output/'parent-before.json',before)
    previous=signal.signal(signal.SIGTERM,runner.interrupt_command)
    try:
        def run(argv,label,env=environment,timeout=600):
            return runner.run_command(argv,label,output=output,commands=commands,
                                      environment=env,timeout=timeout)
        def parsed(raw,minimum,expected):
            rows=[json.loads(line) for line in raw.splitlines() if line.startswith('{"passed"')]
            require(len(rows)==1,'Missing or ambiguous native input report')
            row=rows[0]
            require(row.get('passed') is True and row.get('skipped')==0 and
                    row.get('assertions',0)>=minimum,'Incomplete input cohort')
            require(all(row.get(key)==value for key,value in expected.items()),'Input coverage fields differ')
            require(not any(word in raw for word in ('runtime error:','ERROR: AddressSanitizer',
                                                    'ERROR: LeakSanitizer')),'Input detector diagnostic')
            return row
        results['python']=parsed(run([sys.executable,ROOT/'.project/checks/python_input_probe.py'],
                                     'python-input'),9,{})
        run([sys.executable,ROOT/'.project/checks/native_input_oracle.py',output/'oracle.txt'],'python-oracle')
        oracle=json.loads((output/'oracle.json').read_text())
        require(oracle['operations']==20168,'Python/native input cohort changed')
        tactical_reference=None
        builds={'release':args.build.resolve(),'sanitized':args.sanitized_build.resolve()}
        require(builds['release']!=builds['sanitized'],'Release and sanitizer builds must be distinct')
        runtimes={}
        for label,build in builds.items():
            sanitized=label=='sanitized'
            run(['cmake','-S',ROOT/'engine','-B',build,
                 '-DCMAKE_BUILD_TYPE='+('Debug' if sanitized else 'Release'),
                 '-DBUILD_PYTHON_BINDINGS=OFF','-DFOOTBALL_ENABLE_SANITIZERS='+('ON' if sanitized else 'OFF'),
                 '-DFOOTBALL_TEST_X11_ROOT='+str(tools),'-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY='+str(build/'bin')],
                label+'-configure',timeout=1800)
            # 2026-09-14: product executables were previously built only in Release.
            # targets=[*CONTRACTS,'engine_native_clock_replay_contract','engine_native_sdl_input_contract']
            # if not sanitized:
            #     targets+=['engine_native_window_trace','standalone_game','football_client_tcp',
            #               'football_client','football_server_tcp','football_server']
            targets=[*CONTRACTS,'engine_native_clock_replay_contract','engine_native_sdl_input_contract',*TARGETS]
            if not sanitized:
                targets+=['engine_native_window_trace']
            run(['cmake','--build',build,'-j','1','--target',*targets],label+'-build',timeout=3600)
            compile_rows=json.loads((build/'compile_commands.json').read_text())
            for target in [*CONTRACTS,'engine_native_clock_replay_contract','engine_native_sdl_input_contract']:
                rows=[r for r in compile_rows if r['file'].endswith('/tests/'+target+'.cpp')]
                require(len(rows)==1 and '-std=c++23' in rows[0]['command'],'Missing canonical compile recipe')
                flags=rows[0]['command']
                require(('-fsanitize=address,undefined' in flags)==sanitized,'Wrong native input instrumentation')
                if sanitized:require('-fno-sanitize-recover=all' in flags,'Recovering sanitizer build')
                else:require('-O3' in flags and '-DNDEBUG' in flags,'Wrong Release optimization')
                binaries[str(build/'bin'/target)]=benchmark.file_hash(build/'bin'/target)
            # 2026-09-14: keep identities for every product actually built, in both modes.
            for name in TARGETS:
                binary=build/'bin'/name;binaries[str(binary)]=benchmark.file_hash(binary)
            core=build/'libfootball_engine.so';binaries[str(core)]=benchmark.file_hash(core)
            runtime=dict(environment,LD_LIBRARY_PATH=str(build)+':'+str(tools/'usr/lib'))
            if sanitized:
                runtime.update(ASAN_OPTIONS='halt_on_error=1:detect_leaks=1:quarantine_size_mb=16',
                               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1',LSAN_OPTIONS='exitcode=23')
                symbols=run(['nm','-D',core],label+'-core-symbols',runtime)
                require('__asan_' in symbols and '__ubsan_' in symbols,'Actual engine lacks detector instrumentation')
            runtimes[label]=runtime
            for target,(minimum,expected) in CONTRACTS.items():
                binary=build/'bin'/target
                link=run(['ldd',binary],label+'-'+target+'-linkage',runtime)
                require('not found' not in link,'Unresolved native input library')
                if sanitized:require('libasan' in link and 'libubsan' in link,'Missing detector runtime')
                # 2026-09-13: real capture contract archives independently read GL pixels.
                # argv=[binary]+([output/'oracle.txt'] if target=='engine_native_input_buffer_contract' else [])
                arguments = ([output/'oracle.txt'] if target=='engine_native_input_buffer_contract'
                             else [output/(label+'-capture-images')] if target=='engine_frame_capture_contract'
                             else [])
                argv=[binary]+arguments
                raw=run(argv,label+'-'+target,runtime)
                row=parsed(raw,minimum,expected)
                if target=='engine_ai_tactical_state_contract':
                    coverage=tactical_coverage(raw,row)
                    if sanitized:
                        require_tactical_parity(tactical_reference, coverage)
                    else:
                        tactical_reference=coverage
                    row['scenario_coverage']=coverage[1]
                results[label+'-'+target]=row
        # 2026-09-13: thread instrumentation is separate from the ASan/UBSan engine.
        # This contract exercises publication and sampled input, not the whole engine.
        compiler=shlex.split(next(r['command'] for r in compile_rows
                  if r['file'].endswith('/tests/engine_native_transport_pump_contract.cpp')))[0]
        thread_binary=output/'native-transport-pump-tsan'
        run([compiler,'-std=c++23','-g','-O1','-fno-omit-frame-pointer','-fsanitize=thread','-pthread',
             '-I'+str(ROOT/'engine/src'),'-I'+str(ROOT/'engine/src/cmake'),'-I/usr/include/SDL2',
             ROOT/'engine/tests/engine_native_transport_pump_contract.cpp','-o',thread_binary],
            'thread-pump-build')
        thread_runtime=dict(environment,TSAN_OPTIONS='halt_on_error=1')
        link=run(['ldd',thread_binary],'thread-pump-linkage',thread_runtime)
        require('libtsan' in link and 'not found' not in link,'Missing thread detector runtime')
        binaries[str(thread_binary)]=benchmark.file_hash(thread_binary)
        results['thread-pump']=parsed(run([thread_binary],'thread-pump',thread_runtime),
            20333,{'ledger_frames':4000,'concurrent_frames':128,'joined_lifetimes':64})
        # 2026-09-13: validate the new UI/worker and input handoff with a race detector too.
        owner_binary=output/'native-ui-owner-tsan'
        run([compiler,'-std=c++23','-g','-O1','-fno-omit-frame-pointer','-fsanitize=thread','-pthread',
             '-I'+str(ROOT/'engine/src'),'-I'+str(ROOT/'engine/src/cmake'),'-I/usr/include/SDL2',
             ROOT/'engine/tests/engine_native_ui_owner_contract.cpp','-o',owner_binary],'thread-owner-build')
        owner_link=run(['ldd',owner_binary],'thread-owner-linkage',thread_runtime)
        require('libtsan' in owner_link and 'not found' not in owner_link,'Missing UI owner detector runtime')
        binaries[str(owner_binary)]=benchmark.file_hash(owner_binary)
        results['thread-owner']=parsed(run([owner_binary],'thread-owner',thread_runtime),20000,
            {'joined_lifetimes':64,'handoff_frames':256,'concurrent_observations':20000})
        # 2026-09-13: timed publication uses the existing ledger lock across both callers.
        publication_binary=output/'native-publication-clock-tsan'
        run([compiler,'-std=c++23','-g','-O1','-fno-omit-frame-pointer','-fsanitize=thread','-pthread',
             '-I'+str(ROOT/'engine/src'),'-I'+str(ROOT/'engine/src/cmake'),'-I/usr/include/SDL2',
             ROOT/'engine/tests/engine_native_publication_clock_contract.cpp','-o',publication_binary],
            'thread-publication-build')
        publication_link=run(['ldd',publication_binary],'thread-publication-linkage',thread_runtime)
        require('libtsan' in publication_link and 'not found' not in publication_link,'Missing publication detector runtime')
        binaries[str(publication_binary)]=benchmark.file_hash(publication_binary)
        # 2026-09-13: share the same required clock coverage across detector builds.
#         results['thread-publication']=parsed(run([publication_binary],'thread-publication',thread_runtime),30559,
#             {'cadence_frames':6000,'concurrent_frames':512,'edge_frames':6})
        results['thread-publication']=parsed(run([publication_binary],'thread-publication',thread_runtime),
            *CONTRACTS['engine_native_publication_clock_contract'])
        release=builds['release']
        for target in ('standalone_game','football_client_tcp','football_client','football_server_tcp','football_server'):
            binaries[str(release/'bin'/target)]=benchmark.file_hash(release/'bin'/target)
        trace=release/'input-tests/libengine_native_window_trace.so'
        binaries[str(trace)]=benchmark.file_hash(trace)
        run(['unshare','--mount','--propagation','private',sys.executable,
             ROOT/'.project/checks/native_input_x11.py','--parent-mount-namespace',before['namespace'],
             '--output',output/'x11','--build',release,'--library',trace,
             '--sampler',release/'bin/engine_native_sdl_input_contract',
             '--sanitized-sampler',builds['sanitized']/'bin/engine_native_sdl_input_contract',
        # 2026-09-13: cover three bounded in-play waits plus focus/pause cases and X11 cleanup.
        #              '--sanitized-build',builds['sanitized']],'actual-input-windows',timeout=360)
             '--sanitized-build',builds['sanitized']],'actual-input-windows',timeout=600)
        windows=json.loads((output/'x11/report.json').read_text())
        require(windows['probe_passed'] and windows['server_reaped'] and
                windows['private_mount_namespace']!=windows['parent_mount_namespace'],'Incomplete private window run')
        cases=windows['probe_result']['cases']
        require(len(cases)==3 and {row['kind'] for row in cases}=={'standalone','tcp','udp'} and
                all(row['passed'] and row['actual_product_main'] and row['actual_xtest'] for row in cases),
                'Missing actual main input coverage')
        # 2026-09-13: successful startup alone does not establish continuous product input.
        require(all(row['measurements']['actual_in_play'] for row in cases),'Missing in-play observation')
        require(all(row['measurements']['continuous_held_authority_verified'] and
                    row['measurements']['held_authority_neutral']==0
                    for row in cases if row['kind']!='standalone'),'Held authority has input gaps')
        expected_frames=sum(row['authority']['frames'] for row in cases if row.get('authority'))
        for label,build in builds.items():
            target='engine_native_clock_replay_contract'
            results[label+'-clock-replay']=parsed(run([build/'bin'/target,output/'x11/windows'],
                    label+'-clock-replay',runtimes[label]),400000,
                    {'clock_events':40000,'replay_frames':expected_frames,'actual_gameenv':True})
        for key,value in windows['sampler_results'].items():results[key+'-sdl']=value
        require(set(windows['sampler_results'])=={'release','sanitized'},'Missing instrumented device sampler')
        require(observation()==before,'Input gate changed parent X11 environment')
        runner.write_json(output/'parent-after.json',observation())
        for path,expected in sources.items():require(benchmark.file_hash(ROOT/path)==expected,'Input source changed during gate')
        for path,expected in dependencies.items():require(benchmark.file_hash(path)==expected,'X11 dependency changed during gate')
        for path,expected in binaries.items():require(benchmark.file_hash(path)==expected,'Input binary changed during gate')
        artifacts={p.relative_to(output).as_posix():dict(bytes=p.stat().st_size,sha256=benchmark.file_hash(p))
                   for p in output.rglob('*') if p.is_file()}
        assertions=sum(row['assertions'] for row in results.values())
        report=dict(passed=True,skipped=0,assertions=assertions,sources=sources,binaries=binaries,
                    bot_selection_reference=bot_reference,
                    dependencies=dependencies,artifacts=artifacts,results=results,windows=windows,
                    actual_gameenv=True,actual_x11=True,actual_xtest=True,actual_native_mains=True,
                    latency_acceptance=False,scope='Current shared Python/native input, real device sampler, '
                    'authority/replay and presentation ownership regression; no product latency acceptance')
        runner.write_json(output/'report.json',report)
        print(json.dumps(dict(passed=True,skipped=0,assertions=assertions,artifact=str(output/'report.json'),
                              artifact_sha256=benchmark.file_hash(output/'report.json'))),flush=True)
        return 0
    except BaseException as error:
        runner.write_json(output/'failure.json',dict(error_type=type(error).__name__,error=str(error)))
        raise
    finally:
        runner.write_json(output/'parent-after.json',observation())
        signal.signal(signal.SIGTERM,previous)
if __name__=='__main__':raise SystemExit(main())
