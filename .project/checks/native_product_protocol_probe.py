#!/usr/bin/env python3
"""Independent native product bootstrap/ready/roster and two-peer authority probe."""
from pathlib import Path
import argparse,hashlib,json,os,socket,struct,subprocess,time
HELLO=bytes([64,70,78,65,84,1,0,0,50,0,50,0,2,0,16,39,0,0])
SESSION=bytes([66])+HELLO[1:]+struct.pack("<IBBII",42,1,1,1,15000)
READY=bytes([65])+SESSION[1:]
ASSERTIONS=0
def require(value,reason):
    global ASSERTIONS
    ASSERTIONS+=1
    if not value:raise RuntimeError(reason)
def messages(buffer):
    rows=[]
    while buffer:
        kind=buffer[0]
        size={66:32,4:13,8:9,10:7,11:7}.get(kind)
        if kind in (3,7):
            at=5 if kind==3 else 1
            if len(buffer)<at+2:break
            count=struct.unpack_from("<H",buffer,at)[0]
            require(0<count<=22,"Unbounded native wire count")
            size=at+2+count*(10 if kind==3 else 2)
        require(size is not None,"Unexpected native server packet "+str(kind))
        if len(buffer)<size:break
        rows.append(bytes(buffer[:size]));del buffer[:size]
    return rows
class Peer:
    def __init__(self,kind,port):
        self.kind=kind;self.socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM if kind=="tcp" else socket.SOCK_DGRAM)
        self.socket.settimeout(1);self.socket.connect(("127.0.0.1",port));self.socket.settimeout(.01)
        self.buffer=bytearray();self.tx=0;self.rx=0;self.pending={};self.ordered={};self.closed=False
    def close(self):self.socket.close()
    def raw(self,data):self.socket.sendall(data)
    def send(self,data):
        if self.kind=="tcp":self.raw(data)
        else:
            wire=struct.pack("<BIH",0,self.tx,len(data))+data
            self.pending[self.tx]=(wire,time.monotonic());self.tx+=1;self.raw(wire)
    def pump(self):
        now=time.monotonic()
        if self.kind=="udp":
            for seq,(wire,sent) in list(self.pending.items()):
                if now-sent>=.1:self.raw(wire);self.pending[seq]=(wire,now)
        try:data=self.socket.recv(4096)
        except socket.timeout:return []
        if self.kind=="tcp":
            if not data:self.closed=True;return []
            self.buffer.extend(data)
        else:
            if len(data)==5 and data[0]==255:
                self.pending.pop(struct.unpack_from("<I",data,1)[0],None);return []
            require(len(data)>=7 and data[0]==0,"Invalid reliable server packet")
            _,seq,length=struct.unpack_from("<BIH",data)
            require(length==len(data)-7,"Truncated reliable server payload")
            self.raw(struct.pack("<BI",255,seq))
            if seq>=self.rx:
                require(seq-self.rx<64,"Unbounded reliable sequence jump")
                self.ordered.setdefault(seq,data[7:])
            while self.rx in self.ordered:
                self.buffer.extend(self.ordered.pop(self.rx));self.rx+=1
        return messages(self.buffer)
    def quiet(self,seconds,allow_heartbeat=False):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            rows=self.pump()
            require(all(row[0]==8 for row in rows) if allow_heartbeat else not rows,
                    "Authority or bootstrap escaped the handshake barrier")
            if self.closed:return
    def bootstrap(self,fragment=False):
        if fragment and self.kind=="tcp":
            self.raw(HELLO[:9]);self.quiet(.06);self.raw(HELLO[9:])
        else:self.raw(HELLO)
        rows=[];until=time.monotonic()+3
        while len(rows)<2 and not self.closed and time.monotonic()<until:rows+=self.pump()
        require(len(rows)==2 and rows[0]==SESSION and rows[1][0]==7,"Expected native bootstrap before timeout")
        require(len(rows[1])==5 and struct.unpack_from("<H",rows[1],1)[0]==1,"One slot per peer expected")
        return struct.unpack_from("<H",rows[1],3)[0]
def owned_bound(process,port,kind):
    descriptors=set()
    for entry in Path(f"/proc/{process.pid}/fd").iterdir():
        try:link=os.readlink(entry)
        except FileNotFoundError:continue
        if link.startswith("socket:["):descriptors.add(link[8:-1])
    rows=[line.split() for line in Path("/proc/net/"+("tcp" if kind=="tcp" else "udp")).read_text().splitlines()[1:]]
    return any(int(row[1].split(":")[1],16)==port and row[9] in descriptors for row in rows)
def match(kind,build,environment,output):
    directory=output/kind;directory.mkdir();peers=[];server=None;phase="startup";result={"kind":kind,"passed":False}
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM if kind=="tcp" else socket.SOCK_DGRAM) as reserve:
            reserve.bind(("127.0.0.1",0));port=reserve.getsockname()[1]
        argv=[str(build/("bin/football_server_tcp" if kind=="tcp" else "bin/football_server")),str(port),"1","1","42"]
        if kind=="udp":argv+=["1"]
        with (directory/"server.log").open("w") as log:
            server=subprocess.Popen(argv,cwd=directory,env=environment,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        until=time.monotonic()+30
        while time.monotonic()<until:
            require(server.poll() is None,"Native server stopped during startup")
            if owned_bound(server,port,kind):break
            time.sleep(.02)
        else:raise RuntimeError("Native server bind timeout")
        phase="legacy rejection"
        legacy=Peer(kind,port);peers.append(legacy);legacy.raw(b"\0");legacy.quiet(.1)
        if kind=="tcp":require(legacy.closed,"Legacy TCP bootstrap was not rejected")
        else:
            legacy.raw(HELLO[:9]);legacy.quiet(.06)
            wrong=bytearray(HELLO);wrong[8]=10;legacy.raw(wrong);legacy.quiet(.06)
        phase="bad ready and replacement"
        bad=Peer(kind,port);peers.append(bad)
        require(bad.bootstrap(fragment=True)==0,"Malformed probes reserved a product slot")
        wrong=bytearray(READY);wrong[8]=10;bad.send(wrong);bad.quiet(.15)
        if kind=="tcp":require(bad.closed,"Mismatched TCP ready was not rejected")
        first=Peer(kind,port);peers.append(first)
        first_slot=first.bootstrap()
        require(first_slot==0,"Failed pregame handshake permanently reserved slot zero")
        second=Peer(kind,port);peers.append(second)
        second_slot=second.bootstrap();require(second_slot==1,"Native peer slot ownership differs")
        phase="fragmented ready barrier"
        def inputs(slot,direction):
            return b"".join(struct.pack("<BIHHffH",2,frame,1,slot,direction,0.,512|(8 if frame==4 else 0))
                            for frame in range(10))
        first.send(READY+inputs(first_slot,1.))
        second.send(READY[:16])
        first.quiet(.12,allow_heartbeat=True);second.quiet(.02)
        phase="two-peer authority"
        second.send(READY[16:]+inputs(second_slot,-1.))
        frames=[{},{}];digests=[{},{}];arrivals=[[],[]];until=time.monotonic()+6;heartbeat=time.monotonic()
        while any(len(group)<50 for group in frames) and time.monotonic()<until:
            for index,peer in enumerate((first,second)):
                for row in peer.pump():
                    if row[0]==3:
                        frame,count=struct.unpack_from("<IH",row,1)
                        require(count==2 and frame not in frames[index],"Authority repeated or changed slot count")
                        frames[index][frame]=row;arrivals[index].append(time.monotonic())
                    elif row[0]==4:
                        frame,digest=struct.unpack_from("<IQ",row,1);digests[index][frame]=digest
                    else:require(row[0]==8,"Unexpected control change during admitted match")
            if time.monotonic()-heartbeat>=.15:
                heartbeat=time.monotonic()
                for peer in (first,second):peer.send(struct.pack("<BII",8,0,0))
            require(server.poll() is None,"Actual native authority died")
        require(all(len(group)>=50 for group in frames),"Native 50 Hz authority did not complete 50 frames")
        for frame in range(50):
            require(frame in frames[0] and frames[0][frame]==frames[1].get(frame),"Two actual peers received different authority")
            actual=[struct.unpack_from("<ffH",frames[0][frame],7+10*slot) for slot in range(2)]
            expected=[(1.,0.,512|(8 if frame==4 else 0)),(-1.,0.,512|(8 if frame==4 else 0))] if frame<10 else [(0.,0.,0),(0.,0.,0)]
            require(actual==expected,"Owned input or neutral timeout changed authoritative data")
        for frame in range(0,50,10):
            require(frame in digests[0] and digests[0][frame]==digests[1].get(frame),"Peers missed matching real engine hash")
        result.update(passed=True,frames=50,nonzero_frames=10,matching_hashes=5,
                      arrival_span_seconds=[times[49]-times[0] for times in arrivals],
                      device_latency_acceptance=False,actual_product_server=True)
    except Exception as error:result.update(error=str(error),phase=phase)
    finally:
        for peer in peers:peer.close()
        if server:
            if server.poll() is None:server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
            result["server_exit"]=server.returncode
            if server.returncode!=0:result.update(passed=False,cleanup_error="Native server did not exit cleanly")
        (directory/"report.json").write_text(json.dumps(result,indent=2)+"\n")
    return result
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--build",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);build=args.build.resolve()
    environment=dict(os.environ,LD_LIBRARY_PATH=str(build),SDL_VIDEODRIVER="offscreen")
    environment.pop("LD_PRELOAD",None)
    binaries={str(build/"libfootball_engine.so"):hashlib.sha256((build/"libfootball_engine.so").read_bytes()).hexdigest()}
    for target in ("football_server_tcp","football_server"):
        p=build/"bin"/target;binaries[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    rows=[]
    for kind in ("tcp","udp"):
        row=match(kind,build,environment,args.output.resolve());rows.append(row)
        if not row["passed"]:break
    report=dict(passed=len(rows)==2 and all(row["passed"] for row in rows),skipped=0,assertions=ASSERTIONS,
                cases=rows,binaries=binaries,scope="Actual native bootstrap and two-peer authority; loopback, no WAN or device latency acceptance")
    for path,digest in binaries.items():require(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest,"Product binary changed during probe")
    (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report),flush=True)
    return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
