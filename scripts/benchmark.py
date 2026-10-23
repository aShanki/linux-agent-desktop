#!/usr/bin/env python3
"""Repeat measured fixture actions; never reads the host desktop or application data."""
import json
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from lad.service import DesktopService


def main():
    results=[]
    with tempfile.TemporaryDirectory(prefix='lad-benchmark-') as directory:
        service=DesktopService(Path(directory)/'service')
        owner=uuid.uuid4().hex
        try:
            for kind in ('qt','gtk','browser','wayland-qt','wayland-gtk','wayland-canvas'):
                task=service.dispatch('open_task',{'kind':kind},owner)['task_id']
                def act(action,native_id=None,args=None):
                    start=time.perf_counter()
                    v=service.dispatch('act',dict(task_id=task,action_id=uuid.uuid4().hex,action=action,native_id=native_id,args=args or {}),owner)
                    return v['result'],(time.perf_counter()-start)*1000
                windows,_=act('discover')
                n=windows['windows'][0]['native_id']
                samples=[]
                for _ in range(10):
                    result,elapsed=act('screenshot',n)
                    assert result['png']
                    samples.append(elapsed)
                results.append({'backend':kind,'operation':'window_capture','runs':len(samples),'successes':len(samples),
                                'median_ms':round(statistics.median(samples),2),'max_ms':round(max(samples),2)})
                service.dispatch('close_task',{'task_id':task},owner)
        finally:service.close()
    print(json.dumps({'scope':'isolated fixtures only','results':results},indent=2))

if __name__=='__main__':main()
