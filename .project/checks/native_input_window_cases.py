# 2026-09-13: require actual in-play held input and focus/pause/release authority.
"""Drive actual product windows using XTEST; never inject game-level inputs."""
from pathlib import Path
import argparse,ctypes,json,os,socket,subprocess,time

def require(value,text):
    if not value:raise RuntimeError(text)
def events(directory):
    p=directory/"events.jsonl"
    if not p.exists():return []
    result=[]
    for line in p.read_text().splitlines():
        try:result.append(json.loads(line))
        except ValueError:pass  # an in-progress final write is read again later
    return result

# 2026-09-13: independently decode actual saved authority, beyond local prediction.
def decode_replay(path):
    import struct
# 2026-09-13: decode the product envelope independently before the legacy payload.
#     data=path.read_bytes()
    data=path.read_bytes()
    # Independent wire oracle: do not import the producer's native contract.
    require(len(data)>=68 and data[:8]==b"FNRPLY1\x00","Missing native replay envelope")
    require(data[8:26]==bytes([66,70,78,65,84,1,0,0,50,0,50,0,2,0,16,39,0,0]),
            "Native replay family or physics cadence differs")
    require(struct.unpack_from("<IBBII",data,26)==(42,1,1,1,15000),
            "Native replay seed, teams or scenario differs")
    data=data[40:]
    require(len(data)>=28,"Truncated actual replay")
    seed,length=struct.unpack_from("<II",data)
    require(length<=1024 and len(data)>=28+length,"Invalid actual replay header")
    scenario=data[8:8+length].decode()
    offset=8+length
    total,slots,final,count=struct.unpack_from("<IIQI",data,offset);offset+=20
    require(seed==42 and scenario=="default_11v11" and slots==2 and total==count and count>0,
            "Actual replay session metadata differs")
    require(len(data)-offset==count*(12+10*slots),"Actual replay shape differs")
    rows=[]
    for index in range(count):
        frame,digest=struct.unpack_from("<IQ",data,offset);offset+=12
        inputs=[struct.unpack_from("<ffH",data,offset+10*slot) for slot in range(slots)];offset+=10*slots
        require(frame==index,"Actual replay authority is not contiguous from frame zero")
        rows.append(dict(frame=frame,hash=digest,inputs=inputs))
    require(rows[-1]["hash"]==final,"Actual replay final hash differs")
    return rows

class Keyboard:
    def __init__(self):
        self.x=ctypes.CDLL("libX11.so.6");self.t=ctypes.CDLL("libXtst.so.6")
        self.x.XOpenDisplay.argtypes=[ctypes.c_char_p];self.x.XOpenDisplay.restype=ctypes.c_void_p
        self.x.XStringToKeysym.argtypes=[ctypes.c_char_p];self.x.XStringToKeysym.restype=ctypes.c_ulong
        self.x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong];self.x.XKeysymToKeycode.restype=ctypes.c_uint
        self.x.XSetInputFocus.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        self.x.XGetInputFocus.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_int)]
        self.x.XSync.argtypes=[ctypes.c_void_p,ctypes.c_int]
        self.x.XCloseDisplay.argtypes=[ctypes.c_void_p]
        self.t.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
        self.display=self.x.XOpenDisplay(None);require(self.display,"Cannot open private display")
        self.held=set()
    def focus(self,window):
        self.x.XSetInputFocus(self.display,window,1,0);self.x.XSync(self.display,0)
        actual=ctypes.c_ulong();revert=ctypes.c_int()
        self.x.XGetInputFocus(self.display,ctypes.byref(actual),ctypes.byref(revert))
        require(actual.value==window,"Actual X focus differs")
    def key(self,name,down):
        key=self.x.XKeysymToKeycode(self.display,self.x.XStringToKeysym(name.encode()))
        require(key and self.t.XTestFakeKeyEvent(self.display,key,int(down),0),"XTEST key delivery failed")
        self.x.XSync(self.display,0)
        if down:self.held.add(name)
        else:self.held.discard(name)
    def tap(self,name):
        self.key(name,True);time.sleep(.02);self.key(name,False)
    def close(self):
        for name in list(self.held):self.key(name,False)
        self.x.XCloseDisplay(self.display)

def case(kind,build,library,output):
    directory=output/kind;directory.mkdir()
    trace=directory/"trace";trace.mkdir()
    runtime=dict(os.environ,LD_LIBRARY_PATH=str(build)+":"+os.environ.get("LD_LIBRARY_PATH",""),
                 LD_PRELOAD=str(library),FOOTBALL_NATIVE_TRACE=str(trace),
                 GFOOTBALL_DATA_DIR=str(Path(__file__).resolve().parents[2]/"engine/data"),LIBGL_ALWAYS_SOFTWARE="1")
    server=None;client=None;keyboard=None;streams=[];actions=[]
    result=dict(passed=False,kind=kind)
    authority=None
    try:
        if kind=="standalone":
            argv=[str(build/"bin/standalone_game"),"--seed","42"]
        else:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM if kind=="udp" else socket.SOCK_STREAM) as reserve:
                reserve.bind(("127.0.0.1",0));port=reserve.getsockname()[1]
            server_trace=directory/"server-trace";server_trace.mkdir()
            server_env=dict(runtime,FOOTBALL_NATIVE_TRACE=str(server_trace))
            log=(directory/"server.log").open("w");streams.append(log)
            server=subprocess.Popen([str(build/("bin/football_server" if kind=="udp" else "bin/football_server_tcp")),
                                    str(port),"1","1","42"],cwd=directory,env=server_env,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+30
            while True:
                require(server.poll() is None,"Actual server stopped before binding")
                descriptors=set()
                for entry in Path(f"/proc/{server.pid}/fd").iterdir():
                    try:link=os.readlink(entry)
                    except FileNotFoundError:continue
                    if link.startswith("socket:["):descriptors.add(link[8:-1])
                table="/proc/net/udp" if kind=="udp" else "/proc/net/tcp"
                if any(int(row[1].split(":")[1],16)==port and row[9] in descriptors
                       for row in [line.split() for line in Path(table).read_text().splitlines()[1:]]):break
                require(time.monotonic()<deadline,"Actual server bind deadline");time.sleep(.02)
            argv=[str(build/("bin/football_client" if kind=="udp" else "bin/football_client_tcp")),
                  "127.0.0.1",str(port)]
        log=(directory/"client.log").open("w");streams.append(log)
        client=subprocess.Popen(argv,cwd=directory,env=runtime,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+30
        rows=[]
        # 2026-09-13: the first SDL swap is the loading screen, before reset finishes.
        # while not any(r["kind"]=="swap" and r["xid"] for r in rows):
        while not (any(r["kind"]=="render" for r in rows) and
                   any(r["kind"]=="step" for r in rows) and
                   any(r["kind"]=="swap" and r["xid"] and r["render_owner"] for r in rows)):
            require(client.poll() is None,"Actual graphical client failed")
            require(time.monotonic()<deadline,"No actual SDL swap/window")
            time.sleep(.02);rows=events(trace)
        keyboard=Keyboard();keyboard.focus(next(r["xid"] for r in rows if r["kind"]=="swap" and r["xid"]))
        def mark(name):actions.append(dict(action=name,time=time.monotonic_ns()))
        deadline=time.monotonic()+90
        while not any(r["kind"]=="step_timing" and r["in_play"] and r["sim_step"]>=20 for r in events(trace)):
            require(client.poll() is None and time.monotonic()<deadline,"Match did not reach actual in-play state")
            time.sleep(.02)
        mark("in_play_observed")
        mark("hold_direction_sprint");keyboard.key("d",True);keyboard.key("Shift_L",True);time.sleep(2.0)
        mark("release");keyboard.key("d",False);keyboard.key("Shift_L",False);time.sleep(.5)
        mark("short_shot");keyboard.tap("v");time.sleep(.5)
        mark("focus_hold");keyboard.key("d",True);keyboard.key("Shift_L",True);time.sleep(.5)
        keyboard.x.XDefaultRootWindow.argtypes=[ctypes.c_void_p]
        keyboard.x.XDefaultRootWindow.restype=ctypes.c_ulong
        mark("focus_loss");keyboard.focus(keyboard.x.XDefaultRootWindow(keyboard.display));time.sleep(.7)
        keyboard.key("d",False);keyboard.key("Shift_L",False)
        mark("focus_regain");keyboard.focus(next(r["xid"] for r in rows if r["kind"]=="swap" and r["xid"]));time.sleep(.4)
        keyboard.key("d",True);keyboard.key("Shift_L",True);time.sleep(.3)
        def await_transition(kind):
            deadline=time.monotonic()+5
            while not any(row["kind"]==kind for row in events(trace)):
                require(client.poll() is None and time.monotonic()<deadline,"Actual pause/resume transition missing")
                time.sleep(.01)
        mark("pause");keyboard.tap("k")
        if kind=="standalone":await_transition("pause")
        time.sleep(.6)
        mark("resume");keyboard.tap("k")
        if kind=="standalone":await_transition("resume")
        time.sleep(.5)
        mark("resume_release");keyboard.key("d",False);keyboard.key("Shift_L",False);time.sleep(.3)
        mark("resume_repress");keyboard.key("d",True);keyboard.key("Shift_L",True);time.sleep(.4)
        keyboard.key("d",False);keyboard.key("Shift_L",False);time.sleep(.3)
        prefix_size=None
        if kind!="standalone":
            mark("midmatch_save");keyboard.tap("p")
            replay=directory/"replay_42.bin";deadline=time.monotonic()+10
            while not replay.exists():
                require(client.poll() is None and time.monotonic()<deadline,"Midmatch replay was not saved")
                time.sleep(.02)
            prefix_size=replay.stat().st_size
            (directory/"midmatch-replay.bin").write_bytes(replay.read_bytes())
            time.sleep(.8)
        mark("quit");keyboard.tap("q")
        code=client.wait(timeout=15)
        rows=events(trace)
        (directory/"actions.json").write_text(json.dumps(actions,indent=2)+"\n")
        require(code==0,"Actual window program did not exit successfully")
        render=[r for r in rows if r["kind"]=="render"]
        steps=[r for r in rows if r["kind"]=="step"]
        swaps=[r for r in rows if r["kind"]=="swap"]
        require(len(render)>=6 and len(steps)>=6,"Insufficient actual display/logic samples")
        require(all(r["present_delta"]==1 and r["swap_requested"] and r["state_stable"] for r in render),
                "A rendered frame has duplicate/missing presentation or mutated simulation")
        # 2026-09-13: retain and report initialization swaps; verify all match swaps strictly.
        # require(len(swaps)==len(render),"Presentation bypassed the shared render owner")
        match_swaps=[r for r in swaps if r["render_owner"]]
        loading_swaps=[r for r in swaps if not r["render_owner"]]
        require(len(match_swaps)==len(render),"Match presentation bypassed the shared render owner")
        first_match=min(r["time"] for r in match_swaps)
        require(all(r["time"]<first_match for r in loading_swaps),"Unowned swap after match rendering began")
        require(any(0<r["alpha"]<1 for r in render),"No actual interpolated intermediate frame")
        require(any(r["x"]==1 and r["buttons"]&(1<<9) for r in steps),"Actual direction/sprint never reached engine")
        release=next(r["time"] for r in actions if r["action"]=="release")
        shot=next(r["time"] for r in actions if r["action"]=="short_shot")
        require(any(release<r["time"]<shot and r["x"]==0 and not r["buttons"] for r in steps),
                "Released input was not cleared in the real engine")
        require(any(r["buttons"]&(1<<3) for r in steps),"A short physical shot tap was lost")
        require(all(r["controllable"]==11 for r in steps),"Product roster disallows field players")
        if kind=="standalone":
            pause=next(r["time"] for r in rows if r["kind"]=="pause")
            resume=next(r["time"] for r in rows if r["kind"]=="resume")
            require(not any(pause<r["time"]<resume for r in steps),"Paused local match advanced")
            require(any(pause<r["time"]<resume for r in render),"Paused local window stopped rendering")
        else:
            require((directory/"replay_42.bin").stat().st_size>prefix_size,"Midmatch save stopped recording")
            full=decode_replay(directory/"replay_42.bin")
            prefix=decode_replay(directory/"midmatch-replay.bin")
            require(len(full)>len(prefix) and full[:len(prefix)]==prefix,
                    "Midmatch save changed prior confirmed inputs or stopped recording")
            require(any(row["inputs"][0][0]==1 and row["inputs"][0][2]&(1<<9) for row in full),
                    "Direction/sprint never entered actual server authority")
            require(any(row["inputs"][0][2]&(1<<3) for row in full),
                    "Short physical shot never entered actual server authority")
            require(any(not any(row["inputs"][0]) for row in full[1:]),"No neutral authority input")
            if kind=="tcp":
                require(all(not any(row["inputs"][1]) for row in full),"TCP input escaped its owned slot")
            else:
                require(all(row["inputs"][0]==row["inputs"][1] for row in full),
                        "UDP owned-slot publication differs")
            authority=dict(frames=len(full),prefix_frames=len(prefix),
                nonzero_frames=sum(any(row["inputs"][0]) for row in full),
                shot_frames=sum(bool(row["inputs"][0][2]&(1<<3)) for row in full),
                actual_saved_confirmed_inputs=True,full_engine_replay_verified=False)

        # 2026-09-13: encode captured RGB bytes losslessly with stdlib; this environment has no PIL.
        # from PIL import Image
        # pictures=[]
        # for source in sorted(trace.glob("*.ppm")):
        # image=Image.open(source);require(image.size==(1280,720),"Unexpected actual window size")
        # colors=image.getextrema();require(any(hi>lo for lo,hi in colors),"Blank real framebuffer")
        # destination=source.with_suffix(".png");image.save(destination)
        # pictures.append(dict(path=str(destination),width=image.width,height=image.height))
        import struct,zlib
        pictures=[]
        for source in sorted(trace.glob("*.ppm")):
            magic,dimensions,maximum,pixels=source.read_bytes().split(b"\n",3)
            width,height=map(int,dimensions.split())
            require(magic==b"P6" and maximum==b"255" and len(pixels)==width*height*3,
                    "Malformed actual RGB framebuffer")
            require((width,height)==(1280,720),"Unexpected actual window size")
            require(any(max(pixels[channel::3])>min(pixels[channel::3]) for channel in range(3)),
                    "Blank real framebuffer")
            def chunk(kind,payload):
                return (struct.pack(">I",len(payload))+kind+payload+
                        struct.pack(">I",zlib.crc32(kind+payload)&0xffffffff))
            raw=b"".join(b"\x00"+pixels[row*width*3:(row+1)*width*3] for row in range(height))
            packed=zlib.compress(raw)
            require(zlib.decompress(packed)==raw,"PNG roundtrip changed actual framebuffer bytes")
            png=(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))+
                 chunk(b"IDAT",packed)+chunk(b"IEND",b""))
            destination=source.with_suffix(".png");destination.write_bytes(png)
            pictures.append(dict(path=str(destination),width=width,height=height))
        require(len(pictures)>=3,"Missing actual image artifacts")
        timing=[r for r in rows if r["kind"]=="step_timing"]
        start=next(a["time"] for a in actions if a["action"]=="hold_direction_sprint")
        end=next(a["time"] for a in actions if a["action"]=="release")
        begin=next(r for r in timing if r["start"]>=start)
        last=next(r for r in timing if r["start"]>=end)
        held=[r for r in steps if start+300000000<r["time"]<end-300000000]
        timings={r["index"]:r for r in timing}
        responding=[r for r in steps if r["time"]>=start and r["x"]==1 and r["buttons"]&512]
        require(responding and held,"No in-play input witness")
        def distribution(values):
            values=sorted(values)
            return dict(count=len(values),p50_ms=values[len(values)//2]/1e6,
                        p95_ms=values[min(len(values)-1,int(len(values)*.95))]/1e6,max_ms=values[-1]/1e6)
        measurements=dict(actual_in_play=True,wall_seconds=(end-start)/1e9,
          simulated_seconds=(last["sim_step"]-begin["sim_step"])*.02,
          local_response_completion_ms=(responding[0]["time"]-start)/1e6,
          response_in_play=timings[responding[0]["index"]]["in_play"],
          step=distribution([r["step_ns"] for r in timing]),
          render=distribution([r["render_ns"] for r in rows if r["kind"]=="render_timing"]),
          render_observer=distribution([r["observer_ns"] for r in rows if r["kind"]=="render_timing"]),
          held_local_frames=len(held),held_local_neutral=sum(not r["x"] and not r["buttons"] for r in held),
          latency_acceptance=False)
        if kind!="standalone":
            authority_steps=[r for r in events(directory/"server-trace") if r["kind"]=="step" and start+300000000<r["time"]<end-300000000]
            require(authority_steps,"No contemporaneous authority observation")
            measurements.update(held_authority_frames=len(authority_steps),
              held_authority_nonzero=sum(r["x"]==1 and bool(r["buttons"]&512) for r in authority_steps),
              held_authority_neutral=sum(not r["x"] and not r["buttons"] for r in authority_steps))
            require(measurements["held_authority_nonzero"]==measurements["held_authority_frames"],
                    "Continuous held input contains neutral or incomplete authority frames")
            server_rows=[r for r in events(directory/"server-trace") if r["kind"]=="step"]
            action_times={r["action"]:r["time"] for r in actions}
            clearing={}
            for label,first,last in (
                ("release",action_times["release"]+300000000,action_times["short_shot"]-50000000),
                ("focus_loss",action_times["focus_loss"]+300000000,action_times["focus_regain"]-50000000),
                ("controls_paused",action_times["pause"]+300000000,action_times["resume"]-50000000),
                ("resume_held_barrier",action_times["resume"]+300000000,action_times["resume_release"]-50000000)):
                interval=[r for r in server_rows if first<r["time"]<last]
                require(len(interval)>=3 and all(not r["x"] and not r["y"] and not r["buttons"] for r in interval),
                        "Authority retained stale input after "+label)
                clearing[label]=len(interval)
            interval=[r for r in server_rows if action_times["resume_repress"]+200000000<r["time"]<action_times["resume_repress"]+350000000]
            require(len(interval)>=3 and all(r["x"]==1 and r["buttons"]&512 for r in interval),
                    "Fresh input was not rearmed after the resume release barrier")
            measurements.update(continuous_held_authority_verified=True,clearing_frames=clearing,
                                resume_repressed_frames=len(interval))
        result["measurements"]=measurements
        result.update(passed=True,skipped=0,renders=len(render),steps=len(steps),swaps=len(swaps),match_swaps=len(match_swaps),loading_swaps=len(loading_swaps),
                      images=pictures,actual_product_main=True,actual_x11=True,actual_xtest=True,
                      latency_acceptance=False,client_exit=code,authority=authority)
    except Exception as error:
        result.update(error_type=type(error).__name__,error=str(error))
    finally:
        if keyboard:keyboard.close()
        if client and client.poll() is None:
            client.terminate()
            try:client.wait(timeout=5)
            except subprocess.TimeoutExpired:client.kill();client.wait(timeout=5)
            result["client_forced_cleanup"]=True
        if server and server.poll() is None:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
# 2026-09-13: a reaped server must also exit successfully on graceful termination.
#             result["server_exit"]=server.returncode
            result["server_exit"]=server.returncode
        if server:
            result["server_exit"]=server.returncode
            if server.returncode!=0:
                result.update(passed=False,error="Product server did not exit cleanly")
        for stream in streams:stream.close()
        (directory/"actions.json").write_text(json.dumps(actions,indent=2)+"\n")
        (directory/"report.json").write_text(json.dumps(result,indent=2)+"\n")
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--build",type=Path,required=True);parser.add_argument("--library",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(exist_ok=False)
    rows=[]
    for kind in ("standalone","tcp","udp"):
        row=case(kind,args.build,args.library,args.output);rows.append(row)
        if not row["passed"]:break
    report=dict(passed=len(rows)==3 and all(r["passed"] for r in rows),skipped=0,cases=rows)
    (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report))
    return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
