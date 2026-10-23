"""Policy and real-application checks for operator-enrolled Sway targets."""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

import pytest

from lad.errors import DesktopError
from lad.service import DesktopService
from lad.sway import SwayConnection, SwaySession
from conftest import act


def test_no_implicit_desktop(monkeypatch):
    for name in ('LAD_SWAYSOCK','LAD_XDG_RUNTIME_DIR','LAD_WAYLAND_DISPLAY'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(DesktopError, match='explicitly'):
        SwayConnection()


def test_operator_only(service, owner):
    with pytest.raises(DesktopError) as error:
        service.dispatch('operator_enroll_sway', {}, owner)
    assert error.value.code == 'unknown_method'
    with pytest.raises(DesktopError) as error:
        service.enroll_sway(dict(owner=owner, native_id=1, pid=os.getpid(), consent_session=False))
    assert error.value.code == 'permission_denied'


@pytest.fixture
def desktop(monkeypatch):
    if os.environ.get('LAD_TEST_SWAY') != '1':
        pytest.skip('Set LAD_TEST_SWAY=1 for disposable real-app software-rendered tests')
    for binary in ('sway','grim','wtype','mousepad','dbus-daemon'):
        if not shutil.which(binary):
            pytest.fail('Missing integration dependency: '+binary)
    with tempfile.TemporaryDirectory(prefix='lad-smoke-') as name:
        root = Path(name)
        runtime = root / 'runtime'
        runtime.mkdir(mode=0o700)
        home = root / 'home'
        home.mkdir()
        env = dict(PATH=os.defpath, HOME=str(home), XDG_RUNTIME_DIR=str(runtime),
                   XDG_CONFIG_HOME=str(home/'config'), XDG_DATA_HOME=str(home/'data'),
                   XDG_CACHE_HOME=str(home/'cache'), WLR_BACKENDS='headless',
                   WLR_RENDERER='pixman', WLR_LIBINPUT_NO_DEVICES='1',
                   WLR_HEADLESS_OUTPUTS='2', LANG='C.UTF-8', GDK_BACKEND='wayland',
                   WINEDLLOVERRIDES='mscoree,mshtml=', WINEDEBUG='-all',
                   WINEPREFIX=str(root/'wine'))
        processes = []
        log = open(root/'process.log','wb')
        def spawn(argv):
            p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            processes.append(p)
            return p
        bus = subprocess.Popen(['dbus-daemon','--session','--nofork','--print-address=1'],
                               env=env, stdout=subprocess.PIPE, stderr=log, start_new_session=True)
        processes.append(bus)
        env['DBUS_SESSION_BUS_ADDRESS'] = bus.stdout.readline().decode().strip()
        config = root/'sway.conf'
        config.write_text('output * resolution 1280x800\nseat seat0 fallback true\nxwayland force\n'
                          'default_border pixel 1\nfocus_follows_mouse no\n'
                          f'exec /usr/bin/env > {root}/session-env\n')
        compositor = spawn(['sway','-c',str(config)])
        try:
            wait(lambda: list(runtime.glob('sway-ipc.*.sock')) and (root/'session-env').exists())
            session_env = dict(line.split('=',1) for line in (root/'session-env').read_text().splitlines() if '=' in line)
            env.update({k:session_env[k] for k in ('WAYLAND_DISPLAY','DISPLAY','SWAYSOCK') if k in session_env})
            monkeypatch.setenv('LAD_SWAYSOCK', env['SWAYSOCK'])
            monkeypatch.setenv('LAD_XDG_RUNTIME_DIR', str(runtime))
            monkeypatch.setenv('LAD_WAYLAND_DISPLAY', env['WAYLAND_DISPLAY'])
            connection = SwayConnection()
            yield root, env, spawn, connection
        finally:
            if (root/'wine').exists():
                server = shutil.which('wineserver') or next((str(p) for p in (Path('/usr/lib/wine/wineserver64'),Path('/usr/lib/x86_64-linux-gnu/wine/wineserver')) if p.exists()), None)
                if server:
                    subprocess.run([server,'-k'], env=env, capture_output=True, timeout=8)
            for p in reversed(processes):
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGTERM)
                    try:
                        p.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(p.pid, signal.SIGKILL)
                        p.wait(timeout=3)
            log.close()


def wait(condition, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError('Timed out waiting for real application state')


def attach(service, owner, window):
    return service.enroll_sway(dict(owner=owner, native_id=window['native_id'], pid=window['pid'], consent_session=True))['task_id']


def test_real_native_and_failures(desktop, owner):
    root, env, spawn, connection = desktop
    document = root/'scratch.txt'
    document.write_text('')
    app = spawn(['mousepad','--disable-server',str(document)])
    window = wait(lambda: next((w for w in connection.inventory() if w['pid']==app.pid), None))
    service = DesktopService(root/'service')
    try:
        task = attach(service, owner, window)
        target = window['native_id']
        with pytest.raises(DesktopError) as error:
            attach(service, 'other-owner-00000000', window)
        assert error.value.code == 'busy'
        with pytest.raises(DesktopError):
            act(service, 'other-owner-00000000', task, 'geometry', target)
        with pytest.raises(DesktopError) as error:
            act(service, owner, task, 'geometry', target+100000)
        assert error.value.code == 'stale_target'
        # A stale action revokes the enrollment without killing the application.
        assert app.poll() is None
        task = attach(service, owner, window)
        act(service, owner, task, 'focus', target)
        text = 'Real Wayland input: café 123'
        action_id = uuid.uuid4().hex
        params = dict(task_id=task, action_id=action_id, action='type', native_id=target, args={'text':text})
        service.dispatch('act', params, owner)
        assert service.dispatch('act', params, owner)['replayed']
        act(service, owner, task, 'key', target, {'key':'s','modifier':'ctrl'})
        wait(lambda: document.read_text().rstrip('\n') == text)
        geometry = act(service, owner, task, 'geometry', target)['result']
        with pytest.raises(DesktopError) as error:
            act(service, owner, task, 'click', target, {'x':geometry['width'],'y':1})
        assert error.value.code == 'out_of_bounds'
        frame = act(service, owner, task, 'screenshot', target)['result']
        assert base64.b64decode(frame['png']).startswith(b'\x89PNG')
        import io
        from PIL import Image
        pixels = Image.open(io.BytesIO(base64.b64decode(frame['png']))).convert('RGB')
        assert len(pixels.getcolors(1000000)) > 10
        assert frame['width'] == geometry['width']
        # Window geometry changes retain the enrolled container identity.
        connection.ipc(0, f'[con_id={target}] floating enable')
        resized = act(service, owner, task, 'resize', target, {'width':640,'height':480})['result']
        assert resized['width'] > 500
        moved = act(service, owner, task, 'move', target, {'x':100,'y':100})['result']
        assert moved['x'] >= 100
        act(service, owner, task, 'click', target, {'x':100,'y':100})
        act(service, owner, task, 'drag', target, {'x':100,'y':100,'end_x':150,'end_y':100})
        act(service, owner, task, 'scroll', target, {'x':100,'y':100,'steps':1})
        service.dispatch('close_task', {'task_id':task}, owner)
        assert app.poll() is None and document.read_text().rstrip('\n') == text
        # Independent app receives no text during actions on the enrolled target.
        other = root/'sentinel.txt'
        other.write_text('sentinel')
        sentinel = spawn(['mousepad','--disable-server',str(other)])
        sentinel_window = wait(lambda: next((w for w in connection.inventory() if w['pid']==sentinel.pid),None))
        task = attach(service, owner, window)
        act(service, owner, task, 'focus', target)
        connection.ipc(0, f"[con_id={sentinel_window['native_id']}] focus")
        with pytest.raises(DesktopError) as error:
            act(service, owner, task, 'type', target, {'text':'must not reach sentinel'})
        assert error.value.code == 'focus_changed'
        assert other.read_text() == 'sentinel'
        connection.ipc(0, f"[con_id={sentinel_window['native_id']}] focus")
        connection.ipc(0, 'nop')
        from lad.protocol import ROOT
        subprocess.run([str(ROOT/'.local/native/lad-key'),'31','ctrl'],env=env,check=True,timeout=3)
        assert other.read_text().rstrip('\n') == 'sentinel'
        # A helper timeout terminates only owned helpers and revokes the seat.
        task = attach(service, owner, window)
        act(service, owner, task, 'focus', target)
        live = service.tasks[task].session
        with pytest.raises(DesktopError) as error:
            live.helper(['/bin/sleep','5'], time.monotonic()+.05)
        assert error.value.code == 'timeout'
        assert not live.processes
        service.dispatch('cancel_task', {'task_id':task}, owner)
        assert app.poll() is None and sentinel.poll() is None
        # Service-level timeout records unknown effect and releases the grant.
        task = attach(service, owner, window)
        act(service, owner, task, 'focus', target)
        timed_id = uuid.uuid4().hex
        with pytest.raises(DesktopError) as error:
            service.dispatch('act',dict(task_id=task,action_id=timed_id,action='type',native_id=target,
                                       args={'text':'timeout'},timeout=.05),owner)
        assert error.value.code == 'timeout'
        assert service.store.get(timed_id, owner)['status']=='unknown'
        assert service.tasks[task].cancel.is_set() and app.poll() is None
        # Cancellation during real input owns only the helper's process group.
        import concurrent.futures
        task = attach(service, owner, window)
        act(service, owner, task, 'focus', target)
        live = service.tasks[task].session
        cancel_id = uuid.uuid4().hex
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(service.dispatch,'act',dict(task_id=task,action_id=cancel_id,action='type',
                                 native_id=target,args={'text':'x'*4096},timeout=15),owner)
            wait(lambda: bool(live.processes))
            service.dispatch('cancel_task',{'task_id':task},owner)
            with pytest.raises(DesktopError):
                future.result(timeout=5)
        assert service.store.get(cancel_id,owner)['status']=='unknown'
        assert not live.processes and app.poll() is None
        # Lease expiry detaches and permits a new enrollment of the same app.
        task = attach(service, owner, window)
        service.tasks[task].created -= 301
        with pytest.raises(DesktopError):
            act(service, owner, task, 'geometry', target)
        task = attach(service, owner, window)
        live = service.tasks[task].session
        live.connection.identity = (0,0)
        with pytest.raises(DesktopError) as error:
            act(service, owner, task, 'geometry', target)
        assert error.value.code=='stale_target'
        assert app.poll() is None and sentinel.poll() is None
    finally:
        service.close()


def test_real_wine_notepad(desktop, owner):
    root, env, spawn, connection = desktop
    wine = shutil.which('wine64-stable') or shutil.which('wine') or '/usr/lib/wine/wine64'
    if not Path(wine).exists():
        pytest.fail('Wine is required for LAD_TEST_SWAY=1')
    document = root/'wine-scratch.txt'
    document.write_text('')
    spawn([wine,'notepad.exe','Z:'+str(document).replace('/','\\')])
    window = wait(lambda: next((w for w in connection.inventory() if w.get('shell')=='xwayland'
                               and 'wine-scratch' in (w.get('title') or '')),None), timeout=60)
    service = DesktopService(root/'service')
    try:
        task = attach(service, owner, window)
        target = window['native_id']
        act(service, owner, task, 'focus', target)
        text = 'Real Wine Notepad input 123'
        act(service, owner, task, 'type', target, {'text':text})
        act(service, owner, task, 'key', target, {'key':'s','modifier':'ctrl'})
        def saved():
            data = document.read_bytes()
            return data.decode('utf-16' if data.startswith(b'\xff\xfe') else 'utf-8-sig').strip() == text
        wait(saved)
        frame = act(service, owner, task, 'screenshot', target)['result']
        assert frame['width'] > 100 and base64.b64decode(frame['png']).startswith(b'\x89PNG')
        service.dispatch('close_task', {'task_id':task}, owner)
        assert any(w['native_id']==target for w in connection.inventory())
    finally:
        service.close()


def test_live_mcp_and_crash_recovery(desktop, owner):
    import asyncio
    import concurrent.futures
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from lad.protocol import request
    from lad.session import process_start
    root, env, spawn, connection = desktop
    document = root/'mcp-scratch.txt'
    document.write_text('')
    app = spawn(['mousepad','--disable-server',str(document)])
    window = wait(lambda: next((w for w in connection.inventory() if w['pid']==app.pid),None))
    socket_path = root/'service'/'service.sock'
    daemons = []
    def start():
        p = subprocess.Popen([sys.executable,'-m','lad.cli','--socket',str(socket_path),'serve'],
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        daemons.append(p)
        def ready():
            if p.poll() is not None:
                raise AssertionError('Test daemon failed to start')
            try:
                return request('capabilities', owner=owner,path=socket_path).get('ok')
            except OSError:
                return False
        wait(ready)
        return p
    def enroll():
        value = request('operator_enroll_sway',dict(owner=owner,native_id=window['native_id'],
                        pid=window['pid'],consent_session=True),owner=owner,path=socket_path)
        assert value['ok'],value
        return value['data']['task_id']
    try:
        daemon = start()
        task = enroll()
        target = window['native_id']
        async def check_mcp():
            params = StdioServerParameters(command=sys.executable,args=['-m','lad.mcp_server'],
                                           env={**os.environ,'LAD_SOCKET':str(socket_path),'LAD_CLIENT_ID':owner})
            async with stdio_client(params) as (r,w):
                async with ClientSession(r,w) as client:
                    await client.initialize()
                    tools = {t.name for t in (await client.list_tools()).tools}
                    assert 'operator_enroll_sway' not in tools
                    tasks = await client.call_tool('desktop_tasks',{})
                    assert tasks.structuredContent['tasks'][0]['task_id']==task
                    for action,args in [('focus',{}),('type',{'text':'MCP real application 123'}),('key',{'key':'s','modifier':'ctrl'})]:
                        response = await client.call_tool('desktop_action',dict(task_id=task,action_id=uuid.uuid4().hex,
                                                     native_id=target,action=action,args=args))
                        assert not response.isError,response
                    wait(lambda: document.read_text().rstrip('\n')=='MCP real application 123')
                    frame = await client.call_tool('desktop_screenshot',dict(task_id=task,action_id=uuid.uuid4().hex,native_id=target))
                    assert not frame.isError and frame.content[0].type=='image'
        asyncio.run(check_mcp())
        ident = uuid.uuid4().hex
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(request, 'act', dict(task_id=task, action_id=ident, action='type',native_id=target,
                                  args={'text':'x'*4096},timeout=15),owner=owner,path=socket_path)
            manifest = socket_path.parent/('task-'+task)/'processes.json'
            entries = wait(lambda: json.loads(manifest.read_text()) if manifest.exists() else None)
            daemon.kill()
            daemon.wait(timeout=5)
            try:
                future.result(timeout=5)
            except (OSError,ValueError):
                pass
        start()
        result = request('result',{'action_id':ident},owner=owner,path=socket_path)
        assert result['data']['status']=='interrupted'
        assert request('list_tasks',owner=owner,path=socket_path)['data']['tasks']==[]
        for entry in entries:
            stat_path = Path(f"/proc/{entry['pid']}/stat")
            if stat_path.exists() and process_start(entry['pid'])==entry['start']:
                assert stat_path.read_text().rsplit(')',1)[1].split()[0]=='Z'
        assert app.poll() is None
        assert enroll() != task
    finally:
        for p in daemons:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=10)
