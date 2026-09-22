
from pathlib import Path
import argparse,json,os,socket,struct,subprocess,sys,time,traceback
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/".project/checks"))
import native_product_protocol_probe as wire

def match(kind,build,output,seed,depart):
 directory=output/f"{kind}-{seed}-{depart}";directory.mkdir(parents=True)
 wire.SESSION=bytes([66])+wire.HELLO[1:]+struct.pack("<IBBII",seed,1,2,1,15000)
 wire.READY=bytes([65])+wire.SESSION[1:]
 peers=[];server=None;frames=[{},{}];hashes=[{},{}];takeovers={};arrivals=[];phase="startup";result={"passed":False,"kind":kind,"seed":seed,"depart":depart}
 try:
  with socket.socket(socket.AF_INET,socket.SOCK_STREAM if kind=="tcp" else socket.SOCK_DGRAM) as reserve:
   reserve.bind(("127.0.0.1",0));port=reserve.getsockname()[1]
  argv=[str(build/("bin/football_server_tcp" if kind=="tcp" else "bin/football_server")),str(port),"1","2",str(seed)]
  if kind=="udp":argv+=["1"]
  with (directory/"server.log").open("w") as log:
   server=subprocess.Popen(argv,cwd=directory,env=os.environ,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
  until=time.monotonic()+30
  while time.monotonic()<until:
   wire.require(server.poll() is None,"Server exited during startup")
   if wire.owned_bound(server,port,kind):break
   time.sleep(.02)
  else:raise RuntimeError("Server bind timeout")
  phase="two player bootstrap"
  for slot in range(2):
   peer=wire.Peer(kind,port);peers.append(peer)
   wire.require(peer.bootstrap()==slot,"Assigned slot differs")
   peer.socket.settimeout(.002)
  def packet(slot,frame):
   return struct.pack("<BIHHffH",2,frame,1,slot,1. if slot==0 else -1.,0.,512)
  for slot,peer in enumerate(peers):peer.send(wire.READY+b"".join(packet(slot,f) for f in range(10)))
  sent=[9,9];latest=[-1,-1];dropped=False;dropped_at=None;heartbeat=time.monotonic();until=time.monotonic()+16
  while time.monotonic()<until:
   for slot,peer in enumerate(peers):
    if dropped and slot==depart:continue
    for row in peer.pump():
     if row[0]==3:
      frame,count=struct.unpack_from("<IH",row,1)
      wire.require(count==3 and frame not in frames[slot],"Repeated or malformed authority")
      frames[slot][frame]=row;latest[slot]=frame
      if slot!=depart:arrivals.append(time.monotonic())
     elif row[0]==4:
      fid,h=struct.unpack_from("<IQ",row,1);hashes[slot][fid]=row
     elif row[0]==10:
      owner,fid=struct.unpack_from("<HI",row,1)
      wire.require(owner==depart and owner not in takeovers,"Foreign or repeated takeover")
      takeovers[owner]=(fid,row)
     else:wire.require(row[0]==8,"Unexpected control record")
    target=latest[slot]+6
    if target>sent[slot]:
     peer.send(b"".join(packet(slot,f) for f in range(sent[slot]+1,target+1)));sent[slot]=target
   if not dropped and min(map(len,frames))>=40:
    phase="real peer loss";dropped=True;dropped_at=time.monotonic()
    if kind=="tcp":peers[depart].close()
    # UDP peer remains bound but stops ACKs/heartbeats, exercising actual reliable expiry.
   if dropped and depart in takeovers and latest[1-depart]>=takeovers[depart][0]+150:break
   if dropped and time.monotonic()-dropped_at>10 and depart not in takeovers:
    raise RuntimeError("Disconnected reserved slot was never taken over")
   if time.monotonic()-heartbeat>=.15:
    heartbeat=time.monotonic()
    for slot,peer in enumerate(peers):
     if not (dropped and slot==depart):peer.send(struct.pack("<BII",8,0,0))
   wire.require(server.poll() is None,"Authority exited during takeover")
  wire.require(dropped and depart in takeovers,"Disconnected reserved slot was never taken over")
  active=1-depart;first=takeovers[depart][0];last=latest[active]
  wire.require(last>=first+150,"Insufficient post-takeover frames")
  phase="frozen authority validation"
  for frame in range(40):
   wire.require(frames[0][frame]==frames[1][frame],"Peers received different human authority")
  nonzero=0;human=0
  for fid,row in sorted(frames[active].items()):
   inputs=[struct.unpack_from("<ffH",row,7+10*slot) for slot in range(3)]
   wire.require(inputs[2]==(0.,0.,0),"Never assigned UDP/TCP slot received AI gameplay")
   if fid<10:
    wire.require(inputs[:2]==[(1.,0.,512),(-1.,0.,512)],"Prequeued human input changed")
   wire.require(inputs[active] in [(0.,0.,0),(1. if active==0 else -1.,0.,512)],"Connected human input rewritten")
   if fid>=first:
    nonzero+=inputs[depart]!=(0.,0.,0);human+=inputs[active]!=(0.,0.,0)
  wire.require(nonzero>=10,"Taken-over actual player never resumed gameplay")
  wire.require(human>=100,"Connected player stopped during takeover")
  wire.require(len(hashes[active])>=15,"Missing actual engine hashes")
  result.update(passed=True,frames=len(frames[active]),takeover_frame=first,post_takeover_frames=last-first+1,bot_nonzero=nonzero,human_nonzero=human,hashes=len(hashes[active]),actual_product_server=True,product_acceptance=False)
 except BaseException as error:
  traceback.print_exc();result.update(error=str(error),phase=phase)
 finally:
  active=1-depart
  payload=bytearray(struct.pack("<4sIBBH",b"FTAC",seed,1,2,1))
  for fid,row in sorted(frames[active].items()):
   for _,(taken,notice) in takeovers.items():
    if taken==fid:payload.extend(notice)
   payload.extend(row)
   if fid in hashes[active]:payload.extend(hashes[active][fid])
  (directory/"authority.bin").write_bytes(payload)
  for peer in peers:peer.close()
  if server:
   if server.poll() is None:server.terminate()
   try:server.wait(timeout=10)
   except subprocess.TimeoutExpired:server.kill();server.wait(timeout=3)
   result["server_exit"]=server.returncode
   if server.returncode!=0:result.update(passed=False,cleanup_error="Server did not exit cleanly")
   text=(directory/"server.log").read_text()
   if any(marker in text for marker in ["AddressSanitizer","LeakSanitizer","runtime error:"]):result.update(passed=False,sanitizer_error=True)
  result["assertions"]=wire.ASSERTIONS
  (directory/"report.json").write_text(json.dumps(result,indent=2)+"\n")
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument("--build",type=Path,required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
 args.output.mkdir(parents=True)
 rows=[]
 for kind,seed,depart in [(kind,42+depart,depart) for kind in ["tcp","udp"] for depart in [0,1]]:
  result=match(kind,args.build,args.output,seed,depart);rows.append(result);print(json.dumps(result),flush=True)
  if not result["passed"]:break
 report=dict(passed=all(r["passed"] for r in rows),cases=rows,assertions=wire.ASSERTIONS,skipped=0)
 (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
 return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
