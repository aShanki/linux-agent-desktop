#!/usr/bin/env python3
"""Run a visible-in-observer Qt workflow without connecting to the user's display."""
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lad.protocol import request, DEFAULT_SOCKET

owner='local-demo-client'

def call(method, **params):
    value=request(method,params,owner=owner)
    if not value['ok']:
        raise SystemExit(value['error']['code']+': '+value['error']['message'])
    return value['data']

task=call('open_task',kind='qt')['task_id']
def act(action, native_id=None, **args):
    return call('act',task_id=task,action_id=uuid.uuid4().hex,action=action,native_id=native_id,args=args)

n=act('discover')['result']['windows'][0]['native_id']
act('click',n,x=100,y=85)
act('type',n,text='Background work. Your desktop stays yours.')
act('click',n,x=320,y=117)
act('screenshot',n)
DEFAULT_SOCKET.with_name('demo-task-id').write_text(task+'\n')
print('Task:',task)
print('Private observer:',DEFAULT_SOCKET.with_name('observer-url').read_text().strip())
print('Stop all demo tasks with: .venv/bin/lad revoke-all')
