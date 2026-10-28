"""Owned processes and fresh profiles, never the user's running desktop."""
import json
import os
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import threading
import tempfile
from pathlib import Path
from .errors import DesktopError, require
from .protocol import ROOT


def process_start(pid):
    try:
        # comm can contain spaces and parentheses; fields after its final ')' start at field 3.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def kill_process(process):
    if process and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)


class Session:
    def __init__(self, directory, kind='qt', scale=1, outputs=1):
        self.directory = Path(directory)
        self.kind = kind
        self.outputs = outputs
        self.processes = []
        self.lifecycle = threading.RLock()
        self.cancelled = False
        self.directory.mkdir(mode=0o700)
        self.env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}
        for sub in ('home', 'runtime', 'config', 'cache', 'data'):
            if sub == 'runtime' and kind.startswith('wayland-'):
                self.runtime_dir = Path(tempfile.mkdtemp(prefix='lad-wayland-'))
                (self.directory / sub).symlink_to(self.runtime_dir,target_is_directory=True)
            else:
                (self.directory / sub).mkdir(mode=0o700)
        self.env.update(HOME=str(self.directory / 'home'), XDG_RUNTIME_DIR=str((self.directory / 'runtime').resolve()),
                        XDG_CONFIG_HOME=str(self.directory / 'config'), XDG_CACHE_HOME=str(self.directory / 'cache'),
                        XDG_DATA_HOME=str(self.directory / 'data'), PYTHONPATH=str(ROOT),
                        QT_QPA_PLATFORM='xcb', QT_SCALE_FACTOR=str(scale), NO_AT_BRIDGE='0',
                        GTK_MODULES='gail:atk-bridge', QT_LINUX_ACCESSIBILITY_ALWAYS_ON='1')
        self.log = open(self.directory / 'process.log', 'wb')
        try:
            bus = self.spawn(['dbus-daemon', '--session', '--nofork', '--print-address=1'], stdout=subprocess.PIPE)
            self.env['DBUS_SESSION_BUS_ADDRESS'] = self.read_line(bus.stdout)
            self._start_display()
            self.state_file = self.directory / 'fixture.json'
            if kind in ('qt', 'gtk', 'wayland-qt', 'wayland-gtk', 'wayland-canvas'):
                self.app = self.spawn([sys.executable, '-m', 'lad.demo', kind.removeprefix('wayland-'), str(self.state_file)])
                self.wait_for(self.state_file.exists)
            else:
                self._start_browser()
                self.browser_worker = self.spawn([sys.executable, '-m', 'lad.browser_worker'],
                                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        except Exception:
            self.close()
            raise

    def spawn(self, argv, **kwargs):
        with self.lifecycle:
            require(not self.cancelled, 'cancelled', 'Task has been cancelled')
            p = subprocess.Popen(argv, env=self.env, cwd=ROOT, stdin=kwargs.pop('stdin', subprocess.DEVNULL),
                                 stdout=kwargs.pop('stdout', self.log), stderr=self.log,
                                 start_new_session=True, **kwargs)
            self.processes.append(p)
            self.save_processes()
            return p

    def save_processes(self):
        path = self.directory / 'processes.json'
        values = [{'pid': p.pid, 'start': process_start(p.pid)} for p in self.processes if p.poll() is None]
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(values))
        tmp.replace(path)

    @staticmethod
    def read_line(stream):
        import select
        require(bool(select.select([stream], [], [], 5)[0]), 'startup_timeout', 'Session startup timed out')
        line = stream.readline().decode().strip()
        require(bool(line), 'startup_failed', 'Session process exited during startup')
        return line

    def wait_for(self, condition, timeout=8):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if condition():
                return
            if self.app.poll() is not None:
                raise DesktopError('startup_failed', 'Dedicated app failed; inspect its private process.log')
            time.sleep(.05)
        raise DesktopError('startup_timeout', 'Dedicated application did not become ready')

    def _start_display(self):
        if self.kind.startswith('wayland-'):
            self.env.update(QT_QPA_PLATFORM='offscreen', LIBGL_ALWAYS_SOFTWARE='1',
                            WAYLAND_DISPLAY='lad-isolated', KWIN_SCREENSHOT_NO_PERMISSION_CHECKS='1',
                            QT_LOGGING_RULES='kwin_scripting.debug=true')
            compositor=self.spawn(['kwin_wayland','--virtual','--width','1600','--height','1200',
                                    '--scale',self.env['QT_SCALE_FACTOR'],'--output-count',str(self.outputs),'--no-lockscreen',
                                    '--no-global-shortcuts','--no-kactivities','--socket','lad-isolated'])
            end=time.monotonic()+8
            while not (Path(self.env['XDG_RUNTIME_DIR'])/'lad-isolated').exists():
                require(compositor.poll() is None and time.monotonic()<end,'startup_failed','Private KWin failed to start')
                time.sleep(.05)
            self.env.update(QT_QPA_PLATFORM='wayland', QT_SCALE_FACTOR='1', LAD_KWIN_PID=str(compositor.pid),
                            LAD_ISOLATED_ROOT=str(self.directory))
            self.env.pop('KWIN_SCREENSHOT_NO_PERMISSION_CHECKS')
            scale = float(compositor.args[compositor.args.index('--scale')+1])
            settings=[f'output.{i}.scale.{scale}' for i in range(1,self.outputs+1)]
            if self.outputs==2:settings.append('output.2.position.1600,0')
            setup=self.spawn(['kscreen-doctor',*settings],stdout=subprocess.PIPE)
            setup.communicate(timeout=8)
            require(setup.returncode==0,'startup_failed','Cannot configure private output scaling')
            # Short-lived adapters must not remove the last input device while Xwayland holds a pointer lock.
            self.input_keeper=self.spawn([sys.executable,'-m','lad.kwin_input'],stdout=subprocess.PIPE)
            try:
                require(self.read_line(self.input_keeper.stdout)=='ready','startup_failed','Private input connection failed to start')
            finally:
                self.input_keeper.stdout.close()
            return
        xvfb = shutil.which('Xvfb') or str(ROOT / '.local/xvfb/usr/bin/Xvfb')
        require(Path(xvfb).is_file(), 'missing_dependency', 'Run scripts/bootstrap.sh to provision Xvfb')
        # Xauthority contains only a newly generated cookie for our private display.
        auth = self.directory / 'Xauthority'
        def field(x):
            return struct.pack('!H', len(x)) + x
        auth.write_bytes(struct.pack('!H', 256) + field(socket.gethostname().encode()) + field(b'') +
                         field(b'MIT-MAGIC-COOKIE-1') + field(secrets.token_bytes(16)))
        auth.chmod(0o600)
        self.env['XAUTHORITY'] = str(auth)
        r, w = os.pipe()
        try:
            self.spawn([xvfb, '-displayfd', str(w), '-screen', '0', '1920x1200x24',
                        '-nolisten', 'tcp', '-noreset', '-auth', str(auth)], pass_fds=(w,))
            os.close(w)
            w = None
            with os.fdopen(r, 'rb') as pipe:
                self.env['DISPLAY'] = ':' + self.read_line(pipe)
        finally:
            if w is not None:
                os.close(w)

    def _start_browser(self):
        chrome = shutil.which('google-chrome') or shutil.which('chromium')
        require(bool(chrome), 'missing_dependency', 'Chrome or Chromium is required')
        profile = self.directory / 'browser'
        html = ROOT / 'lad' / 'fixture.html'
        self.app = self.spawn([chrome, '--headless=new', '--disable-gpu', '--no-first-run',
                               '--no-default-browser-check', '--disable-background-networking',
                               '--disable-sync', '--disable-extensions', '--remote-debugging-port=0',
                               '--remote-debugging-address=127.0.0.1', '--window-size=800,600',
                               '--user-data-dir=' + str(profile), html.as_uri()])
        self.wait_for(lambda: (profile / 'DevToolsActivePort').exists())
        self.env['LAD_CDP_PORT'] = (profile / 'DevToolsActivePort').read_text().splitlines()[0]

    def run(self, operation, timeout=8):
        require(not self.cancelled and self.app.poll() is None, 'target_gone', 'Task target is no longer running')
        if self.kind.startswith('wayland-'):
            require(self.input_keeper.poll() is None,'backend_failed','Private input connection was lost; close and reopen the task')
        if self.kind == 'browser':
            return self.run_browser(operation, timeout)
        p = self.spawn([sys.executable, '-m', 'lad.worker'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            stdout, _ = p.communicate(json.dumps(dict(operation, kind=self.kind, pid=self.app.pid)).encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_process(p)
            raise DesktopError('timeout', 'Action timed out; inspect before retrying writes')
        finally:
            if p.poll() is not None:
                self.processes.remove(p) if p in self.processes else None
        require(p.returncode == 0, 'backend_failed', 'Backend exited without a result')
        result = json.loads(stdout)
        if 'error' in result:
            raise DesktopError(result['error']['code'], result['error']['message'])
        return result

    def run_browser(self, operation, timeout):
        import select
        process = self.browser_worker
        require(process.poll() is None, 'target_gone', 'Browser worker is no longer running')
        process.stdin.write(json.dumps(operation).encode()+b'\n')
        process.stdin.flush()
        deadline = time.monotonic()+timeout
        data = bytearray()
        while not data.endswith(b'\n'):
            remaining = deadline-time.monotonic()
            if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                kill_process(process)
                raise DesktopError('timeout', 'Browser action timed out; inspect before retrying writes')
            block = os.read(process.stdout.fileno(), 65536)
            require(bool(block) and len(data)+len(block) < 16*1024*1024, 'backend_failed', 'Invalid browser response')
            data.extend(block)
        value = json.loads(data)
        if 'error' in value:
            raise DesktopError(value['error']['code'], value['error']['message'])
        return value

    def close(self):
        with self.lifecycle:
            self.cancelled = True
            for process in reversed(list(self.processes)):
                kill_process(process)
            self.processes.clear()
            (self.directory / 'processes.json').unlink(missing_ok=True)
            if hasattr(self,'runtime_dir'):
                shutil.rmtree(self.runtime_dir,ignore_errors=True)
            if hasattr(self, 'log') and not self.log.closed:
                self.log.close()
