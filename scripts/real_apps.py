#!/usr/bin/env python3
"""Verify installed Kate/Writer through the real backend on private Wayland.

Creates only fresh profiles and scratch documents. Never connects to the user's
Wayland socket, D-Bus, application instances, or profiles. Screenshots stay in
.runtime; the public report contains only versions and assertions.
"""
import base64
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from lad.session import Session, kill_process, process_start

ROOT = Path(__file__).resolve().parent.parent
TEXT = 'Linux Agent Desktop verified background input'
FODT = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.3"
 office:mimetype="application/vnd.oasis.opendocument.text">
 <office:body><office:text><text:p/></office:text></office:body></office:document>'''


def check_app(name):
    directory = ROOT / '.runtime' / f'real-{name}-{time.time_ns()}'
    session = Session(directory, 'wayland-qt', 1.5, 2)
    app = None
    pid = None
    identity = None
    try:
        kill_process(session.app)
        if name == 'kate':
            document = directory / 'scratch.txt'
            document.write_text('')
            app = session.spawn(['kate', '--startanon', str(document)])
        else:
            document = directory / 'scratch.fodt'
            document.write_text(FODT)
            session.env['SAL_USE_VCLPLUGIN'] = 'qt6'
            app = session.spawn(['libreoffice', '-env:UserInstallation=' + (directory / 'profile').as_uri(),
                                 '--writer', '--norestore', '--pidfile=' + str(directory / 'app.pid'), str(document)])

        def run(candidate, action, **args):
            operation = dict(kind='wayland-qt', pid=candidate, action=action, **args)
            worker = session.spawn([sys.executable, '-m', 'lad.worker'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            output, _ = worker.communicate(json.dumps(operation).encode(), timeout=15)
            if worker.returncode:
                raise RuntimeError('Owned backend process failed')
            result = json.loads(output)
            if 'error' in result:
                raise RuntimeError(result['error']['code'])
            return result

        # Toolkits can fork a child. Discover only our process group; never use
        # a host-wide application-name search or the user's window list.
        time.sleep(3)
        deadline = time.monotonic() + 15
        scene = None
        while time.monotonic() < deadline:
            time.sleep(.2)
            group = subprocess.run(['pgrep', '-g', str(app.pid)], capture_output=True, text=True)
            candidates = set(map(int, group.stdout.split()))
            if name == 'libreoffice':
                candidates = {int((directory / 'app.pid').read_text())} if (directory / 'app.pid').exists() else set()
            if name == 'kate':
                # Kate detaches into a new process group. Resolve its service on
                # our private bus, never through the host session's service.
                services = session.spawn(['qdbus6', 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                                          'org.freedesktop.DBus.ListNames'], stdout=subprocess.PIPE)
                names, _ = services.communicate(timeout=4)
                for service in names.decode().splitlines():
                    if service.startswith('org.kde.kate-'):
                        query = session.spawn(['qdbus6','org.freedesktop.DBus','/org/freedesktop/DBus',
                                               'org.freedesktop.DBus.GetConnectionUnixProcessID',service],
                                              stdout=subprocess.PIPE)
                        answer, _ = query.communicate(timeout=4)
                        candidates.add(int(answer.strip()))
            for candidate in candidates:
                if candidate == session.app.pid:
                    continue
                found = run(candidate, 'discover')
                if found['windows']:
                    pid, scene = candidate, found
                    identity = process_start(pid)
                    break
            if scene:
                break
        if not scene:
            raise RuntimeError('Owned application did not create a Wayland window')
        # Wait out splash surfaces, then rediscover the stable main/dialog IDs.
        time.sleep(3)
        scene = run(pid, 'discover')
        windows = scene['windows']
        main = max(windows, key=lambda w: w['width'] * w['height'])
        target = main['native_id']
        dismissed = False
        if name == 'libreoffice' and not main['active']:
            dialog = next(w for w in windows if w['active'])
            image = run(pid, 'screenshot', native_id=dialog['native_id'])
            (directory / 'welcome.png').write_bytes(base64.b64decode(image['png']))
            run(pid, 'key', native_id=dialog['native_id'], key='Escape')
            dismissed = True
            time.sleep(.3)
        run(pid, 'type', native_id=target, text=TEXT)
        run(pid, 'key', native_id=target, key='s', modifier='ctrl')
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if name == 'kate':
                actual = document.read_text().rstrip('\n')
            else:
                body = ET.parse(document).find('.//{urn:oasis:names:tc:opendocument:xmlns:office:1.0}body')
                actual = ''.join(body.itertext()).strip()
            if actual == TEXT:
                break
            time.sleep(.1)
        assert actual == TEXT, 'Saved document differs from the input'
        frame = run(pid, 'screenshot', native_id=target)
        (directory / 'verified.png').write_bytes(base64.b64decode(frame['png']))
        version = subprocess.run([name, '--version'], env={**session.env, 'QT_QPA_PLATFORM':'offscreen'},
                                 capture_output=True, text=True, timeout=8).stdout.strip()
        return dict(app=name, version=version, passed=True, saved_text_exact=True,
                    welcome_dialog_dismissed=dismissed, screenshot_width=frame['width'],
                    screenshot_height=frame['height'], scale=frame['scale'], virtual_outputs=2,
                    scope='fresh profile and scratch document on private KWin; no host desktop connection')
    finally:
        # A launcher can exit before its child. Stop only its still-owned group.
        if pid and identity and process_start(pid) == identity:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        session.close()


def main():
    (ROOT / '.runtime').mkdir(exist_ok=True)
    results = []
    for name in ('kate', 'libreoffice'):
        result = check_app(name)
        results.append(result)
        print(name + ': exact saved text and window capture verified', flush=True)
    report = dict(generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), results=results)
    (ROOT / 'artifacts' / 'real-apps.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
