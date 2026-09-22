
from pathlib import Path
import argparse,os,socket,struct,subprocess,time,re,json,sys
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/".project/checks"))
import native_product_protocol_probe as wire
assertions=0
def require(value,reason):
 global assertions
 assertions+=1
 if not value:raise RuntimeError(reason)
def case(binary,label,kind,env,root):
 output=root/(label+"-"+kind);output.mkdir();client=None;result={"passed":False,"kind":kind,"build":label}
 try:
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
   peer.bind(("127.0.0.1",0));peer.settimeout(.01)
   with (output/"client.log").open("w") as log:
    client=subprocess.Popen([str(binary),"127.0.0.1",str(peer.getsockname()[1]),"1","2","42","--headless","--frames","3"],cwd=output,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
   # 2026-09-14: the old 15s total included real asset loading before Ready.
   # address=None;sequence=0;ready=False;parts=[];due=0;step=0;until=time.monotonic()+15
   address=None;sequence=0;ready=False;parts=[];due=0;step=0
   started=time.monotonic();until=started+40;ready_at=None;first_control_at=None
   def send(payload):
    nonlocal sequence
    peer.sendto(struct.pack("<BIH",0,sequence,len(payload))+payload,address);sequence+=1
   def auth(frame):return struct.pack("<BIH",3,frame,3)+bytes(30)
   while client.poll() is None and time.monotonic()<until:
    try:data,source=peer.recvfrom(4096)
    except socket.timeout:data=None
    if data is not None:
     if address is None:
      require(data==wire.HELLO,"Actual client did not send native hello");address=source
      session=bytes([66])+wire.HELLO[1:]+struct.pack("<IBBII",42,1,2,1,15000)
      send(session);send(struct.pack("<BHH",7,1,0));continue
     require(source==address,"Unexpected peer")
     if len(data)==5 and data[0]==255:continue
     require(len(data)>=7 and data[0]==0,"Malformed actual client reliable data")
     _,seq,length=struct.unpack_from("<BIH",data);require(length==len(data)-7,"Invalid client length")
     peer.sendto(struct.pack("<BI",255,seq),address)
     if data[7]==65 and not ready:
      ready=True;ready_at=time.monotonic();until=ready_at+15;send(auth(0))
      control=struct.pack("<BHI",10,3 if kind=="invalid_slot" else 1,2 if kind=="invalid_frame" else 1)
      control+=struct.pack("<BHI",11,1,1)
      parts=[control[:3],control[3:10],control[10:]];due=time.monotonic()+.075
    if ready and step<len(parts) and time.monotonic()>=due:
     if first_control_at is None:first_control_at=time.monotonic()
     send(parts[step]);step+=1;due=time.monotonic()+.075
     if step==len(parts):send(auth(1));send(auth(2))
   result.update(ready=ready,bootstrap_ms=None if ready_at is None else (ready_at-started)*1000,
                 control_ms=None if ready_at is None else (time.monotonic()-ready_at)*1000,
                 first_control_ms=None if first_control_at is None else (first_control_at-ready_at)*1000,
                 bootstrap_budget_seconds=40,control_budget_seconds=15)
   require(client.poll() is not None,"Control parser stalled after Ready" if ready else "Native client bootstrap timed out before Ready")
  text=(output/"client.log").read_text()
  row=re.search(r"UDP session confirmed=(\d+) verified_hashes=(\d+) failed=(\d+)",text)
  require(row is not None,"Missing real client final state");confirmed,hashes,failed=map(int,row.groups())
  require(not any(s in text for s in ["AddressSanitizer","LeakSanitizer","runtime error:"]),"Client sanitizer diagnostic")
  if kind=="fragmented":require(client.returncode==0 and failed==0 and confirmed==3 and step==3,"Fragmented notices consumed authority incorrectly")
  else:require(client.returncode==1 and failed==1,"Malformed bot control was accepted")
  result.update(passed=True,confirmed=confirmed,client_exit=client.returncode,failed=failed,parts_sent=step,actual_native_client=True)
 finally:
  if client and client.poll() is None:client.terminate();client.wait(timeout=5)
  (output/"report.json").write_text(json.dumps(result,indent=2)+"\n")
 return result
def main():
 p=argparse.ArgumentParser();p.add_argument("--build",type=Path,required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
 args.output.mkdir(parents=True);results=[];exit_code=0
 build=args.build.resolve();root=args.output.resolve()
 try:
  env=dict(os.environ,LD_LIBRARY_PATH=str(build),GFOOTBALL_DATA_DIR=str(R/"engine/data"),
           ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",LSAN_OPTIONS="exitcode=23")
  for key in ["DISPLAY","LD_PRELOAD","SDL_VIDEODRIVER","GFOOTBALL_FONT"]:env.pop(key,None)
  for kind in ["fragmented","invalid_slot","invalid_frame"]:
   row=case(build/"bin/football_client","native",kind,env,root);results.append(row);print(json.dumps(row),flush=True)
 except BaseException:
  import traceback;traceback.print_exc();exit_code=1
 report=dict(passed=exit_code==0,assertions=assertions,skipped=0,cases=results,product_acceptance=False)
 (root/"report.json").write_text(json.dumps(report,indent=2)+"\n")
 print(json.dumps(report),flush=True)
 return exit_code
if __name__=="__main__":raise SystemExit(main())
