import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from lad.cursor_state import activity, is_active, project_point
from lad.session import Session


def test_cursor_projection_tracks_move_resize_and_rejects_invalid_target():
    point = {'x': .25, 'y': .5, 'space': 'normalized'}
    assert project_point((100, 200, 800, 600), point) == (300, 500)
    assert project_point((700, 50, 1200, 800), point) == (1000, 450)
    assert project_point((0, 0, 50, 50), {'x': 80, 'y': 20}) is None
    assert project_point((0, 0, 50, 50), {'x': float('nan'), 'y': 20}) is None
    assert project_point((0, 0, 50, 50), {'space': 'desktop'}) is None


def test_activity_hides_on_error_and_expired_heartbeat(tmp_path):
    path = tmp_path / 'cursor.json'
    with pytest.raises(RuntimeError):
        with activity(path, 20, 30):
            state = json.loads(path.read_text())
            assert is_active(state)
            assert not is_active(state, state['heartbeat'] + 3)
            raise RuntimeError('cancelled action')
    assert not is_active(json.loads(path.read_text()))
    assert not is_active({'active': True})
    assert path.stat().st_mode & 0o077 == 0


def test_kwin_tracker_follows_real_window_move_and_resize(tmp_path):
    session = Session(tmp_path / 'native', 'wayland-qt')
    try:
        target = session.run({'action': 'discover'})['windows'][0]['native_id']
        code = '''import json,time
from pathlib import Path
from gi.repository import GLib
from lad.window_tracker import WindowTracker
t = WindowTracker(TARGET, Path(DIRECTORY))
try:
 end=time.monotonic()+3
 while not t.geometry and time.monotonic()<end:time.sleep(.02)
 assert t.geometry
 before=t.geometry.copy()
 p=Path(DIRECTORY)/'move.js'
 p.write_text('var ws=workspace.stackingOrder;for(var i=0;i<ws.length;i++){if(ws[i].internalId.toString()===TARGET_JSON){ws[i].frameGeometry={x:125,y:150,width:900,height:650};}}'.replace('TARGET_JSON',json.dumps(TARGET)))
 ident=t.call('/Scripting','org.kde.kwin.Scripting','loadScript',GLib.Variant('(ss)',(str(p),'cursor-test-move')))
 t.call('/Scripting/Script'+str(ident),'org.kde.kwin.Script','run')
 end=time.monotonic()+3
 while time.monotonic()<end:
  if t.geometry['x']==125 and t.geometry['width']==900:break
  time.sleep(.02)
 assert t.geometry['x']==125 and t.geometry['width']==900
 assert t.geometry['height']!=before['height']
 print('tracked')
finally:t.close()
'''.replace('TARGET', repr(target)).replace('DIRECTORY', repr(str(session.directory)))
        # Keep the embedded JavaScript marker distinct from Python substitutions.
        code = code.replace(repr(target) + '_JSON', 'TARGET_JSON')
        process = session.spawn([sys.executable, '-c', code], stdout=subprocess.PIPE)
        out, _ = process.communicate(timeout=10)
        assert process.returncode == 0, 'Tracker failed; inspect the private test log'
        assert out.strip() == b'tracked'
    finally:
        session.close()


def test_overlay_keeps_one_click_through_window_while_activity_changes(tmp_path):
    from lad.session import kill_process
    native = Session(tmp_path / 'native-ui', 'wayland-qt')
    x11 = Session(tmp_path / 'x11-ui', 'qt')
    overlay = None
    try:
        target = native.run({'action': 'discover'})['windows'][0]['native_id']
        state, ready = tmp_path / 'cursor.json', tmp_path / 'ready.json'
        state.write_text(json.dumps(dict(active=False, x=80, y=140)))
        env = dict(native.env, DISPLAY=x11.env['DISPLAY'], XAUTHORITY=x11.env['XAUTHORITY'], QT_QPA_PLATFORM='xcb')
        overlay = subprocess.Popen([sys.executable, '-m', 'lad.live_cursor', '--window-id', target,
                                    '--pid', str(native.app.pid), '--state', str(state), '--ready', str(ready)],
                                   env=env, stdout=subprocess.DEVNULL, stderr=native.log, start_new_session=True)
        end = time.monotonic() + 4
        while not ready.exists() and time.monotonic() < end:
            time.sleep(.02)
        ident = json.loads(ready.read_text())['window_id']
        code = '''from Xlib import display,X
from Xlib.ext import shape
import json
D=display.Display();w=D.create_resource_object('window',__WINDOW_ID__)
p=w.get_full_property(D.intern_atom('_NET_WM_WINDOW_OPACITY'),X.AnyPropertyType)
s=w.get_full_property(D.intern_atom('_KDE_NET_WM_SHADOW'),X.AnyPropertyType)
print(json.dumps({'opacity':int(p.value[0]) if p else -1,'input':len(w.shape_get_rectangles(shape.SK.Input).rectangles),'shadow':s is not None,'shape':len(w.shape_get_rectangles(shape.SK.Bounding).rectangles)}))
'''.replace('__WINDOW_ID__', str(ident))
        def inspect():
            return json.loads(subprocess.check_output([sys.executable, '-c', code], env=x11.env))
        inactive = inspect()
        assert inactive['opacity'] == 0 and inactive['input'] == 0
        assert inactive['shadow'] is False and inactive['shape'] > 1
        with activity(state, 80, 140):
            end = time.monotonic() + 2
            while time.monotonic() < end:
                active = inspect()
                if active['opacity'] > 0:
                    break
                time.sleep(.02)
            assert 0 < active['opacity'] < 0xffffffff and active['input'] == 0
        end = time.monotonic() + 2
        while inspect()['opacity'] and time.monotonic() < end:
            time.sleep(.02)
        assert inspect()['opacity'] == 0
        assert overlay.poll() is None
        assert json.loads(ready.read_text())['window_id'] == ident
    finally:
        kill_process(overlay)
        x11.close()
        native.close()


def test_motion_eases_and_retargeting_is_continuous():
    from lad.cursor_state import Motion
    motion = Motion((0, 0))
    motion.move((100, 200), 1)
    assert motion.position(1) == (0, 0)
    assert motion.position(1.11) == pytest.approx((50, 100))
    previous = motion.position(1.12)
    motion.move((200, 300), 1.12)
    assert motion.position(1.12) == previous
    assert motion.position(2) == (200, 300)


def test_activity_move_and_click_are_explicit_events(tmp_path):
    path = tmp_path / 'events.json'
    with activity(path, 10, 20) as cursor:
        cursor.move(30, 40)
        cursor.click()
        state = json.loads(path.read_text())
        assert (state['x'], state['y'], state['click_seq']) == (30, 40, 1)
    assert not json.loads(path.read_text())['active']
