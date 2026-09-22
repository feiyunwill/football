#!/usr/bin/env python3
"""Formal shared input acceptance: current Python, native engine and real SDL/XTEST.
No old stage receipt substitutes for execution. No device latency acceptance.
"""
from pathlib import Path
import argparse,json,os,platform,signal,sys,time,shlex
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
 'engine_ai_tactical_state_contract':(27618,{'frames':960,'actual_gameenv':True,'nonzero_actors':3513,'restarts':331}),
 # 2026-09-14: native controls must retain moving touches and stationary ball handling.
 'engine_ai_touch_contract':(586,{'seeds':3,'ball_control_assets':270,'quiet_idle':24,'actual_gameenv':True}),
 # 2026-09-13: native display-only capture keeps default RGB and logical state.
 'engine_frame_capture_contract':(150,{'engine_frames':161,'images':5,'uncaptured_renders':5,'rejections':16,'headless_policy':True,'solid_colours':3,'odd_width':321,'actual_gameenv':True}),
 # 2026-09-13: slow authority lead and real unavailable-player AI recovery are mandatory.
 #     'engine_native_publication_clock_contract':(30559,{'cadence_frames':6000,'concurrent_frames':512,'edge_frames':6}),
 'engine_native_publication_clock_contract':(30559,{'cadence_frames':6000,'concurrent_frames':512,'edge_frames':6,'resync_frames':572,'resync_max_lead':2}),
 'engine_native_bot_selection_contract':(1262,{'prefix_frames':512,'recorded_tail_frames':57,'unavailable_frames':30,'recovered_frames':1,'actual_gameenv':True}),
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
def observation():
    socket=Path('/tmp/.X11-unix')
    return dict(namespace=os.readlink('/proc/self/ns/mnt'),
                socket_mode=oct(socket.stat().st_mode&0o7777) if socket.exists() else None,
                xkbcomp_exists=Path('/usr/bin/xkbcomp').exists())

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
                results[label+'-'+target]=parsed(run(argv,label+'-'+target,runtime),minimum,expected)
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
