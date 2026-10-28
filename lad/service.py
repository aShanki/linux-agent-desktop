"""Provider-neutral daemon for isolated fixtures and explicit live application grants."""
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import shutil
import tempfile
import socket
import socketserver
import sqlite3
import struct
import threading
import time
import uuid
from pathlib import Path
from .errors import DesktopError, require
from . import __version__
from .protocol import read_message, DEFAULT_SOCKET
from .session import Session
from .observer import Observer

READS = {'discover', 'geometry', 'screenshot', 'tree'}
WRITES = {'focus', 'move', 'resize', 'click', 'type', 'key', 'scroll', 'drag', 'set_text', 'invoke', 'dialog'}
PARAMETERS = {'focus': set(), 'move': {'x', 'y'}, 'resize': {'width', 'height'}, 'discover': set(), 'geometry': set(), 'screenshot': set(), 'tree': set(),
              'click': {'x', 'y', 'hold_ms'}, 'type': {'text'}, 'key': {'key', 'modifier', 'hold_ms'},
              'scroll': {'x', 'y', 'steps'}, 'drag': {'x', 'y', 'end_x', 'end_y'},
              'set_text': {'element', 'text'}, 'invoke': {'element', 'name'}, 'dialog': {'accept'}}


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, task TEXT, owner TEXT, action TEXT, digest TEXT, status TEXT, result TEXT, created REAL)')
        self.db.execute("UPDATE actions SET status='interrupted', result=? WHERE status='running'",
                        (json.dumps({'code': 'interrupted', 'message': 'Service restarted; effect may have occurred. Inspect before retrying.'}),))
        self.db.commit()

    def get(self, ident, owner):
        with self.lock:
            row = self.db.execute('SELECT task,owner,action,digest,status,result,created FROM actions WHERE id=?', (ident,)).fetchone()
        require(row is not None and row[1] == owner, 'not_found', 'Action is not owned by this client')
        return {'action_id': ident, 'task_id': row[0], 'action': row[2], 'digest': row[3],
                'status': row[4], 'summary': json.loads(row[5]), 'created': row[6]}

    def start(self, ident, task, owner, action, digest):
        with self.lock:
            try:
                self.db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)',
                                (ident, task, owner, action, digest, 'running', '{}', time.time()))
                self.db.commit()
                return None
            except sqlite3.IntegrityError:
                return self.get(ident, owner)

    def finish(self, ident, status, summary):
        with self.lock:
            self.db.execute('UPDATE actions SET status=?,result=? WHERE id=?', (status, json.dumps(summary), ident))
            self.db.commit()


class Task:
    def __init__(self, owner, session, ttl=1800):
        self.owner, self.session = owner, session
        self.lock = threading.Lock()
        self.created = time.time()
        self.ttl = ttl
        self.cancel = threading.Event()


class DesktopService:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(not self.root.is_symlink() and self.root.stat().st_uid == os.getuid(), 'unsafe_runtime', 'Runtime directory must be owned by the current user')
        require(self.root.stat().st_mode & 0o077 == 0, 'unsafe_runtime', 'Runtime directory must have mode 0700')
        self.lockfile = open(self.root / 'service.lock', 'a')
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DesktopError('already_running', 'A service already owns this runtime directory')
        self._recover_processes()
        self.store = Store(self.root / 'actions.sqlite3')
        os.chmod(self.root / 'actions.sqlite3', 0o600)
        self.observer = Observer()
        self.tasks = {}
        self.lock = threading.RLock()
        self.digest_key = secrets.token_bytes(32)
        self.stop = threading.Event()
        self.reaper = threading.Thread(target=self._reap, daemon=True)
        self.reaper.start()

    def _recover_processes(self):
        # Only manifests inside this service's runtime and matching PID start times.
        from .session import process_start
        for manifest in self.root.glob('task-*/processes.json'):
            try:
                entries = json.loads(manifest.read_text())
                for entry in reversed(entries):
                    pid = entry['pid']
                    try:
                        if process_start(pid) == entry['start'] and os.getpgid(pid) == pid:
                            os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        continue
                # SIGKILL delivery is asynchronous. Do not advertise a recovered
                # service while an old owned worker can still run. Zombies have
                # already stopped and must be reaped by their current parent.
                def still_running(entry):
                    try:
                        fields = Path(f"/proc/{entry['pid']}/stat").read_text().rsplit(')', 1)[1].split()
                        return fields[19] == entry['start'] and fields[0] != 'Z'
                    except (FileNotFoundError, ProcessLookupError):
                        return False
                deadline = time.monotonic() + 3
                while any(still_running(entry) for entry in entries):
                    require(time.monotonic() < deadline, 'recovery_failed',
                            'Owned processes have not stopped; recovery cannot safely continue')
                    time.sleep(.01)
                runtime=manifest.parent/'runtime'
                if runtime.is_symlink():
                    target=runtime.resolve()
                    if target.parent==Path(tempfile.gettempdir()) and target.name.startswith('lad-wayland-') and target.exists() and target.stat().st_uid==os.getuid():
                        shutil.rmtree(target)
                        runtime.unlink()
                manifest.unlink()
            except (OSError, ValueError, KeyError):
                continue

        for manifest in self.root.glob('task-*/seat.json'):
            from .sway import SwaySession
            SwaySession.recover(manifest.parent)

    def _reap(self):
        while not self.stop.wait(5):
            with self.lock:
                expired = [t for t in self.tasks.values() if time.time()-t.created > t.ttl]
            for task in expired:
                task.cancel.set()
                task.session.close()

    def get_task(self, ident, owner):
        with self.lock:
            task = self.tasks.get(ident)
        require(task is not None and task.owner == owner, 'not_found', 'Task is not owned by this client or expired after restart')
        if time.time()-task.created > task.ttl:
            task.cancel.set()
            task.session.close()
        require(not task.cancel.is_set(), 'cancelled', 'Task has been cancelled or expired')
        return task

    def dispatch(self, method, params, owner):
        require(isinstance(owner, str) and re.fullmatch(r'[a-zA-Z0-9_-]{16,128}', owner), 'invalid_owner', 'Client identity is invalid')
        require(isinstance(params, dict), 'invalid_argument', 'Parameters must be an object')
        if method == 'capabilities':
            return {'version': __version__, 'scope': 'isolated fixtures; operator-enrolled Sway session targets and Revu test document',
                    'backends': {'x11': 'XSendEvent + XGetImage; application-dependent event acceptance',
                                 'atspi': 'owned PID on private D-Bus; toolkit-dependent',
                                 'browser': 'owned headless fixture via CDP',
                                 'wayland': 'private KWin: window capture, EIS input and AT-SPI; no host compositor input',
                                 'sway-live': 'explicit dedicated-session grant: native Wayland and Wine/Xwayland input, visible capture, floating window move/resize; session focus/pointer may change',
                                 'wine': 'Revu sample document: window capture and guarded direct Win32 click/drag, opt-in enrollment required'},
                    'forbidden': ['unenrolled live desktop', 'foreground fallback', 'credentials', 'external', 'destructive'],
                    'sway_attachment': {
                        'configured': all(os.environ.get(k) for k in ('LAD_SWAYSOCK','LAD_XDG_RUNTIME_DIR','LAD_WAYLAND_DISPLAY')),
                        'requires': 'operator grant for an exclusively controlled dedicated Sway session with seat0',
                        'capture': 'visible region including overlays; not occlusion independent',
                        'unsupported': ['other host compositors','multiple seats','Wine Unicode','semantic actions']},
                    'task_ttl_seconds': 1800, 'live_task_ttl_seconds': 300, 'max_tasks': 6}
        if method == 'list_tasks':
            with self.lock:
                return {'tasks':[{'task_id':ident,'kind':t.session.kind,'active':not t.cancel.is_set(),
                                  'expires_in':max(0,round(t.created+t.ttl-time.time()))}
                                 for ident,t in self.tasks.items() if t.owner==owner]}
        if method == 'open_task':
            require(set(params) <= {'kind', 'scale', 'outputs'}, 'invalid_argument', 'Unknown task parameter')
            kind, scale = params.get('kind', 'qt'), params.get('scale', 1)
            require(kind in ('qt', 'gtk', 'browser', 'wayland-qt', 'wayland-gtk', 'wayland-canvas'), 'unsupported_backend', 'Only qt, gtk, browser, wayland-qt, and wayland-gtk and wayland-canvas fixtures may be launched')
            require(type(scale) in (int, float) and scale in (1, 1.5, 2), 'invalid_argument', 'Scale must be 1, 1.5, or 2')
            outputs = params.get('outputs',1)
            require(type(outputs) is int and outputs in (1,2) and (outputs==1 or kind.startswith('wayland-')),
                    'invalid_argument','Two outputs are supported only for private Wayland tasks')
            with self.lock:
                require(sum(not t.cancel.is_set() for t in self.tasks.values()) < 6, 'capacity', 'Task limit reached; close a task')
                ident = uuid.uuid4().hex
                session = Session(self.root / ('task-'+ident), kind, scale, outputs)
                self.tasks[ident] = Task(owner, session)
                if len(self.tasks) > 64:
                    for old_id, old_task in list(self.tasks.items()):
                        if old_task.cancel.is_set():
                            del self.tasks[old_id]
                            break
            self.observer.event(ident, kind, 'open', status='ready',
                                actor='Claude' if owner.startswith('claude') else 'Codex' if owner.startswith('codex') else 'Agent')
            self.capture(ident, self.tasks[ident])
            return {'task_id': ident, 'kind': kind, 'scale': scale, 'outputs':outputs, 'isolated': True,
                    'permission': 'test fixture only; no live desktop access', 'expires_in': 1800}
        if method in ('cancel_task', 'close_task'):
            with self.lock:
                task = self.tasks.get(params.get('task_id'))
            require(task is not None and task.owner == owner, 'not_found', 'Task is not owned by this client')
            task.cancel.set()
            task.session.close()
            self.observer.event(params.get('task_id'), task.session.kind, 'close', status='cancelled')
            return {'cancelled': True}
        if method == 'result':
            value = self.store.get(params.get('action_id'), owner)
            value.pop('digest')
            return value
        if method == 'act':
            return self.act(params, owner)
        raise DesktopError('unknown_method', 'Unknown service method')

    def enroll_sway(self, params):
        require(set(params) == {'owner','native_id','pid','consent_session'}, 'invalid_argument', 'Supply owner, exact native_id/PID and session consent')
        owner = params['owner']
        require(isinstance(owner,str) and re.fullmatch(r'[a-zA-Z0-9_-]{16,128}',owner), 'invalid_owner', 'A valid client owner is required')
        require(params['consent_session'] is True, 'permission_denied', 'Operator must grant exclusive session input and visible capture')
        from .sway import SwaySession
        with self.lock:
            require(sum(not t.cancel.is_set() for t in self.tasks.values()) < 6, 'capacity', 'Task limit reached')
            ident = uuid.uuid4().hex
            session = SwaySession(self.root / ('task-'+ident), params['native_id'], params['pid'])
            self.tasks[ident] = Task(owner, session, ttl=300)
            if len(self.tasks) > 64:
                old = next((key for key,value in self.tasks.items() if value.cancel.is_set()),None)
                if old is not None:
                    del self.tasks[old]
        # Do not capture at enrollment. The operator-selected target may be covered.
        return {'task_id':ident, 'kind':session.kind, 'native_id':session.native_id,
                'expires_in':300, 'isolated':False,
                'permission':'exclusive Sway session input and visible-region capture; detach never closes the app'}

    def enroll_revu(self, owner):
        # Explicit operator-only entry point; never exposed as an MCP attachment tool.
        require(isinstance(owner,str) and re.fullmatch(r'[a-zA-Z0-9_-]{16,128}',owner),
                'invalid_owner','A valid client owner is required')
        from .live_revu import LiveRevu
        with self.lock:
            require(not any(t.session.kind=='wine-revu' and not t.cancel.is_set() for t in self.tasks.values()),
                    'busy','Revu already has an active enrollment; revoke it before transferring ownership')
            require(sum(not t.cancel.is_set() for t in self.tasks.values())<6,'capacity','Task limit reached')
            ident=uuid.uuid4().hex
            session=LiveRevu(self.root/('live-'+ident))
            self.tasks[ident]=Task(owner,session,ttl=300)
        self.observer.event(ident,session.kind,'open',status='ready',
                            actor='Claude' if owner.startswith('claude') else 'Codex')
        self.capture(ident,self.tasks[ident])
        return {'task_id':ident,'kind':session.kind,'native_id':session.target['native_id'],
                'isolated':False,'expires_in':300,'permission':'explicit enrollment of live Revu test document only; no save or close'}

    def act(self, params, owner):
        require(set(params) <= {'task_id','action_id','action','native_id','args','timeout'}, 'invalid_argument', 'Unknown action parameter')
        task_id, action, ident = params.get('task_id'), params.get('action'), params.get('action_id')
        require(isinstance(ident, str) and re.fullmatch(r'[a-zA-Z0-9_-]{8,128}', ident), 'invalid_argument', 'Supply a unique action_id of 8–128 safe characters')
        require(isinstance(action, str) and action in READS | WRITES, 'permission_denied', 'Action is not in the desktop action allowlist')
        args = params.get('args', {})
        require(isinstance(args, dict) and set(args) <= PARAMETERS[action], 'invalid_argument', 'Unknown adapter arguments')
        timeout = params.get('timeout', 8)
        require(type(timeout) in (int, float) and 0.05 <= timeout <= 15, 'invalid_argument', 'Timeout must be 0.05–15 seconds')
        task = self.get_task(task_id, owner)
        if 'hold_ms' in args:
            require(task.session.kind.startswith('wayland-'),'unsupported_action','hold_ms requires a private KWin target')
        require(task.lock.acquire(blocking=False), 'busy', 'Another action owns this task; retry after it completes')
        try:
            require(not task.cancel.is_set(), 'cancelled', 'Task was cancelled')
            digest = hmac.new(self.digest_key, json.dumps(params, sort_keys=True).encode(), hashlib.sha256).hexdigest()
            existing = self.store.start(ident, task_id, owner, action, digest)
            if existing:
                require(existing['digest'] == digest, 'idempotency_conflict', 'Action ID was already used; no action was repeated')
                existing.pop('digest')
                return dict(existing, replayed=True)
            self.observer.event(task_id, task.session.kind, action, args)
            try:
                result = task.session.run(dict(args, action=action, native_id=params.get('native_id')), timeout)
                require(not task.cancel.is_set(), 'cancelled', 'Task cancelled during action; effect may have occurred')
            except DesktopError as exc:
                if ((task.session.kind == 'wine-revu' and exc.code == 'focus_changed') or
                        (task.session.kind == 'sway-live' and exc.code in ('focus_changed','stale_target','backend_failed','timeout'))):
                    task.cancel.set()
                    task.session.close()
                status = 'unknown' if exc.code in ('timeout','cancelled','backend_failed','focus_changed','stale_target') else 'failed'
                self.store.finish(ident, status, {'code': exc.code})
                self.observer.event(task_id, task.session.kind, action, args, status)
                raise
            except Exception:
                self.store.finish(ident, 'unknown', {'code': 'internal_error'})
                raise
            # Store metadata only. Text, tree content, images, selectors, and URLs are never logged.
            self.store.finish(ident, 'succeeded', {'code':'ok', 'delivered': action in WRITES,
                                                'verified_effect': False})
            self.observer.event(task_id, task.session.kind, action, args, 'succeeded')
            if action == 'screenshot':
                self.observer.frame(task_id, result)
            elif action in WRITES and task.session.kind != 'sway-live' and not result.get('dialog_open'):
                self.capture(task_id, task, params.get('native_id'))
            return {'action_id': ident, 'status': 'succeeded', 'result': result}
        finally:
            task.lock.release()

    def capture(self, task_id, task, native_id=None):
        try:
            if native_id is None:
                windows = task.session.run({'action': 'discover'})['windows']
                if not windows:
                    return
                native_id = windows[0]['native_id']
            self.observer.frame(task_id, task.session.run({'action':'screenshot', 'native_id':native_id}, timeout=2))
        except Exception:
            pass  # Observation must never change an action's success/failure result.

    def revoke_all(self):
        with self.lock:
            tasks = list(self.tasks.items())
        for task_id, task in tasks:
            task.cancel.set()
            task.session.close()
            self.observer.event(task_id, task.session.kind, 'close', status='cancelled')
        return {'cancelled_tasks': len(tasks)}

    def close(self):
        self.stop.set()
        self.revoke_all()
        self.reaper.join(timeout=6)
        self.store.db.close()
        self.lockfile.close()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(35)
        try:
            _, uid, _ = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            require(uid == os.getuid(), 'permission_denied', 'Unix peer must have the service UID')
            req = read_message(self.rfile)
            if req.get('method') == 'operator_sway_targets':
                from .sway import SwayConnection
                result = {'windows':SwayConnection().inventory()}
            elif req.get('method') == 'operator_enroll_sway':
                result = self.server.desktop.enroll_sway(req.get('params',{}))
            elif req.get('method') == 'operator_enroll_revu':
                result = self.server.desktop.enroll_revu(req.get('params',{}).get('owner'))
            elif req.get('method') == 'operator_revoke_all':
                # Local same-UID operator interface; deliberately not advertised by MCP.
                result = self.server.desktop.revoke_all()
            else:
                result = self.server.desktop.dispatch(req.get('method'), req.get('params', {}), req.get('owner'))
            response = {'ok': True, 'data': result}
        except DesktopError as exc:
            response = {'ok': False, 'error': {'code': exc.code, 'message': str(exc)}}
        except Exception:
            response = {'ok': False, 'error': {'code': 'invalid_request', 'message': 'Malformed request or internal failure'}}
        try:
            self.wfile.write(json.dumps(response).encode()+b'\n')
        except OSError:
            pass


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = False
    block_on_close = True


def serve(path=DEFAULT_SOCKET, observer_port=0):
    path = Path(path)
    os.umask(0o077)
    desktop = DesktopService(path.parent)
    if path.exists():
        require(path.is_socket(), 'unsafe_runtime', 'Socket path is occupied by a non-socket')
        path.unlink()
    observer_server = desktop.observer.serve(observer_port)
    observer_link = path.parent / 'observer-url'
    observer_link.write_text(desktop.observer.url + '\n')
    observer_link.chmod(0o600)
    server = Server(str(path), Handler)
    server.desktop = desktop
    os.chmod(path, 0o600)
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever(poll_interval=.1)
    finally:
        desktop.revoke_all()
        server.server_close()
        desktop.close()
        observer_server.shutdown()
        observer_server.server_close()
        observer_link.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
