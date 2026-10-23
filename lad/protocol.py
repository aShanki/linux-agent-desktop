"""One bounded JSON request per same-UID Unix socket connection."""
import json
import socket
from pathlib import Path

MAX_MESSAGE = 16 * 1024 * 1024
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOCKET = ROOT / '.runtime' / 'service.sock'


def read_message(stream):
    data = stream.readline(MAX_MESSAGE + 1)
    if len(data) > MAX_MESSAGE or not data.endswith(b'\n'):
        raise ValueError('Invalid or oversized message')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('Message must be an object')
    return value


def request(method, params=None, *, owner, path=DEFAULT_SOCKET, timeout=35):
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(timeout)
        conn.connect(str(path))
        stream = conn.makefile('rwb')
        stream.write(json.dumps({'method': method, 'params': params or {}, 'owner': owner}).encode() + b'\n')
        stream.flush()
        return read_message(stream)
