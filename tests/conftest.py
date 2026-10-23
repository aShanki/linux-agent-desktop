import uuid
import pytest
from lad.service import DesktopService

@pytest.fixture
def service(tmp_path):
    value = DesktopService(tmp_path / 'service')
    yield value
    value.close()

@pytest.fixture
def owner():
    return uuid.uuid4().hex


def act(service, owner, task, action, native_id=None, args=None, **kwargs):
    return service.dispatch('act', dict(task_id=task, action_id=uuid.uuid4().hex,
                            action=action, native_id=native_id, args=args or {}, **kwargs), owner)
