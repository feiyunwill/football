from pathlib import Path
import argparse,json,os,re,subprocess,time
import native_product_protocol_probe as wire
ROOT=Path(__file__).resolve().parents[2]
def pair(build,candidate,target,output):
 output.mkdir();servers=[];clients=[];ports=[];results=[];error=None
 transport="tcp" if target.endswith("_tcp") else "udp"
 client_binary=build/"bin"/("football_client_tcp" if transport=="tcp" else "football_client")
 env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(ROOT/"engine/data"),
          ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:quarantine_size_mb=16",
          UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",LSAN_OPTIONS="exitcode=23")
 for name in ["LD_PRELOAD","DISPLAY","SDL_VIDEODRIVER","GFOOTBALL_FONT"]:env.pop(name,None)
 try:
  for index in range(2):
   directory=output/("server-"+str(index));directory.mkdir()
   with (directory/"server.log").open("w") as log:
    server=subprocess.Popen([str(candidate),"0","1","1",str(42+index)],cwd=directory,env=env,
                            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
   servers.append(server);until=time.monotonic()+30
   while time.monotonic()<until:
    wire.require(server.poll() is None,"Port-zero server exited before binding")
    text=(directory/"server.log").read_text()
    match=re.search(r"Integrated "+transport.upper()+r" server listening on port (\d+)",text)
    if match:
     port=int(match.group(1));wire.require(0<port<=65535,"Server advertised port zero or invalid port")
     wire.require(wire.owned_bound(server,port,transport),"Advertised port is not owned by actual server")
     ports.append(port);break
    time.sleep(.01)
   else:raise RuntimeError("Port-zero startup exceeded original30s budget")
  wire.require(ports[0]!=ports[1] and all(p.poll() is None for p in servers),"Live servers collided or exited")
  for index,port in enumerate(ports):
   directory=output/("client-"+str(index));directory.mkdir()
   with (directory/"client.log").open("w") as log:
    client=subprocess.Popen([str(client_binary),"127.0.0.1",str(port),"--headless","--frames","100"],
                            cwd=directory,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
   clients.append(client);code=client.wait(timeout=45)
   text=(directory/"client.log").read_text()
   match=re.search(transport.upper()+r" session confirmed=(\d+) verified_hashes=(\d+) failed=(\d+)",text)
   wire.require(match is not None,"Missing actual client final telemetry")
   confirmed,hashes,failed=map(int,match.groups())
   wire.require(code==0 and failed==0 and confirmed>=100 and hashes>=10,"Actual client did not finish port-zero match")
   wire.require("seed="+str(42+index) in text,"Client joined wrong advertised session")
   wire.require(not any(w in text for w in ["AddressSanitizer","LeakSanitizer","runtime error:"]),"Client sanitizer diagnostic")
   wire.require((directory/("replay_"+str(42+index)+".bin")).is_file(),"Actual client omitted replay")
   results.append(dict(port=port,seed=42+index,confirmed=confirmed,verified_hashes=hashes,exit_code=code))
 except BaseException as e:error=repr(e)
 finally:
  for p in clients:
   if p.poll() is None:
    p.terminate()
    try:p.wait(timeout=5)
    except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
  exits=[]
  for index,p in enumerate(servers):
   if p.poll() is None:p.terminate()
   try:p.wait(timeout=5)
   except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
   exits.append(p.returncode)
   text=(output/("server-"+str(index))/"server.log").read_text()
   if any(w in text for w in ["AddressSanitizer","LeakSanitizer","runtime error:"]):error="Server sanitizer diagnostic"
  if exits!=[0,0]:error=error or "Server did not exit cleanly"
 report=dict(passed=error is None,transport=transport,target=target,ports=ports,
             simultaneous_servers=len(servers),actual_client_cases=results,server_exits=exits,
             error=error,assertions=wire.ASSERTIONS,skipped=0,product_acceptance=False)
 (output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
 print(json.dumps(report));return 0 if report["passed"] else 1
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--build",type=Path,required=True);p.add_argument("--candidate",type=Path,required=True)
 p.add_argument("--target",required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
 raise SystemExit(pair(a.build,a.candidate,a.target,a.output))
