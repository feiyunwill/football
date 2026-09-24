#!/usr/bin/env python3
"""Verify native automatic session ports with simultaneous servers and actual clients."""
from pathlib import Path
import argparse,json,os,shlex,signal,sys,time
import match_benchmark as benchmark
import performance_regression as runner
from native_boundary import ROOT,require

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build",type=Path,default=Path("/tmp/football-optimization-native"))
    parser.add_argument("--sanitized-build",type=Path,default=Path("/tmp/football-optimization-sanitized"))
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    output=(args.output or ROOT/".project/optimization/benchmarks"/("native-session-ports-"+str(time.time_ns()))).resolve()
    output.mkdir(parents=True,exist_ok=False)
    sources=benchmark.source_manifest()
    runner.write_json(output/"sources.json",sources)
    builds={"release":args.build.resolve(),"sanitized":args.sanitized_build.resolve()}
    require(builds["release"]!=builds["sanitized"],"Build directories must differ")
    servers=("football_server","football_server_tcp","football_server_udp")
    clients=("football_client","football_client_tcp")
    env=dict(os.environ,PYTHONOPTIMIZE="0",PYTHONDONTWRITEBYTECODE="1")
    for key in ("LD_PRELOAD","LD_LIBRARY_PATH","DISPLAY","SDL_VIDEODRIVER","GFOOTBALL_FONT"):
        env.pop(key,None)
    commands=[];results={};binaries={};report=dict(passed=False,skipped=0)
    previous=signal.signal(signal.SIGTERM,runner.interrupt_command)
    def run(argv,label,timeout=180):
        try:
            return runner.run_command(argv,label,output=output,commands=commands,environment=env,timeout=timeout)
        finally:
            runner.write_json(output/"commands.json",commands)
            require(benchmark.source_manifest()==sources,"Source changed during port validation")
    try:
        for mode,build in builds.items():
            sanitized=mode=="sanitized"
            run(["cmake","-S",ROOT/"engine","-B",build,
                 "-DCMAKE_BUILD_TYPE="+("Debug" if sanitized else "Release"),
                 "-DBUILD_PYTHON_BINDINGS=OFF",
                 "-DFOOTBALL_ENABLE_SANITIZERS="+("ON" if sanitized else "OFF"),
                 "-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY="+str(build/"bin")],mode+"-configure",600)
            run(["cmake","--build",build,"-j","1","--target",*servers,*clients],mode+"-build",1800)
            recipes=json.loads((build/"compile_commands.json").read_text())
            require(len(recipes)>=100,"Incomplete engine compilation database")
            for recipe in recipes:
                flags=shlex.split(recipe["command"])
                require("-std=c++23" in flags,"Non-C++23 native compilation")
                if sanitized:
                    require(all(flag in flags for flag in ("-g","-fsanitize=address,undefined",
                            "-fno-sanitize-recover=all","-fno-omit-frame-pointer")),
                            "Incomplete full Debug sanitizer compilation")
                    require(not set(flags).intersection(("-O1","-O2","-O3","-Ofast","-DNDEBUG")),
                            "Optimized or assertion-disabled Debug compilation")
            runner.write_json(output/(mode+"-recipes.json"),recipes)
            for p in [build/"libfootball_engine.so",*(build/"bin"/name for name in (*servers,*clients))]:
                binaries[str(p)]=benchmark.file_hash(p)
            for target in servers:
                name=mode+"-"+target;destination=output/name
                run([sys.executable,ROOT/".project/checks/native_automatic_port_probe.py",
                     "--build",build,"--candidate",build/"bin"/target,"--target",target,
                     "--output",destination],name,180)
                row=json.loads((destination/"report.json").read_text())
                require(row["passed"] and row["skipped"]==0 and row["target"]==target,
                        "Automatic port session failed")
                require(row["simultaneous_servers"]==2 and len(row["ports"])==2 and
                        len(set(row["ports"]))==2 and all(0<p<=65535 for p in row["ports"]) and
                        row["server_exits"]==[0,0],"Incomplete concurrent server port validation")
                cases=row["actual_client_cases"]
                require(len(cases)==2 and all(case["exit_code"]==0 and case["confirmed"]>=100 and
                        case["verified_hashes"]>=10 for case in cases),"Incomplete actual client matches")
                require([case["port"] for case in cases]==row["ports"] and
                        [case["seed"] for case in cases]==[42,43],"Clients joined incorrect sessions")
                results[name]=row
                runner.write_json(output/"results.json",results)
        require(len(results)==6,"Missing product alias or build mode")
        for p,h in binaries.items():
            require(benchmark.file_hash(Path(p))==h,"Native binary changed during port validation")
        report=dict(passed=True,assertions=sum(row["assertions"] for row in results.values()),skipped=0,
                    server_pairs=6,actual_client_cases=12,results=results,binaries=binaries,
                    scope="Automatic port allocation and real loopback clients; menu and recovery require separate gates")
    finally:
        signal.signal(signal.SIGTERM,previous)
        runner.write_json(output/"commands.json",commands)
        runner.write_json(output/"report.json",report)
    print(json.dumps(report),flush=True)
    return 0 if report["passed"] else 1

if __name__=="__main__":
    raise SystemExit(main())
