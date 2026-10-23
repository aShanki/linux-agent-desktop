"""Content-free activity signals for a persistent, input-transparent cursor."""
from contextlib import contextmanager
import json
import math
import threading
import time
from pathlib import Path


def project_point(rect, state):
    x, y, width, height = rect
    px, py = state.get('x', 80), state.get('y', 140)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y, width, height, px, py)):
        return None
    if state.get('space', 'window') == 'normalized':
        if not (0 <= px <= 1 and 0 <= py <= 1):
            return None
        px, py = px * width, py * height
    elif state.get('space', 'window') != 'window':
        return None
    if not (0 <= px < width and 0 <= py < height):
        return None
    return x + px, y + py


def is_active(state, now=None):
    now = time.time() if now is None else now
    heartbeat = state.get('heartbeat', 0)
    return (state.get('active') is True and isinstance(heartbeat, (float, int))
            and 0 <= now - heartbeat < 2)


class Motion:
    def __init__(self, point, now=0):
        self.origin = self.target = point
        self.started = now
        self.duration = .22

    def position(self, now):
        progress = max(0, min(1, (now - self.started) / self.duration))
        eased = progress * progress * (3 - 2 * progress)
        return tuple(a + (b - a) * eased for a, b in zip(self.origin, self.target))

    def move(self, point, now):
        if point != self.target:
            self.origin = self.position(now)
            self.target = point
            self.started = now


class Activity:
    def __init__(self, path, x, y, space):
        self.path = Path(path)
        self.state = dict(x=x, y=y, space=space, click_seq=0)
        self.lock = threading.Lock()

    def write(self, active=True):
        with self.lock:
            value = dict(self.state, active=active, heartbeat=time.time())
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(value))
            temp.chmod(0o600)
            temp.replace(self.path)

    def move(self, x, y, space=None):
        with self.lock:
            self.state.update(x=x, y=y)
            if space is not None:
                self.state['space'] = space
        self.write()

    def click(self):
        with self.lock:
            self.state['click_seq'] += 1
        self.write()


@contextmanager
def activity(path, x, y, space='window'):
    """Signal actual GUI work, smooth cursor moves and explicit click events."""
    controller = Activity(path, x, y, space)
    stop = threading.Event()
    def pulse():
        while not stop.wait(.4):
            controller.write()
    controller.write()
    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    try:
        yield controller
    finally:
        stop.set()
        thread.join(timeout=1)
        controller.write(False)
