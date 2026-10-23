"""Read-only, token-gated loopback visual observer. Volatile frames, no input injection."""
import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class Observer:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.tasks = {}
        self.version = 0

    def event(self, task_id, kind, action, args=None, status='running', actor=None):
        args = args or {}
        with self.lock:
            if task_id not in self.tasks and len(self.tasks) >= 12:
                del self.tasks[next(iter(self.tasks))]
            task = self.tasks.setdefault(task_id, {'id': task_id[:8], 'kind': kind, 'actor': actor or 'Agent', 'events': [], 'frame': None})
            self.version += 1
            # No typed text, selectors, window titles, paths, or backend error messages.
            event = {'id': self.version, 'action': action, 'status': status, 'time': time.time()}
            for key in ('x', 'y', 'end_x', 'end_y'):
                if type(args.get(key)) in (int, float):
                    event[key] = args[key]
            if status != 'running' and task['events'] and task['events'][-1]['action'] == action and task['events'][-1]['status'] == 'running':
                task['events'][-1] = event
            else:
                task['events'] = (task['events'] + [event])[-40:]
            task['status'] = status

    def frame(self, task_id, result):
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id]['frame'] = result.get('png')
                self.tasks[task_id]['coordinate_scale'] = result.get('scale',1)
                self.version += 1

    def state(self):
        with self.lock:
            return json.loads(json.dumps({'version': self.version, 'tasks': list(self.tasks.values())}))

    def serve(self, port=0):
        observer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                origin = self.headers.get('Origin')
                host = f'127.0.0.1:{self.server.server_port}'
                if self.headers.get('Host') != host or (origin and origin != 'http://'+host):
                    self.send_error(403)
                    return
                path = urlsplit(self.path).path
                if path == '/api/state':
                    provided = self.headers.get('Authorization', '').removeprefix('Bearer ')
                    if not hmac.compare_digest(provided, observer.token):
                        self.send_error(403)
                        return
                    data = json.dumps(observer.state()).encode()
                    mime = 'application/json'
                elif path == '/':
                    data = Path(__file__).with_name('observer.html').read_bytes()
                    mime = 'text/html; charset=utf-8'
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                self.wfile.write(data)
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{server.server_port}/#'+self.token
        return server
