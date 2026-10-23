"""Explicitly enrolled Revu sample document: no global input or live-process ownership."""
import base64
import io
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from .errors import DesktopError, require
from .protocol import ROOT
from .session import kill_process, process_start

TITLE = os.environ.get('LAD_REVU_TITLE', '')


def live_configuration():
    values = {name: os.environ.get(name, '') for name in
              ('LAD_WINE_BIN', 'LAD_WINEPREFIX', 'LAD_REVU_TITLE')}
    require(all(values.values()), 'live_not_configured',
            'Set LAD_WINE_BIN, LAD_WINEPREFIX and LAD_REVU_TITLE before starting the daemon')
    title = values['LAD_REVU_TITLE']
    require(3 <= len(title) <= 200 and title.isascii() and title.isprintable(),
            'invalid_argument', 'Use a distinctive printable ASCII test-document title')
    runner, prefix = Path(values['LAD_WINE_BIN']), Path(values['LAD_WINEPREFIX'])
    require(runner.is_absolute() and prefix.is_absolute() and prefix.is_dir(),
            'invalid_argument', 'Explicit absolute Wine binary and existing prefix directories are required')
    require((runner/'wine').is_file() and (runner/'wineserver').is_file(),
            'missing_dependency', 'Configured Wine binaries are unavailable')
    return runner, prefix, values
ALLOWED = {'discover','geometry','screenshot','click','drag'}


def host_state(d):
    focus=d.get_input_focus().focus
    pointer=d.screen().root.query_pointer()
    active=d.screen().root.get_full_property(d.intern_atom('_NET_ACTIVE_WINDOW'),0)
    return {'focus':focus if isinstance(focus,int) else focus.id,
            'active':list(active.value) if active else [], 'pointer':[pointer.root_x,pointer.root_y]}


def x11_operation(op):
    require(bool(TITLE), 'live_not_configured', 'No live test-document title is configured')
    from Xlib import X,display
    from PIL import Image
    d=display.Display()
    try:
        root=d.screen().root
        if op['action']=='probe':
            prop=root.get_full_property(d.intern_atom('_NET_CLIENT_LIST'),X.AnyPropertyType)
            matches=[]
            for xid in prop.value if prop else []:
                w=d.create_resource_object('window',int(xid))
                klass=w.get_wm_class() or ()
                if not any('revu.exe'==v.lower() for v in klass):continue
                title=w.get_wm_name() or ''
                if TITLE in title and 'Bluebeam Revu x64' in title:
                    pid=w.get_full_property(d.intern_atom('_NET_WM_PID'),X.AnyPropertyType)
                    require(pid is not None,'stale_target','Revu PID is unavailable')
                    matches.append({'native_id':w.id,'pid':int(pid.value[0])})
            require(len(matches)==1,'invalid_target','Exactly one matching Revu test window is required')
            return matches[0]
        require(process_start(op['pid'])==op['start'],'stale_target','Enrolled Revu process has changed')
        w=d.create_resource_object('window',op['native_id'])
        prop=w.get_full_property(d.intern_atom('_NET_WM_PID'),X.AnyPropertyType)
        require(prop is not None and int(prop.value[0])==op['pid'],'stale_target','Revu window identity changed')
        require(TITLE in (w.get_wm_name() or ''),'stale_target','Enrolled test document is no longer active')
        require(w.get_attributes().map_state==X.IsViewable,'not_viewable','Revu must remain mapped for this capture path')
        g=w.get_geometry()
        if op['action']=='state':return host_state(d)
        if op['action']=='discover':
            return {'windows':[{'native_id':w.id,'pid':op['pid'],'title':TITLE,
                                'width':g.width,'height':g.height,'coordinate_space':'window physical pixels'}]}
        if op['action']=='geometry':return {'width':g.width,'height':g.height,'coordinate_space':'window physical pixels'}
        require(op['action']=='screenshot','unsupported_action','Unsupported live capture operation')
        before=host_state(d)
        require(g.depth==24 and d.display.info.image_byte_order==X.LSBFirst,'unsupported_visual','Capture requires the tested 24-bit little-endian visual')
        raw=w.get_image(0,0,g.width,g.height,X.ZPixmap,0xffffffff)
        image=Image.frombytes('RGB',(g.width,g.height),raw.data,'raw','BGRX')
        out=io.BytesIO();image.save(out,format='PNG')
        require(host_state(d)==before,'focus_changed','Host input state changed during capture')
        return {'png':base64.b64encode(out.getvalue()).decode(),'width':g.width,'height':g.height,
                'focus_unchanged':True,'pointer_unchanged':True,'scope':'live Revu test window'}
    finally:d.close()


class LiveRevu:
    """Only helper processes belong to us. close() never kills Revu or wineserver."""
    kind='wine-revu'
    def __init__(self,directory):
        self.runner, prefix, config = live_configuration()
        self.directory=Path(directory);self.directory.mkdir(mode=0o700)
        self.cancelled=False;self.processes=[];self.lock=threading.RLock()
        self.env={k:os.environ[k] for k in ('PATH','LANG','DISPLAY','XAUTHORITY','XDG_RUNTIME_DIR') if k in os.environ}
        self.env.update(config)
        self.env.update(WINEPREFIX=str(prefix),WINESERVER=str(self.runner/'wineserver'),WINEDEBUG='-all',PYTHONPATH=str(ROOT))
        require((self.runner/'wine').is_file(),'missing_dependency','Configured Wine runner is unavailable')
        for source in ('revu-control','revu-probe'):
            binary=self.directory/(source+'.exe')
            self.command(['x86_64-w64-mingw32-gcc','-O2','-Wall',str(Path(__file__).parent/'native'/f'{source}.c'),'-o',str(binary),'-luser32'],timeout=15)
        self.target=json.loads(self.command([sys.executable,'-m','lad.live_revu'],{'action':'probe'}))
        if 'error' in self.target:
            raise DesktopError(self.target['error']['code'],self.target['error']['message'])
        self.target['start']=process_start(self.target['pid'])
        require(self.target['start'] is not None,'stale_target','Revu exited during enrollment')
        identity=self.command([str(self.runner/'wine'),str(self.directory/'revu-probe.exe'),'--identity'])
        match=re.search(r'root=([0-9a-fA-F]+) pid=(\d+)',identity)
        require(match is not None,'invalid_target','Wine test-document identity is unavailable')
        self.env.update(LAD_EXPECT_HWND=match.group(1),LAD_EXPECT_WINPID=match.group(2))

    def command(self,argv,value=None,timeout=8):
        with self.lock:
            require(not self.cancelled,'cancelled','Live enrollment was revoked')
            p=subprocess.Popen(argv,env=self.env,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            self.processes.append(p)
        try:
            stdout,_=p.communicate(None if value is None else json.dumps(value).encode(),timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_process(p)
            raise DesktopError('timeout','Live backend timed out; inspect before any retry')
        finally:
            with self.lock:
                if p in self.processes:self.processes.remove(p)
        if p.returncode==6:
            self.cancelled=True
            raise DesktopError('focus_changed','Input-state guard stopped the action; enrollment revoked; effect may be partial')
        require(p.returncode==0,'backend_failed','Live backend rejected the operation; no automatic retry')
        return stdout.decode()

    def run(self,operation,timeout=8):
        require(operation['action'] in ALLOWED,'unsupported_action','Live Revu permits discovery, capture, geometry, click and drag only')
        op=dict(operation,**{k:v for k,v in self.target.items() if k!='native_id'})
        if op['action']=='discover':op['native_id']=self.target['native_id']
        require(op.get('native_id')==self.target['native_id'],'stale_target','Wrong enrolled Revu window')
        def inspect(action):
            value=json.loads(self.command([sys.executable,'-m','lad.live_revu'],dict(op,action=action),timeout))
            if 'error' in value:raise DesktopError(value['error']['code'],value['error']['message'])
            return value
        if op['action'] in ('discover','geometry','screenshot'):return inspect(op['action'])
        g=inspect('geometry')
        keys=('x','y') if op['action']=='click' else ('x','y','end_x','end_y')
        for key in keys:
            require(type(op.get(key)) is int and 0<=op[key]<g['width' if key.endswith('x') else 'height'],
                    'out_of_bounds','Live coordinates must be inside the enrolled window')
        before=inspect('state')
        self.command([str(self.runner/'wine'),str(self.directory/'revu-control.exe'),op['action']]+[str(op[k]) for k in keys],timeout=timeout)
        after=inspect('state')
        if before!=after:
            self.cancelled=True
            raise DesktopError('focus_changed','Host input-state guard changed; enrollment revoked; inspect the document')
        return {'delivered':True,'verified_effect':False,'focus_unchanged':True,'pointer_unchanged':True,
                'scope':'live Revu test window; direct Win32 messages'}

    def close(self):
        with self.lock:
            self.cancelled=True
            for process in list(self.processes):kill_process(process)
            self.processes.clear()


if __name__=='__main__':
    try:result=x11_operation(json.load(sys.stdin))
    except DesktopError as exc:result={'error':{'code':exc.code,'message':str(exc)}}
    except Exception:result={'error':{'code':'backend_failed','message':'Live window inspection failed'}}
    print(json.dumps(result))
