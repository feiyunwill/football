
from pathlib import Path
import argparse,json,os,re,socket,struct,subprocess,sys,time,traceback
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/".project/checks"))
import native_product_protocol_probe as wire
from native_product_udp_peer import NativeProductUDPPeer
from native_product_records import records

def case(server_binary,client_binary,directory,seed,depart):
 directory.mkdir(parents=True);client_dir=directory/"client";client_dir.mkdir()
 wire.SESSION=bytes([66])+wire.HELLO[1:]+struct.pack("<IBBII",seed,1,2,1,15000);wire.READY=bytes([65])+wire.SESSION[1:]
 server=client=fake=None;frames={};hashes={};notices={};result={"passed":False,"seed":seed,"depart":depart};phase="startup"
 try:
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reserve:
   reserve.bind(("127.0.0.1",0));port=reserve.getsockname()[1]
  with (directory/"server.log").open("w") as log:
   server=subprocess.Popen([str(server_binary),str(port),"1","2",str(seed),"1"],cwd=directory,env=os.environ,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
  until=time.monotonic()+30
  while time.monotonic()<until:
   wire.require(server.poll() is None,"Server failed to initialize")
   if wire.owned_bound(server,port,"udp"):break
   time.sleep(.02)
  else:raise RuntimeError("Native server bind timeout")
  def make_fake():
   peer=NativeProductUDPPeer(port);wire.require(peer.bootstrap()==depart,"Fake peer assignment differs");peer.socket.settimeout(.001);return peer
  if depart==0:fake=make_fake()
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as proxy:
   proxy.bind(("127.0.0.1",0));proxy.settimeout(.002);remote=("127.0.0.1",port);native_endpoint=None
   with (directory/"client.log").open("w") as log:
    client=subprocess.Popen([str(client_binary),"127.0.0.1",str(proxy.getsockname()[1]),"1","2",str(seed),"--headless","--frames","260"],
      cwd=client_dir,env=os.environ,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
   rx=0;identity=None;ordered={};buffer=bytearray();native_slot=None;fake_ready=False;dropped=False;last_sent=-1;heartbeat=time.monotonic()
   until=time.monotonic()+40;phase="native client bootstrap and real authority"
   def packet(frame):
    return struct.pack("<BIHHffH",2,frame,1,depart,1. if depart==0 else -1.,0.,512)
   while time.monotonic()<until and client.poll() is None:
    try:data,address=proxy.recvfrom(4096)
    except socket.timeout:data=None
    if data is not None:
     if address==remote:
      wire.require(native_endpoint is not None,"Server response before native client")
      if data[0]==1:
       wire.require(23<=len(data)<=1200,"Malformed scoped reliable server datagram")
       current_identity=data[1:17]
       if identity is None:identity=current_identity
       wire.require(identity==current_identity and any(identity),"Unexpected native client transport generation")
       seq,length=struct.unpack_from("<IH",data,17)
       wire.require(length==len(data)-23,"Malformed reliable server payload")
       if seq>=rx:
        wire.require(seq-rx<64,"Unbounded server sequence gap")
        prior=ordered.get(seq);wire.require(prior is None or prior==data[23:],"Server retransmission changed payload")
        ordered.setdefault(seq,data[23:])
       while rx in ordered:buffer.extend(ordered.pop(rx));rx+=1
       wire.require(len(buffer)<=8192,"Unbounded native client application buffer")
       for row in records(buffer):
        if row[0]==81:
         wire.require(len(row)==105 and row[10:42]==wire.SESSION,"Actual native session descriptor differs")
         native_slot=struct.unpack_from("<H",row,58)[0]
         wire.require(native_slot==1-depart and struct.unpack_from("<I",row,101)[0]==1<<native_slot,
                      "Native client must own its one assigned seat")
         wire.require(row[100]==2,"Actual client did not use bounded loading reservation")
         if fake is None:fake=make_fake()
        elif row[0]==3:
         fid,count=struct.unpack_from("<IH",row,1);wire.require(count==3 and fid not in frames,"Duplicate actual authority");frames[fid]=row
        elif row[0]==4:
         fid=struct.unpack_from("<I",row,1)[0];hashes[fid]=row
        elif row[0]==10:
         slot,fid=struct.unpack_from("<HI",row,1)
         wire.require(slot==depart and slot not in notices,"Unexpected takeover notice");notices[slot]=(fid,row)
      proxy.sendto(data,native_endpoint)
     else:
      if native_endpoint is None:native_endpoint=address
      wire.require(address==native_endpoint,"Unexpected native client endpoint")
      proxy.sendto(data,remote)
    if fake is not None and native_slot is not None and not fake_ready:
     fake.send(wire.READY+b"".join(packet(fid) for fid in range(10)));last_sent=9;fake_ready=True
    if fake is not None and fake_ready and not dropped:
     fake.pump()
     latest=max(frames,default=-1)
     if latest+6>last_sent:
      fake.send(b"".join(packet(fid) for fid in range(last_sent+1,latest+7)));last_sent=latest+6
     if latest>=40:dropped=True;phase="actual native client receives takeover"
     if time.monotonic()-heartbeat>.15:
      fake.send(struct.pack("<BII",8,max(0,latest),0));heartbeat=time.monotonic()
    wire.require(server.poll() is None,"Real authority stopped during native-client takeover")
   wire.require(client.poll() is not None,"Actual client stalled after takeover")
  text=(directory/"client.log").read_text();session=re.search(r"UDP session confirmed=(\d+) verified_hashes=(\d+) failed=(\d+)",text)
  wire.require(session is not None,"Missing actual native client final session")
  confirmed,verified,failed=map(int,session.groups())
  result.update(confirmed=confirmed,verified_hashes=verified,failed=failed,client_exit=client.returncode)
  wire.require(dropped and depart in notices,"No real peer expiry and takeover")
  result["takeover_frame"]=notices[depart][0]
  wire.require(client.returncode==0 and failed==0 and confirmed>=260,"Actual native client did not survive takeover")
  wire.require(confirmed<=300 and verified>=25,"Incomplete actual native-client hash verification")
  wire.require(confirmed-notices[depart][0]>=151,"Native client did not execute 151 bot authority frames")
  for fid in range(confirmed):wire.require(fid in frames,"Captured authority misses a confirmed client frame")
  replay=client_dir/f"replay_{seed}.bin";wire.require(replay.is_file(),"Actual native client did not save its replay")
  result.update(passed=True,actual_native_client=True,product_acceptance=False,replay=str(replay))
 except BaseException as error:
  traceback.print_exc();result.update(error=str(error),phase=phase)
 finally:
  if fake:fake.close()
  for proc in [client,server]:
   if proc is None:continue
   if proc.poll() is None:proc.terminate()
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
  if server:result["server_exit"]=server.returncode
  if client:result["client_exit"]=client.returncode
  for name in ["server.log","client.log"]:
   p=directory/name
   if p.exists() and any(mark in p.read_text() for mark in ["AddressSanitizer","LeakSanitizer","runtime error:"]):result.update(passed=False,sanitizer_error=True)
  if server and server.returncode!=0:result.update(passed=False,cleanup_error=True)
  confirmed=result.get("confirmed",len(frames));body=bytearray(struct.pack("<4sIBBH",b"FTAC",seed,1,2,1))
  for fid,row in sorted(frames.items()):
   if fid>=confirmed:continue
   for _,(frame,notice) in notices.items():
    if frame==fid:body.extend(notice)
   body.extend(row)
   if fid in hashes:body.extend(hashes[fid])
  (directory/"authority.bin").write_bytes(body)
  result.update(assertions=wire.ASSERTIONS,delivered_authority=len(frames),notices={str(k):v[0] for k,v in notices.items()})
  (directory/"report.json").write_text(json.dumps(result,indent=2)+"\n")
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument("--server",type=Path,required=True);p.add_argument("--client",type=Path,required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
 args.output.mkdir(parents=True);results=[]
 for depart in [0,1]:
  row=case(args.server,args.client,args.output/f"side-{depart}",42+depart,depart);results.append(row);print(json.dumps(row),flush=True)
  if not row["passed"]:break
 report=dict(passed=all(r["passed"] for r in results),assertions=wire.ASSERTIONS,skipped=0,cases=results)
 (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
 return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
