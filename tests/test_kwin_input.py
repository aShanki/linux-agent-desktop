import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from conftest import act
from lad.errors import DesktopError
from lad.session import kill_process
from test_wayland import open_native


def state_at(path, condition, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = json.loads(path.read_text())
            if condition(value):
                return value
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.02)
    raise AssertionError(f'Fixture did not reach expected state: {path}')


def polled_target(service, owner):
    task, _, session, _ = open_native(service, owner, 'wayland-qt')
    kill_process(session.app)
    session.state_file = session.directory / 'polled.json'
    fixture = Path(__file__).parent / 'fixtures' / 'polled_input.py'
    session.app = session.spawn([sys.executable, str(fixture), str(session.state_file)])
    state_at(session.state_file, lambda _: True)
    scene = act(service, owner, task, 'discover')['result']
    native = scene['windows'][0]['native_id']
    return task, native, session


def test_frame_polled_clicks_and_held_keys(service, owner):
    task, native, session = polled_target(service, owner)
    for count in range(1, 4):
        act(service, owner, task, 'click', native, {'x': 100, 'y': 100})
        state_at(session.state_file, lambda s: s['clicks'] == count and not s['mouse_down'])
    act(service, owner, task, 'key', native, {'key': 'w', 'hold_ms': 250})
    value = state_at(session.state_file, lambda s: s['keys'] == 1 and not s['key_down'])
    assert value['key_ticks'] >= 3


@pytest.mark.parametrize('hold', [0, -1, 10001, True, 1.5, '150'])
def test_invalid_hold_is_rejected_before_input(service, owner, hold):
    task, native, session = polled_target(service, owner)
    with pytest.raises(DesktopError) as exc:
        act(service, owner, task, 'click', native, {'x': 100, 'y': 100, 'hold_ms': hold})
    assert exc.value.code == 'invalid_argument'
    assert json.loads(session.state_file.read_text())['clicks'] == 0


def test_timed_out_hold_releases_input_and_keeps_target(service, owner):
    task, native, session = polled_target(service, owner)
    with pytest.raises(DesktopError) as exc:
        act(service, owner, task, 'key', native, {'key': 'w', 'hold_ms': 3000}, timeout=.4)
    assert exc.value.code == 'timeout'
    state_at(session.state_file, lambda s: not s['key_down'])
    assert session.app.poll() is None
    assert session.input_keeper.poll() is None
    act(service, owner, task, 'click', native, {'x': 100, 'y': 100})
    state_at(session.state_file, lambda s: s['clicks'] == 1)


def test_input_capabilities_survive_short_lived_adapters(service, owner, tmp_path):
    task, native, session, _ = open_native(service, owner, 'wayland-qt')
    source = Path(__file__).parent / 'fixtures' / 'seat_watch.c'
    binary = tmp_path / 'seat-watch'
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'wayland-client'], text=True).split()
    subprocess.run(['cc', str(source), '-o', str(binary), *flags], check=True)
    state = session.directory / 'seat.json'
    session.spawn([str(binary), str(state)])
    state_at(state, lambda s: s['pointer'] and s['keyboard'])
    for _ in range(3):
        act(service, owner, task, 'click', native, {'x': 80, 'y': 85})
        assert state_at(state, lambda s: s['pointer'] and s['keyboard'])
    keeper = session.input_keeper
    kill_process(keeper)
    state_at(state, lambda s: not s['pointer'])
    with pytest.raises(DesktopError) as exc:
        act(service, owner, task, 'click', native, {'x': 80, 'y': 85})
    assert exc.value.code == 'backend_failed'


def test_close_reaps_input_keeper(service, owner):
    task, _, session, _ = open_native(service, owner, 'wayland-qt')
    keeper = session.input_keeper
    service.dispatch('close_task', {'task_id': task}, owner)
    assert keeper.poll() is not None


def test_other_backends_reject_hold_option(service, owner):
    from test_desktop import open_target
    task, native, session = open_target(service, owner, 'qt')
    with pytest.raises(DesktopError) as exc:
        act(service, owner, task, 'click', native, {'x': 80, 'y': 85, 'hold_ms': 150})
    assert exc.value.code == 'unsupported_action'
