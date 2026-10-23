"""Live-enrollment policy tests. Never attach to the user's Revu during pytest."""
import subprocess
import threading
import pytest
from lad.errors import DesktopError
from lad.live_revu import LiveRevu


def test_public_mcp_cannot_enroll_live_window(service,owner):
    with pytest.raises(DesktopError) as err:
        service.dispatch('operator_enroll_revu',{},owner)
    assert err.value.code=='unknown_method'


def test_live_close_only_stops_owned_helpers():
    helper=subprocess.Popen(['sleep','30'],start_new_session=True)
    application=subprocess.Popen(['sleep','30'],start_new_session=True)
    live=LiveRevu.__new__(LiveRevu)
    live.processes=[helper]
    live.cancelled=False
    live.lock=threading.RLock()
    try:
        live.close()
        assert helper.poll() is not None
        assert application.poll() is None
        live.close()
    finally:
        application.terminate();application.wait()


def test_one_live_enrollment_and_expiry(service,owner,monkeypatch):
    class Target:
        kind='wine-revu'
        def __init__(self,directory):
            self.target={'native_id':1234};self.closed=False
        def run(self,op,timeout=8):
            return {'windows':[]}
        def close(self):self.closed=True
    monkeypatch.setattr('lad.live_revu.LiveRevu',Target)
    enrolled=service.enroll_revu(owner)
    task=service.tasks[enrolled['task_id']]
    assert enrolled['expires_in']==300 and enrolled['isolated'] is False
    with pytest.raises(DesktopError) as err:service.enroll_revu(owner)
    assert err.value.code=='busy'
    task.created-=301
    with pytest.raises(DesktopError) as err:service.get_task(enrolled['task_id'],owner)
    assert err.value.code=='cancelled' and task.session.closed


def test_input_guard_revokes_live_grant(service,owner,monkeypatch):
    class Target:
        kind='wine-revu'
        def __init__(self,directory):self.target={'native_id':1234};self.closed=False
        def run(self,op,timeout=8):
            if op['action']=='discover':return {'windows':[]}
            raise DesktopError('focus_changed','Input changed')
        def close(self):self.closed=True
    monkeypatch.setattr('lad.live_revu.LiveRevu',Target)
    enrolled=service.enroll_revu(owner)
    with pytest.raises(DesktopError):
        service.dispatch('act',{'task_id':enrolled['task_id'],'native_id':1234,
                                'action_id':'guard-test-0001','action':'click','args':{'x':1,'y':1}},owner)
    assert not service.dispatch('list_tasks',{},owner)['tasks'][0]['active']
    assert service.tasks[enrolled['task_id']].session.closed
    assert service.dispatch('result',{'action_id':'guard-test-0001'},owner)['status']=='unknown'


def test_unconfigured_live_adapter_never_inspects_desktop(tmp_path, monkeypatch):
    import lad.live_revu as module
    for name in ('LAD_WINE_BIN', 'LAD_WINEPREFIX', 'LAD_REVU_TITLE'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(DesktopError) as error:
        LiveRevu(tmp_path / 'not-created')
    assert error.value.code == 'live_not_configured'
    assert not (tmp_path / 'not-created').exists()
    monkeypatch.setattr(module, 'TITLE', '')
    with pytest.raises(DesktopError) as error:
        module.x11_operation({'action': 'probe'})
    assert error.value.code == 'live_not_configured'


def test_live_configuration_requires_explicit_paths_and_title(tmp_path, monkeypatch):
    from lad.live_revu import live_configuration
    runner = tmp_path / 'bin'
    prefix = tmp_path / 'prefix'
    runner.mkdir(); prefix.mkdir()
    for name in ('wine', 'wineserver'):
        (runner / name).touch()
    monkeypatch.setenv('LAD_WINE_BIN', str(runner))
    monkeypatch.setenv('LAD_WINEPREFIX', str(prefix))
    monkeypatch.setenv('LAD_REVU_TITLE', 'LAD-Revu-Test')
    assert live_configuration()[:2] == (runner, prefix)
    monkeypatch.setenv('LAD_REVU_TITLE', '')
    with pytest.raises(DesktopError):
        live_configuration()
    monkeypatch.setenv('LAD_REVU_TITLE', 'LAD-Revu-Test')
    monkeypatch.setenv('LAD_WINEPREFIX', 'relative-prefix')
    with pytest.raises(DesktopError) as error:
        live_configuration()
    assert error.value.code == 'invalid_argument'
