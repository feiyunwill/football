
from pathlib import Path
import argparse,os,socket,struct,subprocess,time,re,json,sys
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import native_product_protocol_probe as wire
from native_product_udp_fixture import Fixture,packet
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
   fixture=Fixture(peer);ready=False;parts=[];due=0;step=0
   session_sent=False;receipt=False;loaded=False
   grant=os.urandom(16)+struct.pack("<H",0)+os.urandom(32)+struct.pack("<Q",1)
   descriptor=bytes([66])+wire.HELLO[1:]+struct.pack("<IBBII",42,1,2,1,15000)
   started=time.monotonic();until=started+40;ready_at=None;first_control_at=None
   def send(payload):fixture.send(payload)
   def auth(frame):return struct.pack("<BIH",3,frame,3)+bytes(30)
   while client.poll() is None and time.monotonic()<until:
    fixture.retransmit()
    try:data,source=peer.recvfrom(4096)
    except socket.timeout:data=None
    for record in fixture.receive(data,source) if data is not None else []:
     tag=record[0]
     if tag==88:
      require(not session_sent and record[10:28]==wire.HELLO and
              (len(record)==28 or record[28:]==struct.pack("<I",1)),"Invalid actual loading hello")
      session_sent=True;send(packet(81,descriptor+grant+b"\x02"+struct.pack("<I",1)))
     elif tag in (89,90):
      require(session_sent and record[10:]==grant,"Loading proof mismatch")
      if tag==90:require(not receipt,"Duplicate loading receipt");receipt=True
      else:require(receipt and not loaded,"Loading completion order");loaded=True
     elif tag==85:
      require(loaded and not ready and record[10:68]==grant and
              struct.unpack_from("<I",record,68)[0]==0,"Invalid actual Ready")
      ready=True;ready_at=time.monotonic();until=ready_at+15
      send(packet(86,struct.pack("<QI",1,0)));send(auth(0))
      control=struct.pack("<BHI",10,3 if kind=="invalid_slot" else 1,2 if kind=="invalid_frame" else 1)
      control+=struct.pack("<BHI",11,1,1)
      parts=[control[:3],control[3:10],control[10:]];fixture.begin_fragments();due=time.monotonic()+.075
     elif tag==8:fixture.send_heartbeat(record)
     else:require(tag==2 and ready,"Input escaped Ready barrier")
    if ready and step<len(parts) and time.monotonic()>=due:
     if first_control_at is None:first_control_at=time.monotonic()
     send(parts[step]);step+=1;due=time.monotonic()+.075
     if step==len(parts):fixture.end_fragments();send(auth(1));send(auth(2))
   result.update(ready=ready,loading_receipt=receipt,loading_complete=loaded,current_udp_transport=fixture.established,bootstrap_ms=None if ready_at is None else (ready_at-started)*1000,
                 control_ms=None if ready_at is None else (time.monotonic()-ready_at)*1000,
                 first_control_ms=None if first_control_at is None else (first_control_at-ready_at)*1000,
                 bootstrap_budget_seconds=40,control_budget_seconds=15)
   require(receipt and loaded and ready,"Current native loading barrier was not exercised")
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
