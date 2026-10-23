#!/usr/bin/env python3
"""Export a credential-free animated replay of the dedicated demo for review."""
import json
import sys
import urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent.parent
link=(root/'.runtime/observer-url').read_text().strip()
base,token=link.split('#')
request=urllib.request.Request(base+'api/state',headers={'Authorization':'Bearer '+token})
state=json.load(urllib.request.urlopen(request,timeout=5))
assert state['tasks'], 'Run scripts/demo.py first'
# Only the known local-demo fixture belongs in the review artifact.
expected=(root/'.runtime/demo-task-id').read_text().strip()[:8]
state['tasks']=[task for task in state['tasks'] if task['id']==expected]
assert len(state['tasks'])==1, 'Run scripts/demo.py to create an exportable fixture'
html=(root/'lad/observer.html').read_text()
start=html.index('async function poll()')
end=html.index('</script>',start)
serialized=json.dumps(state).replace('<','\\u003c')
script='''state=DEMO_STATE;render();$('status').textContent='Recorded fixture · animated replay';
$('clock').textContent='REPLAY';$('actionpill').textContent='DEMO';
const positions=state.tasks[0].events.filter(e=>e.x!==undefined);let replayIndex=0;
if(positions.length){$('frame').addEventListener('load',()=>move(positions.at(-1)),{once:true});move(positions.at(-1))}
setInterval(()=>{if(positions.length)move(positions[replayIndex++%positions.length])},1800);
'''.replace('DEMO_STATE',serialized)
html=html[:start]+script+html[end:]
html=html.replace('Read-only observer','Recorded demo · read-only')
html=html.replace('<style>','<style>\nheader{display:none!important} main{padding:0!important} html,body{background:transparent!important} .grid{grid-template-columns:minmax(0,1fr)!important} aside{display:none!important} .topline{margin-top:12px} .stage{max-height:440px}\n')
(root/'artifacts').mkdir(exist_ok=True)
out=root/'.runtime/observer-demo.html'
out.write_text(html)
print(out)
