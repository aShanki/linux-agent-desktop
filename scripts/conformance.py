#!/usr/bin/env python3
"""Run independent whole-suite rounds and write an auditable, content-free report."""
import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser()
parser.add_argument('--rounds',type=int,default=3)
parser.add_argument('--suite',choices=('full','sway'),default='full')
args=parser.parse_args()
if not 1<=args.rounds<=10:raise SystemExit('rounds must be 1..10')
(root/'artifacts').mkdir(exist_ok=True)
(root/'.runtime').mkdir(exist_ok=True)
def source_digest():
    files=[root/'pyproject.toml']
    files.extend(p for directory in ('lad','tests','scripts') for p in (root/directory).rglob('*')
                 if p.is_file() and p.suffix in ('.py','.html','.c','.xml','.sh'))
    digest=hashlib.sha256()
    for p in sorted(files):digest.update(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes())
    return digest.hexdigest()

baseline=source_digest()
rounds=[]
for index in range(1,args.rounds+1):
    xml=root/'.runtime'/f'conformance-{index}.xml'
    log=root/'.runtime'/f'conformance-{index}.log'
    command=[sys.executable,'-m','pytest','-q','--junitxml='+str(xml)]
    environment=dict(os.environ)
    if args.suite=='sway':
        command.append('tests/test_sway.py')
        environment['LAD_TEST_SWAY']='1'
    with log.open('w') as out:
        proc=subprocess.run(command,cwd=root,env=environment,stdout=out,stderr=subprocess.STDOUT)
    tests=[]
    if xml.exists():
        for case in ET.parse(xml).iter('testcase'):
            status='passed'
            for name in ('failure','error','skipped'):
                if case.find(name) is not None:status=name
            tests.append({'name':case.get('name'),'suite':case.get('classname'),'status':status,'seconds':float(case.get('time',0))})
    unchanged=source_digest()==baseline
    code=proc.returncode if unchanged else 1
    rounds.append({'round':index,'exit_code':code,'source_unchanged':unchanged,'tests':tests})
    print(f'Round {index}: '+str(sum(t['status']=='passed' for t in tests))+'/'+str(len(tests))+' passed',flush=True)
    report={'source_sha256':baseline,'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'platform':platform.platform(),
            'python':platform.python_version(),'rounds':rounds,
            'suite':args.suite,
            'scope':('operator-enrolled dedicated Sway: real Mousepad, Wine Notepad and MCP, software renderer, two virtual outputs' if args.suite=='sway' else 'isolated X11, headless CDP, private KWin; Sway tests opt-in; Revu evidence separate'),
            'sway_real_apps_enabled':environment.get('LAD_TEST_SWAY')=='1',
            'unsupported':'unenrolled live apps, host compositor attachment other than dedicated Sway, universal compatibility'}
    (root/'artifacts'/('attachment-conformance.json' if args.suite=='sway' else 'conformance.json')).write_text(json.dumps(report,indent=2)+'\n')
    if code:
        print(log.read_text()[-8000:]);raise SystemExit(code)
