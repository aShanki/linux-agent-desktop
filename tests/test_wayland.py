import base64
import io
import json
import subprocess
import sys
import time
import pytest
from PIL import Image
from conftest import act
from test_desktop import wait_state
from lad.errors import DesktopError


def open_native(service,owner,kind,scale=1,outputs=1):
    task=service.dispatch('open_task',{'kind':kind,'scale':scale,'outputs':outputs},owner)['task_id']
    scene=act(service,owner,task,'discover')['result']
    return task,scene['windows'][0]['native_id'],service.tasks[task].session,scene


@pytest.mark.parametrize('scale',[1,1.5,2])
def test_native_wayland_input_capture_scale_and_second_output(service,owner,scale):
    task,n,session,scene=open_native(service,owner,'wayland-qt',scale,2)
    assert len(scene['outputs'])==2
    assert scene['outputs'][1]['x']==1600
    shot=act(service,owner,task,'screenshot',n)['result']
    assert shot['scale']==scale
    im=Image.open(io.BytesIO(base64.b64decode(shot['png'])))
    assert im.size==(int(640*scale),int(440*scale))
    assert im.convert('RGB').getpixel((int(30*scale),int(30*scale)))==(36,85,170)
    act(service,owner,task,'click',n,{'x':80,'y':85})
    act(service,owner,task,'type',n,{'text':'Native Wayland 123'})
    wait_state(session,lambda s:s['text']=='Native Wayland 123')
    act(service,owner,task,'key',n,{'key':'a','modifier':'ctrl'})
    wait_state(session,lambda s:s['selection']=='Native Wayland 123')
    act(service,owner,task,'type',n,{'text':'Replace'})
    act(service,owner,task,'click',n,{'x':100,'y':116})
    wait_state(session,lambda s:s['clicks']==1 and s['text']=='Replace')
    act(service,owner,task,'scroll',n,{'x':200,'y':250,'steps':3})
    wait_state(session,lambda s:s['scroll']>0)


def test_native_wayland_dialog_and_drag(service,owner):
    task,n,session,_=open_native(service,owner,'wayland-qt')
    act(service,owner,task,'click',n,{'x':80,'y':85})
    act(service,owner,task,'type',n,{'text':'Drag Select'})
    act(service,owner,task,'drag',n,{'x':16,'y':85,'end_x':110,'end_y':85})
    wait_state(session,lambda s:len(s['selection'])>0)
    act(service,owner,task,'click',n,{'x':100,'y':415})
    wait_state(session,lambda s:s['dialogs']==1)
    scene=act(service,owner,task,'discover')['result']
    dialog=next(w for w in scene['windows'] if w['active'] and w['native_id']!=n)
    act(service,owner,task,'key',dialog['native_id'],{'key':'Escape'})
    wait_state(session,lambda s:s['dialogs']==0)


def test_covered_gtk_semantic_input_preserves_foreground_sentinel(service,owner):
    task,n,session,_=open_native(service,owner,'wayland-gtk')
    nodes=act(service,owner,task,'tree',n)['result']['nodes']
    entry=next(v for v in nodes if v['name']=='Message')
    button=next(v for v in nodes if v['name']=='Increment')
    baseline_image=Image.open(io.BytesIO(base64.b64decode(act(service,owner,task,'screenshot',n)['result']['png']))).convert('RGB')
    sentinel_file=session.directory/'sentinel.json'
    session.spawn([sys.executable,'-m','lad.sentinel',str(sentinel_file)])
    end=time.monotonic()+4
    while time.monotonic()<end:
        if sentinel_file.exists() and json.loads(sentinel_file.read_text())['active']:break
        time.sleep(.03)
    else:raise AssertionError('Sentinel did not become active')
    assert not act(service,owner,task,'discover')['result']['windows'][0]['active']
    with pytest.raises(DesktopError) as e:
        act(service,owner,task,'click',n,{'x':30,'y':60})
    assert e.value.code=='occluded_target'
    act(service,owner,task,'set_text',n,{'element':entry['element'],'text':'Background ✓'})
    act(service,owner,task,'invoke',n,{'element':button['element'],'name':'click'})
    wait_state(session,lambda s:s['text']=='Background ✓' and s['clicks']==1)
    assert not act(service,owner,task,'discover')['result']['windows'][0]['active']
    sentinel=json.loads(sentinel_file.read_text())
    assert sentinel=={'keys':0,'clicks':0,'active':True,'focus_losses':0}
    shot=act(service,owner,task,'screenshot',n)['result']
    im=Image.open(io.BytesIO(base64.b64decode(shot['png'])))
    assert im.size==(640,440)
    assert im.convert('RGB').crop((0,300,640,440)).tobytes()==baseline_image.crop((0,300,640,440)).tobytes(), 'Covered-window pixels differ from the baseline'


def test_kwin_backend_refuses_host_bus(monkeypatch):
    from lad.kwin import PrivateBus
    monkeypatch.delenv('LAD_ISOLATED_ROOT',raising=False)
    with pytest.raises(DesktopError) as e:PrivateBus()
    assert e.value.code=='unsafe_target'


def test_native_gtk_coordinate_input(service,owner):
    task,n,session,_=open_native(service,owner,'wayland-gtk')
    state=wait_state(session,lambda s:bool(s.get('controls')))
    for name in ('entry','button'):
        x,y,w,h=state['controls'][name]
        act(service,owner,task,'click',n,{'x':x+w//2,'y':y+h//2})
        if name=='entry':act(service,owner,task,'type',n,{'text':'Native GTK'})
    wait_state(session,lambda s:s['text']=='Native GTK' and s['clicks']==1)


def test_private_wayland_input_does_not_reach_other_display(service,owner):
    from test_desktop import open_target
    task0,n0,sentinel=open_target(service,owner,'qt')
    act(service,owner,task0,'click',n0,{'x':80,'y':85})
    baseline=json.loads(sentinel.state_file.read_text())
    task,n,session,_=open_native(service,owner,'wayland-qt')
    def sentinel_focus():
        p=subprocess.run([sys.executable,'-c','from lad.x11 import X11; import json; print(json.dumps(X11('+str(sentinel.app.pid)+').state()))'],env=sentinel.env,capture_output=True,text=True,check=True)
        return json.loads(p.stdout)
    before=sentinel_focus()
    act(service,owner,task,'click',n,{'x':80,'y':85})
    act(service,owner,task,'type',n,{'text':'Only the target gets input'})
    wait_state(session,lambda s:s['text']=='Only the target gets input')
    assert sentinel_focus()==before
    other=json.loads(sentinel.state_file.read_text())
    assert other['text']==baseline['text'] and other['clicks']==baseline['clicks']


def test_custom_painted_canvas_without_semantic_controls(service,owner):
    task,n,session,_=open_native(service,owner,'wayland-canvas')
    act(service,owner,task,'drag',n,{'x':100,'y':140,'end_x':420,'end_y':300})
    value=wait_state(session,lambda s:len(s['points'])>=5)
    assert value['clicks']==1
    assert abs(value['points'][-1][0]-420)<2 and abs(value['points'][-1][1]-300)<2
    act(service,owner,task,'type',n,{'text':'Canvas input'})
    wait_state(session,lambda s:s['text']=='Canvas input')
    act(service,owner,task,'scroll',n,{'x':250,'y':250,'steps':2})
    wait_state(session,lambda s:s['scroll']!=0)
    shot=act(service,owner,task,'screenshot',n)['result']
    im=Image.open(io.BytesIO(base64.b64decode(shot['png']))).convert('RGB')
    assert im.getpixel((100,140))==(220,40,79)
