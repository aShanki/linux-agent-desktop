"""Explicit, expiring attachment to a dedicated Sway session.

Sway routes input through a seat, not directly to a surface. Enrollment grants
exclusive use of that session's seat and visible capture, including overlays.
Never infer consent from the service's inherited desktop environment.
"""
import base64
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import threading
import time

from .errors import DesktopError, require
from .session import process_start, kill_process


def walk(node):
    yield node
    for child in node.get('nodes', []) + node.get('floating_nodes', []):
        yield from walk(child)


class SwayConnection:
    def __init__(self):
        values = [os.environ.get(k) for k in ('LAD_SWAYSOCK', 'LAD_XDG_RUNTIME_DIR', 'LAD_WAYLAND_DISPLAY')]
        require(all(values), 'not_configured', 'Set LAD_SWAYSOCK, LAD_XDG_RUNTIME_DIR and LAD_WAYLAND_DISPLAY explicitly')
        self.path, runtime, display = map(Path, values)
        require(self.path.is_absolute() and runtime.is_absolute() and not display.is_absolute()
                and len(display.parts) == 1, 'unsafe_target', 'Use absolute IPC/runtime paths and a Wayland socket basename')
        require(runtime.is_dir() and runtime.stat().st_uid == os.getuid() and runtime.stat().st_mode & 0o077 == 0,
                'unsafe_runtime', 'Configured Wayland runtime must be private and owned by the service user')
        self.display = runtime / display
        self.env = {'PATH': os.defpath, 'LANG':'C.UTF-8', 'XDG_RUNTIME_DIR': str(runtime), 'WAYLAND_DISPLAY': str(display)}
        self.identity = self.socket_identity(self.path)
        self.display_identity = self.socket_identity(self.display)
        self.peer = self.peer_identity(self.path)
        require(self.peer == self.peer_identity(self.display), 'unsafe_target', 'IPC and Wayland sockets must belong to the same compositor')
        require('human_readable' in self.ipc(7), 'unsupported_backend', 'Configured IPC is not Sway')

    @staticmethod
    def socket_identity(path):
        try:
            info = path.lstat()
        except OSError:
            raise DesktopError('target_gone', 'Configured compositor socket is unavailable')
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid(), 'unsafe_target', 'Compositor socket must be owned by the service user')
        return info.st_dev, info.st_ino

    @staticmethod
    def peer_identity(path):
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(2)
            sock.connect(str(path))
            pid, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        require(uid == os.getuid() and process_start(pid), 'unsafe_target', 'Compositor peer must be a live process owned by the service user')
        return pid, process_start(pid)

    def check(self):
        require(self.identity == self.socket_identity(self.path)
                and self.display_identity == self.socket_identity(self.display)
                and self.peer == self.peer_identity(self.path)
                and self.peer == self.peer_identity(self.display), 'stale_target', 'Compositor session changed; enroll again')

    def ipc(self, kind, payload='', timeout=2):
        self.check()
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(timeout)
                sock.connect(str(self.path))
                require(struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0] == self.peer[0],
                        'stale_target', 'Compositor peer changed')
                data = payload.encode()
                sock.sendall(b'i3-ipc' + struct.pack('<II', len(data), kind) + data)
                def receive(size):
                    value = bytearray()
                    while len(value) < size:
                        chunk = sock.recv(size - len(value))
                        require(bool(chunk), 'backend_failed', 'Compositor disconnected')
                        value.extend(chunk)
                    return bytes(value)
                header = receive(14)
                size, response = struct.unpack('<II', header[6:])
                require(header[:6] == b'i3-ipc' and response == kind and size <= 8 * 1024 * 1024,
                        'backend_failed', 'Invalid compositor response')
                return json.loads(receive(size))
        except (OSError, ValueError):
            raise DesktopError('backend_failed', 'Sway IPC failed; inspect before retrying writes')

    def inventory(self):
        return [self.describe(n) for n in walk(self.ipc(4)) if n.get('pid') and n.get('type') == 'con']

    @staticmethod
    def describe(node):
        return dict(native_id=node['id'], pid=node['pid'], title=node.get('name'),
                    app_id=node.get('app_id'), shell=node.get('shell'),
                    coordinate_space='input: window content logical pixels; rectangle: outer container', **node['rect'])


class SwaySession:
    kind = 'sway-live'

    def __init__(self, directory, native_id, pid, connection=None):
        require(type(native_id) is int and native_id > 0 and type(pid) is int and pid > 0,
                'invalid_argument', 'Supply exact positive window and PID identifiers')
        self.connection = connection or SwayConnection()
        self.native_id, self.pid = native_id, pid
        seats = self.connection.ipc(101)
        require(len(seats) == 1 and seats[0].get('name') == 'seat0', 'unsupported_backend', 'Live attachment requires exactly one Sway seat named seat0')
        self.start = process_start(pid)
        require(self.start is not None and Path(f'/proc/{pid}').stat().st_uid == os.getuid(),
                'unsafe_target', 'Target process must be owned by the service user')
        self.cancelled = threading.Event()
        self.lifecycle = threading.RLock()
        self.execution = threading.RLock()
        self.processes = []
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700)
        self.lockfile = None
        self.button_down = False
        try:
            self.target()
            # A single seat lease across service roots prevents two grants from
            # routing input to different windows on the same compositor.
            lockroot = self.connection.display.parent / 'lad-seat-locks'
            lockroot.mkdir(mode=0o700, exist_ok=True)
            require(not lockroot.is_symlink() and lockroot.stat().st_uid == os.getuid()
                    and lockroot.stat().st_mode & 0o077 == 0, 'unsafe_runtime', 'Unsafe seat lock directory')
            key = hashlib.sha256(repr(self.connection.peer).encode()).hexdigest()
            fd = os.open(lockroot / key, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            self.lockfile = os.fdopen(fd, 'a')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.lockfile.close()
                self.lockfile = None
                raise DesktopError('busy', 'Another enrollment owns this compositor seat')
            self.seat_manifest = self.directory / 'seat.json'
            self.seat_manifest.write_text(json.dumps({'peer':self.connection.peer, 'lock':str(lockroot / key)}))
        except Exception:
            self.close()
            try:
                self.directory.rmdir()
            except OSError:
                pass
            raise

    @staticmethod
    def recover(directory):
        manifest = directory / 'seat.json'
        record = json.loads(manifest.read_text())
        peer = record['peer']
        if process_start(peer[0]) == peer[1]:
            connection = SwayConnection()
            require(list(connection.peer) == peer, 'recovery_failed', 'Configure the previously enrolled compositor before recovery')
            lockroot = connection.display.parent / 'lad-seat-locks'
            key = hashlib.sha256(repr(connection.peer).encode()).hexdigest()
            require(str(lockroot / key) == record['lock'], 'recovery_failed', 'Seat lock identity changed')
            fd = os.open(lockroot / key, os.O_RDWR | os.O_NOFOLLOW)
            with os.fdopen(fd, 'a') as lockfile:
                try:
                    fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise DesktopError('recovery_failed', 'Another enrollment owns the previous seat')
                result = connection.ipc(0, 'seat seat0 cursor release button1')
                require(result and all(r.get('success') for r in result), 'recovery_failed', 'Could not release interrupted pointer input')
        manifest.unlink()

    def target(self):
        require(not self.cancelled.is_set(), 'cancelled', 'Enrollment was revoked')
        require(process_start(self.pid) == self.start, 'stale_target', 'Target process exited or PID was reused')
        tree = self.connection.ipc(4)
        nodes = list(walk(tree))
        matches = [n for n in nodes if n.get('id') == self.native_id and n.get('pid') == self.pid]
        require(len(matches) == 1, 'stale_target', 'Enrolled window was closed or replaced')
        return matches[0], nodes

    def command(self, value, deadline):
        require(not self.cancelled.is_set(), 'cancelled', 'Enrollment was revoked')
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'timeout', 'Action timed out; effect may have occurred')
        result = self.connection.ipc(0, value, min(2, remaining))
        require(result and all(r.get('success') for r in result), 'backend_failed', 'Sway rejected the operation; inspect the target')

    def helper(self, argv, deadline):
        with self.lifecycle:
            require(not self.cancelled.is_set(), 'cancelled', 'Enrollment was revoked')
            p = subprocess.Popen(argv, env=self.connection.env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            self.processes.append(p)
            # Recovery owns helpers only, never the attached app or compositor.
            self.save_processes()
        try:
            while True:
                try:
                    output, _ = p.communicate(timeout=min(.02, max(.001, deadline-time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise
                    try:
                        self.focused()
                    except DesktopError:
                        kill_process(p)
                        raise
            require(not self.cancelled.is_set(), 'cancelled', 'Enrollment was revoked; effect may have occurred')
            require(p.returncode == 0, 'backend_failed', 'Wayland helper failed; required protocol may be unavailable')
            return output
        except subprocess.TimeoutExpired:
            kill_process(p)
            raise DesktopError('timeout', 'Action timed out; effect may have occurred')
        finally:
            with self.lifecycle:
                if p in self.processes:
                    self.processes.remove(p)
                self.save_processes()

    def save_processes(self):
        manifest = self.directory / 'processes.json'
        temporary = manifest.with_suffix('.tmp')
        temporary.write_text(json.dumps([{'pid':p.pid, 'start':process_start(p.pid)} for p in self.processes if p.poll() is None]))
        temporary.replace(manifest)

    def focused(self):
        node, _ = self.target()
        require(node.get('focused'), 'focus_changed', 'Focus left the enrolled window; effect may have occurred')
        return node

    @staticmethod
    def content(node):
        rect, inner = node['rect'], node['window_rect']
        return dict(x=rect['x']+inner['x'], y=rect['y']+inner['y'], width=inner['width'], height=inner['height'])

    def run(self, operation, timeout=8):
        with self.execution:
            return self._run(operation, timeout)

    def _run(self, operation, timeout=8):
        deadline = time.monotonic() + timeout
        node, nodes = self.target()
        action = operation['action']
        if action == 'discover':
            return {'windows': [self.connection.describe(node)]}
        require(operation.get('native_id') == self.native_id, 'stale_target', 'Use the enrolled window ID')
        rect = self.content(node)
        if action == 'geometry':
            return dict(rect, native_id=self.native_id, coordinate_space='window content logical pixels')
        require(action in ('screenshot','focus','move','resize','click','drag','scroll','type','key'),
                'unsupported_action', 'Sway attachment supports visible capture, window management and seat input only')
        # Commands interpolate only validated numeric values or fixed vocabulary.
        prefix = f'[con_id={self.native_id}] '
        if action in ('move','resize'):
            fields = ('x','y') if action == 'move' else ('width','height')
            values = [operation.get(k) for k in fields]
            require(all(type(v) is int and 0 <= v <= 16384 for v in values)
                    and (action != 'resize' or min(values) >= 32), 'invalid_argument', 'Window coordinates/sizes must be bounded integers')
            require(node.get('floating') in ('user_on','auto_on'), 'unsupported_action', 'Move/resize requires an already floating window')
            verb = 'move position' if action == 'move' else 'resize set'
            self.command(prefix + f'{verb} {values[0]} px {values[1]} px', deadline)
            return {'delivered':True, 'verified_effect':False, **self.content(self.target()[0])}
        require(rect['width'] > 0 and rect['height'] > 0, 'not_viewable', 'Window has no content area')
        # Focus is an explicit part of the operator's session grant. Do not
        # silently switch focus for typing or capture.
        if action == 'focus':
            self.command(prefix + 'focus', deadline)
            self.focused()
            return {'delivered':True, 'verified_effect':True, 'session_focus_changed':True}
        self.focused()
        if action == 'screenshot':
            # This is visible-region capture, not occlusion-independent capture.
            # The operator grants capture of overlays in this dedicated session.
            require(rect['width'] * rect['height'] <= 16000000, 'unsupported_action', 'Visible capture is limited to 16 million logical pixels')
            data = self.helper(['grim','-s','1','-g',f"{rect['x']},{rect['y']} {rect['width']}x{rect['height']}",'-'], deadline)
            after = self.focused()
            require(self.content(after) == rect, 'stale_target', 'Window moved during capture; image discarded')
            from PIL import Image
            image = Image.open(io.BytesIO(data))
            require(image.size == (rect['width'],rect['height']), 'capture_failed', 'Unexpected capture dimensions')
            return dict(png=base64.b64encode(data).decode(), width=image.width, height=image.height,
                        scale=1, capture_scope='visible region; may contain session overlays', host_input_isolated=False)
        if action in ('type','key'):
            if action == 'type':
                text = operation.get('text')
                require(isinstance(text,str) and 0 < len(text) <= 4096 and '\0' not in text,
                        'invalid_argument', 'Text must contain 1–4096 non-NUL characters')
                if text.isascii():
                    require(all(c.isprintable() or c in '\n\t' for c in text), 'unsupported_text', 'ASCII control characters are unsupported')
                    from .protocol import ROOT
                    helper = ROOT / '.local/native/lad-key'
                    require(helper.is_file(), 'missing_dependency', 'Run scripts/build-sway-helper.sh')
                    argv = [str(helper),'--text',text]
                else:
                    require(node.get('shell') != 'xwayland', 'unsupported_text', 'Wine/Xwayland text currently requires ASCII; Unicode is unvalidated')
                    argv = ['wtype','-s','100','--',text]
            else:
                keys = {'Return':28,'Tab':15,'Escape':1,'BackSpace':14,'Delete':111,
                        'Left':105,'Right':106,'Up':103,'Down':108,'Home':102,'End':107,
                        'a':30,'s':31,'z':44,'c':46,'v':47}
                key = operation.get('key')
                require(key in keys, 'unsupported_key', 'Key is outside the supported key subset')
                modifier = operation.get('modifier','none')
                require(modifier in ('none','ctrl','shift','alt'), 'invalid_argument', 'Unsupported modifier')
                from .protocol import ROOT
                helper = ROOT / '.local/native/lad-key'
                require(helper.is_file(), 'missing_dependency', 'Run scripts/build-sway-helper.sh for standard-keymap shortcuts')
                argv = [str(helper),str(keys[key]),modifier]
            self.helper(argv, deadline)
        else:
            x,y = operation.get('x'),operation.get('y')
            require(all(type(v) in (int,float) and math.isfinite(v) for v in (x,y))
                    and 0 <= x < rect['width'] and 0 <= y < rect['height'], 'out_of_bounds', 'Input must lie inside enrolled content')
            end = (operation.get('end_x'),operation.get('end_y')) if action == 'drag' else (x,y)
            require(all(type(v) in (int,float) and math.isfinite(v) for v in end)
                    and 0 <= end[0] < rect['width'] and 0 <= end[1] < rect['height'], 'out_of_bounds', 'Drag must end inside enrolled content')
            if action == 'scroll':
                steps = operation.get('steps',1)
                require(type(steps) is int and 0 < abs(steps) <= 20, 'invalid_argument', 'Scroll steps must be within 20')
            self.command(f"seat seat0 cursor set {int(rect['x']+x)} {int(rect['y']+y)}", deadline)
            try:
                if action == 'scroll':
                    button = 'button5' if steps > 0 else 'button4'
                    for _ in range(abs(steps)):
                        self.focused()
                        self.command(f'seat seat0 cursor press {button}', deadline)
                else:
                    self.focused()
                    self.button_down = True
                    self.command('seat seat0 cursor press button1', deadline)
                    if action == 'drag':
                        for i in range(1,11):
                            self.focused()
                            require(self.content(self.target()[0]) == rect, 'stale_target', 'Window moved during gesture')
                            self.command(f"seat seat0 cursor set {int(rect['x']+x+(end[0]-x)*i/10)} {int(rect['y']+y+(end[1]-y)*i/10)}", deadline)
            finally:
                require(self.release_button(), 'backend_failed', 'Pointer release failed; inspect before retrying')
        self.focused()
        return {'delivered':True, 'verified_effect':False, 'host_input_isolated':False,
                'input_scope':'operator-enrolled Sway session seat; focus/pointer may change'}

    def release_button(self):
        if self.button_down:
            try:
                result = self.connection.ipc(0, 'seat seat0 cursor release button1')
                if not result or not all(r.get('success') for r in result):
                    return False
            except (DesktopError,OSError):
                return False
            self.button_down = False
        return True

    def close(self):
        self.cancelled.set()
        with self.lifecycle:
            processes = list(self.processes)
        for p in processes:
            kill_process(p)
        with self.execution:
            released = self.release_button()
            if self.lockfile:
                self.lockfile.close()
                self.lockfile = None
                if released and hasattr(self, 'seat_manifest'):
                    self.seat_manifest.unlink(missing_ok=True)
