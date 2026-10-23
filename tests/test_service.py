import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from lad.protocol import request
from lad.service import Store

@pytest.fixture
def daemon(tmp_path):
    root=tmp_path/'daemon'
    socket=root/'service.sock'
    proc=subprocess.Popen([sys.executable,'-m','lad.cli','--socket',str(socket),'serve'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    end=time.monotonic()+8
    while not socket.exists() and time.monotonic()<end:
        if proc.poll() is not None:raise AssertionError(proc.stderr.read().decode())
        time.sleep(.05)
    assert socket.exists()
    yield proc,root,socket
    if proc.poll() is None:
        proc.terminate()
    proc.communicate(timeout=10)


def test_mcp_end_to_end(daemon):
    proc,root,socket=daemon
    async def run():
        params=StdioServerParameters(command=sys.executable,args=['-m','lad.mcp_server'],env={**os.environ,'LAD_SOCKET':str(socket)})
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as client:
                await client.initialize()
                tools=await client.list_tools()
                assert {t.name for t in tools.tools} >= {'desktop_tasks','desktop_open_task','desktop_screenshot'}
                value=await client.call_tool('desktop_capabilities',{})
                assert not value.isError
                task=await client.call_tool('desktop_open_task',{'kind':'qt'})
                task_id=task.structuredContent['task_id']
                found=await client.call_tool('desktop_discover',{'task_id':task_id,'action_id':uuid.uuid4().hex})
                n=found.structuredContent['result']['windows'][0]['native_id']
                image=await client.call_tool('desktop_screenshot',dict(task_id=task_id,action_id=uuid.uuid4().hex,native_id=n))
                assert image.content[0].type=='image'
                assert image.content[0].mimeType=='image/png'
                bad=await client.call_tool('desktop_action',dict(task_id=task_id,action_id=uuid.uuid4().hex,native_id=n,action='foreground'))
                assert bad.isError
                closed=await client.call_tool('desktop_close_task',{'task_id':task_id})
                assert not closed.isError
    asyncio.run(run())


def test_observer_auth_and_readonly(daemon):
    import urllib.request,urllib.error
    _,root,socket=daemon
    url=(root/'observer-url').read_text().strip()
    base,token=url.split('#')
    assert urllib.request.urlopen(base).status==200
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(base+'api/state')
    assert err.value.code==403
    req=urllib.request.Request(base+'api/state',headers={'Authorization':'Bearer '+token})
    assert 'tasks' in json.load(urllib.request.urlopen(req))
    req=urllib.request.Request(base+'api/state',headers={'Authorization':'Bearer '+token,'Origin':'https://evil.example'})
    with pytest.raises(urllib.error.HTTPError):urllib.request.urlopen(req)
    req=urllib.request.Request(base+'api/state',data=b'{}',headers={'Authorization':'Bearer '+token})
    with pytest.raises(urllib.error.HTTPError):urllib.request.urlopen(req)


def test_crash_recovery_preserves_action_status_and_kills_owned_process(daemon):
    proc,root,socket=daemon
    owner=uuid.uuid4().hex
    task=request('open_task',{'kind':'qt'},owner=owner,path=socket)['data']['task_id']
    ident=uuid.uuid4().hex
    found=request('act',{'task_id':task,'action_id':ident,'action':'discover'},owner=owner,path=socket)
    assert found['ok']
    manifest=json.loads((root/('task-'+task)/'processes.json').read_text())
    proc.kill();proc.communicate(timeout=5)
    restart=subprocess.Popen([sys.executable,'-m','lad.cli','--socket',str(socket),'serve'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        end=time.monotonic()+10
        while time.monotonic()<end:
            try:
                value=request('result',{'action_id':ident},owner=owner,path=socket)
                if value.get('ok'):break
            except OSError:pass
            time.sleep(.05)
        else:raise AssertionError('Daemon did not recover')
        assert value['data']['status']=='succeeded'
        from lad.session import process_start
        for entry in manifest:
            # Killed children can briefly remain zombies, but must not be running.
            path=Path(f"/proc/{entry['pid']}/stat")
            if path.exists() and process_start(entry['pid'])==entry['start']:
                assert path.read_text().rsplit(')',1)[1].split()[0]=='Z'
    finally:
        restart.terminate();restart.communicate(timeout=10)


def test_interrupted_store_record(tmp_path):
    path=tmp_path/'actions.db'
    store=Store(path)
    store.start('action-123','task','owner','click','digest')
    store.db.close()
    recovered=Store(path)
    assert recovered.get('action-123','owner')['status']=='interrupted'
    recovered.db.close()


def test_mcp_cancellation_reaches_daemon(monkeypatch):
    from lad import mcp_server
    import threading
    started=threading.Event()
    release=threading.Event()
    calls=[]
    def fake_request(method, params, **kwargs):
        calls.append(method)
        if method=='act':
            started.set();release.wait(3)
        if method=='cancel_task':release.set()
        return {'ok':True,'data':{}}
    monkeypatch.setattr(mcp_server,'request',fake_request)
    async def run():
        task=asyncio.create_task(mcp_server.call('act',task_id='task-owned'))
        await asyncio.to_thread(started.wait,2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    assert 'cancel_task' in calls
