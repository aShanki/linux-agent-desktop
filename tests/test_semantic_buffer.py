import pytest
from conftest import act
from lad.semantic_buffer import SemanticBuffer, fingerprint
from lad.errors import DesktopError


def test_scoped_buffer_rejects_human_edit_without_overwriting(service, owner):
    task = service.dispatch('open_task', {'kind':'gtk'}, owner)['task_id']
    session = service.tasks[task].session
    # Run on the task's private accessibility bus, not the host.
    code = '''from lad.semantic_buffer import SemanticBuffer,fingerprint
from lad.accessibility import Accessibility
from lad.errors import DesktopError
nodes=Accessibility(PID).nodes()
element=next(ident for ident,node,info in nodes if info['name']=='Message')
buffer=SemanticBuffer(PID,element)
buffer.replace(0,0,'agent text',fingerprint(''))
old=fingerprint(buffer.read())
node=buffer.node
from lad.accessibility import Atspi
Atspi.EditableText.set_text_contents(node,'human edit')
try:buffer.replace(0,5,'replacement',old)
except DesktopError as e:assert e.code=='concurrent_edit'
else:raise AssertionError('conflict not detected')
assert buffer.read()=='human edit'
result=buffer.replace(0,5,'shared',fingerprint('human edit'))
assert buffer.read()=='shared edit' and result['characters']==11
print('verified')
'''.replace('PID',str(session.app.pid))
    import sys,subprocess
    process=session.spawn([sys.executable,'-c',code],stdout=subprocess.PIPE)
    out,_=process.communicate(timeout=8)
    assert process.returncode==0 and out.strip()==b'verified'
