import base64
import io
import json
import time
import uuid
import pytest
from PIL import Image
from lad.errors import DesktopError
from conftest import act


def wait_state(session, predicate):
    end = time.monotonic()+3
    while time.monotonic()<end:
        try:
            value = json.loads(session.state_file.read_text())
            if predicate(value):
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.03)
    raise AssertionError('Fixture did not reach expected state')


def open_target(service, owner, kind='qt', scale=1):
    task = service.dispatch('open_task', {'kind':kind, 'scale':scale}, owner)['task_id']
    n = act(service,owner,task,'discover')['result']['windows'][0]['native_id']
    return task,n,service.tasks[task].session


@pytest.mark.parametrize('scale',[1,1.5,2])
def test_x11_input_capture_scaling(service,owner,scale):
    task,n,session=open_target(service,owner,scale=scale)
    state = wait_state(session,lambda s: bool(s['controls']))
    def point(control):
        x,y,w,h=state['controls'][control]
        return {'x':int((x+w/2)*scale),'y':int((y+h/2)*scale)}
    shot=act(service,owner,task,'screenshot',n)['result']
    image=Image.open(io.BytesIO(base64.b64decode(shot['png'])))
    assert image.size==(int(640*scale),int(440*scale))
    assert image.getpixel((int(30*scale),int(30*scale)))==(36,85,170)
    assert shot['isolated_display_focus_unchanged'] and shot['pointer_unchanged']
    act(service,owner,task,'click',n,point('entry'))
    text='Hello World! AaZz 0123 @#$% ^&*()[]{};:,./?'
    result=act(service,owner,task,'type',n,{'text':text})['result']
    assert result['pointer_unchanged']
    wait_state(session,lambda s:s['text']==text)
    act(service,owner,task,'key',n,{'key':'a','modifier':'ctrl'})
    wait_state(session,lambda s:s['selection']==text)
    act(service,owner,task,'type',n,{'text':'replacement'})
    wait_state(session,lambda s:s['text']=='replacement')
    act(service,owner,task,'click',n,point('button'))
    wait_state(session,lambda s:s['clicks']==1)
    with pytest.raises(DesktopError) as err:
        act(service,owner,task,'scroll',n,dict(point('scroll'),steps=3))
    assert err.value.code == 'unsupported_action'


def test_gtk_semantic_unicode_no_focus(service,owner):
    task,n,session=open_target(service,owner,'gtk')
    nodes=act(service,owner,task,'tree',n)['result']['nodes']
    entry=next(x for x in nodes if x['name']=='Message')
    button=next(x for x in nodes if x['name']=='Increment')
    for action,args in [('set_text',{'element':entry['element'],'text':'Hello ✓ 中文'}),
                        ('invoke',{'element':button['element'],'name':'click'})]:
        result=act(service,owner,task,action,n,args)['result']
        assert result['isolated_display_focus_unchanged']
        assert result['pointer_unchanged']
    wait_state(session,lambda s:s['text']=='Hello ✓ 中文' and s['clicks']==1)
    with pytest.raises(DesktopError,match='Reinspect'):
        act(service,owner,task,'invoke',n,{'element':'stale-node','name':'click'})


def test_browser_unicode_click_scroll_dialog(service,owner):
    task,n,session=open_target(service,owner,'browser')
    tree=act(service,owner,task,'tree',n)['result']['nodes']
    act(service,owner,task,'set_text',n,{'element':'message','text':'Hello ✓ 中文'})
    node=next(x for x in tree if x['element']=='increment')['rect']
    act(service,owner,task,'click',n,{'x':int(node['x']+20),'y':int(node['y']+20)})
    # Fixture assertions via a dedicated test-only subprocess. No arbitrary JS MCP tool exists.
    import subprocess,sys
    def read(expression):
        p=subprocess.run([sys.executable,'-c','from lad.browser import Browser; import json; print(json.dumps(Browser().evaluate('+repr(expression)+')))'],
                         env=session.env,capture_output=True,text=True,check=True)
        return json.loads(p.stdout)
    assert read("document.querySelector('#message').value")=='Hello ✓ 中文'
    assert read('window.count')==1
    act(service,owner,task,'scroll',n,{'x':120,'y':320,'steps':3})
    time.sleep(.2)
    assert read("document.querySelector('#scroll').scrollTop")>0
    node=next(x for x in tree if x['element']=='dialog')['rect']
    act(service,owner,task,'click',n,{'x':int(node['x']+10),'y':int(node['y']+10)})
    act(service,owner,task,'dialog',n,{'accept':False})
    shot=act(service,owner,task,'screenshot',n)['result']
    assert Image.open(io.BytesIO(base64.b64decode(shot['png']))).width>0


def test_policy_identity_and_no_log_payload(service,owner):
    task,n,session=open_target(service,owner)
    with pytest.raises(DesktopError) as err:
        act(service,uuid.uuid4().hex,task,'click',n,{'x':1,'y':1})
    assert err.value.code=='not_found'
    for action,args in [('foreground',{}),('click',{'x':-1,'y':3}),('type',{'text':'x','extra':'y'})]:
        with pytest.raises(DesktopError):
            act(service,owner,task,action,n,args)
    with pytest.raises(DesktopError):
        act(service,owner,task,'click',1,{'x':1,'y':1})
    with pytest.raises(DesktopError):
        service.dispatch('open_task',{'kind':'revu'},owner)
    # Invalid text is rejected before any character can be typed; audit excludes payload.
    secret='DO-NOT-LOG-TEST-MARKER-✓'
    with pytest.raises(DesktopError):
        act(service,owner,task,'type',n,{'text':secret})
    for path in service.root.glob('actions.sqlite3*'):
        assert secret.encode() not in path.read_bytes()
    assert secret not in (session.directory/'process.log').read_text()
    assert secret not in json.dumps(service.observer.state())


def test_replay_busy_cancel_and_durable_status(service,owner):
    task,n,session=open_target(service,owner)
    state=wait_state(session,lambda s:True)
    x,y,w,h=state['controls']['button']
    params=dict(task_id=task,action_id=uuid.uuid4().hex,action='click',native_id=n,args={'x':x+5,'y':y+5})
    service.dispatch('act',params,owner)
    assert service.dispatch('act',params,owner)['replayed']
    wait_state(session,lambda s:s['clicks']==1)
    with pytest.raises(DesktopError) as err:
        service.dispatch('act',dict(params,args={'x':x+8,'y':y+8}),owner)
    assert err.value.code=='idempotency_conflict'
    service.tasks[task].lock.acquire()
    try:
        with pytest.raises(DesktopError) as err:
            act(service,owner,task,'geometry',n)
        assert err.value.code=='busy'
    finally:service.tasks[task].lock.release()
    service.dispatch('close_task',{'task_id':task},owner)
    assert session.app.poll() is not None
    assert service.dispatch('close_task',{'task_id':task},owner)['cancelled']
    with pytest.raises(DesktopError) as err:
        act(service,owner,task,'geometry',n)
    assert err.value.code=='cancelled'
    assert service.dispatch('result',{'action_id':params['action_id']},owner)['status']=='succeeded'


def test_timeout_has_unknown_effect_and_new_target(service,owner):
    task,n,_=open_target(service,owner)
    ident=uuid.uuid4().hex
    with pytest.raises(DesktopError):
        service.dispatch('act',dict(task_id=task,native_id=n,action_id=ident,action='screenshot',timeout=.05),owner)
    status=service.dispatch('result',{'action_id':ident},owner)
    assert status['status']=='unknown'
    assert act(service,owner,task,'geometry',n)['result']['width']==640


def test_independent_tasks_and_drag_selection(service,owner):
    from concurrent.futures import ThreadPoolExecutor
    targets=[open_target(service,owner) for _ in range(2)]
    def fill(target):
        task,n,session=target
        act(service,owner,task,'click',n,{'x':40,'y':85})
        act(service,owner,task,'type',n,{'text':'Independent task'})
        return wait_state(session,lambda s:s['text']=='Independent task')
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(fill,targets)))==2
    assert targets[0][2].env['DISPLAY']!=targets[1][2].env['DISPLAY']
    task,n,session=targets[0]
    result=act(service,owner,task,'drag',n,{'x':16,'y':85,'end_x':140,'end_y':85})['result']
    assert result['pointer_unchanged']
    wait_state(session,lambda s:len(s['selection'])>0)


def test_cancel_interrupts_blocked_backend(service,owner):
    import os,signal,threading
    task,n,session=open_target(service,owner)
    os.kill(session.processes[0].pid,signal.SIGSTOP)  # Only our private Xvfb.
    outcomes=[]
    def blocked():
        try:act(service,owner,task,'geometry',n,timeout=10)
        except DesktopError as exc:outcomes.append(exc.code)
    worker=threading.Thread(target=blocked)
    worker.start()
    end=time.monotonic()+3
    while not service.tasks[task].lock.locked() and time.monotonic()<end:time.sleep(.01)
    service.dispatch('close_task',{'task_id':task},owner)
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert outcomes
    assert all(p.poll() is not None for p in session.processes)
