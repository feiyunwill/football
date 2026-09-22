"""Run only inside a newly created private mount namespace.
The parent owns this whole process group; no mount or executable is changed
in the parent's namespace. All command logs and the X server outcome are kept.
"""
from pathlib import Path
import argparse,json,os,select,struct,subprocess,sys,time,tempfile

ROOT=Path(__file__).resolve().parents[2]
TOOLS=Path(os.environ.get('FOOTBALL_TEST_X11_ROOT',
 str(Path.home()/'.cache/football-input-x11-20260913-a/root-relocated'))).resolve()

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--parent-mount-namespace',required=True)
 parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--build',type=Path,required=True)
 parser.add_argument('--library',type=Path,required=True)
 parser.add_argument('--sampler',type=Path,required=True)
 parser.add_argument('--sanitized-sampler',type=Path,required=True)
 parser.add_argument('--sanitized-build',type=Path,required=True)
 args=parser.parse_args()
 current=os.readlink('/proc/self/ns/mnt')
 if current==args.parent_mount_namespace:
  raise RuntimeError('Private mount namespace was not created')
 output=args.output.resolve()
 if not output.is_relative_to(ROOT) or output.exists():
  raise RuntimeError('Expected a new workspace output directory')
 output.mkdir()
 commands=[]
 def command(argv,label,timeout=15,env=None):
  started=time.monotonic()
  with (output/(label+'.log')).open('w') as log:
   result=subprocess.run(list(map(str,argv)),env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
  commands.append(dict(argv=list(map(str,argv)),log=label+'.log',returncode=result.returncode,
                       seconds=time.monotonic()-started))
  (output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
  if result.returncode:raise RuntimeError('Command failed: '+label)
 # 2026-09-13: keep overlay backing files outside archived evidence. Never
 # recursively clean a directory while a namespace may still mount it.
 overlay=Path(tempfile.mkdtemp(prefix='namespace-',dir=TOOLS.parent))
 for name in ('host-bin','upper','work'):
  (overlay/name).mkdir()
 # 2026-09-13: installed xkbcomp needs no overlay; only the missing-tool fallback is relocated.
 # # Bind the original tool directory as a stable, read-only overlay lower.
 # command(['mount','--bind','/usr/bin',overlay/'host-bin'],'bind-host-tools')
 # command(['mount','-t','overlay','overlay','-o',
 # f'lowerdir={overlay/"host-bin"},upperdir={overlay/"upper"},workdir={overlay/"work"}',
 # '/usr/bin'],'private-tools-overlay')
 # if Path('/usr/bin/xkbcomp').exists():raise RuntimeError('Unexpected host xkbcomp; reassess relocation')
 # Path('/usr/bin/xkbcomp').symlink_to(TOOLS/'usr/bin/xkbcomp')
 if not Path('/usr/bin/xkbcomp').exists():
  command(['mount','--bind','/usr/bin',overlay/'host-bin'],'bind-host-tools')
  command(['mount','-t','overlay','overlay','-o',
           f'lowerdir={overlay/"host-bin"},upperdir={overlay/"upper"},workdir={overlay/"work"}',
           '/usr/bin'],'private-tools-overlay')
  Path('/usr/bin/xkbcomp').symlink_to(TOOLS/'usr/bin/xkbcomp')
 # WSL's existing socket directory remains unchanged in the parent namespace.
 command(['mount','-t','tmpfs','-o','size=1m,mode=1777,nosuid,nodev','none','/tmp/.X11-unix'],'private-x-sockets')
 def field(value):return struct.pack('!H',len(value))+value
 authority=output/'authority'
 authority.write_bytes(struct.pack('!H',65535)+field(b'')+field(b'')+
                       field(b'MIT-MAGIC-COOKIE-1')+field(os.urandom(16)))
 authority.chmod(0o600)
 env=dict(os.environ,LD_LIBRARY_PATH=str(TOOLS/'usr/lib'),XAUTHORITY=str(authority),
          SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
 env.pop('LD_PRELOAD',None)
 read_fd,write_fd=os.pipe()
 argv=[str(TOOLS/'usr/bin/Xvfb'),'-displayfd',str(write_fd),'-screen','0','1280x720x24',
       '-nolisten','tcp','-auth',str(authority),'-xkbdir',str(TOOLS/'usr/share/X11/xkb')]
 record=dict(private_mount_namespace=current,parent_mount_namespace=args.parent_mount_namespace,
             server_argv=argv,ready=False,probe_passed=False,overlay_backing=str(overlay))
 server=None
 try:
  with (output/'server.log').open('w') as log:
   server=subprocess.Popen(argv,env=env,stdout=log,stderr=subprocess.STDOUT,pass_fds=(write_fd,))
   os.close(write_fd);write_fd=None
   record['server_pid']=server.pid
   readable,_,_=select.select([read_fd],[],[],10)
   reply=os.read(read_fd,80) if readable else b''
   if not reply.strip().isdigit() or server.poll() is not None:
    raise RuntimeError('Private X server did not signal readiness')
   display=int(reply.strip())
   if not 0<=display<=65535:raise RuntimeError('Invalid private display number')
   record.update(ready=True,display=display)
   env['DISPLAY']=':'+str(display)
   record['sampler_results']={}
   for label,binary in (('release',args.sampler),('sanitized',args.sanitized_sampler)):
    sampler_env=dict(env)
    if label=='sanitized':
     sampler_env.update(LD_LIBRARY_PATH=str(args.sanitized_build.resolve())+':'+str(TOOLS/'usr/lib'),
                        ASAN_OPTIONS='halt_on_error=1:detect_leaks=1:quarantine_size_mb=16',
                        UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1',LSAN_OPTIONS='exitcode=23')
    command([binary.resolve()],label+'-sampler',timeout=30,env=sampler_env)
    sampler=[json.loads(line) for line in (output/(label+'-sampler.log')).read_text().splitlines() if line.startswith('{')]
    if len(sampler)!=1 or sampler[0].get('passed') is not True or sampler[0].get('skipped')!=0 or sampler[0].get('assertions',0)<56:
     raise RuntimeError('Incomplete actual native keyboard/controller sampler')
    record['sampler_results'][label]=sampler[0]
   command([sys.executable,Path(__file__).with_name('native_input_window_cases.py'),'--build',args.build.resolve(),
            '--library',args.library.resolve(),'--output',output/'windows'],'windows',timeout=420,env=env)
   lines=(output/'windows.log').read_text().splitlines()
   reports=[json.loads(line) for line in lines if line.startswith('{')]
   if len(reports)!=1 or reports[0].get('passed') is not True or reports[0].get('skipped')!=0:
    raise RuntimeError('Incomplete actual native window result')
   record.update(probe_passed=True,probe_result=reports[0])
 except BaseException as error:
  record.update(error_type=type(error).__name__,error=str(error))
  raise
 finally:
  os.close(read_fd)
  if write_fd is not None:os.close(write_fd)
  if server is not None:
   if server.poll() is None:
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:
     server.kill();server.wait(timeout=5)
   record.update(server_reaped=True,server_returncode=server.returncode)
  (output/'report.json').write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps(record))
if __name__=='__main__':main()
