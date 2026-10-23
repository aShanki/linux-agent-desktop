"""CDP exclusively for our launched headless browser and fixture URL."""
import json
import os
import urllib.request
from pathlib import Path
from websockets.sync.client import connect
from .errors import DesktopError, require
from .protocol import ROOT


class Browser:
    def __init__(self):
        port = int(os.environ['LAD_CDP_PORT'])
        # Ignore HTTP proxy environment for a loopback-only owned endpoint.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/json/list', timeout=2) as response:
            pages = json.load(response)
        expected = (ROOT / 'lad/fixture.html').as_uri()
        targets = [p for p in pages if p.get('type') == 'page' and p.get('url') == expected]
        require(len(targets) == 1, 'stale_target', 'Owned fixture page is not available')
        target = targets[0]
        ws = target['webSocketDebuggerUrl']
        require(ws.startswith(f'ws://127.0.0.1:{port}/devtools/page/'), 'invalid_endpoint', 'Unexpected browser endpoint')
        self.ws = connect(ws, open_timeout=2, max_size=12*1024*1024, proxy=None)
        self.seq = 0
        self.target = target['id']
        self.dialog_open = False
        self.call('Page.enable')

    def call(self, method, params=None):
        self.seq += 1
        self.ws.send(json.dumps({'id': self.seq, 'method': method, 'params': params or {}}))
        while True:
            value = json.loads(self.ws.recv(timeout=3))
            if value.get('method') == 'Page.javascriptDialogOpening' and method.startswith('Input.'):
                self.dialog_open = True
                return {}
            if value.get('id') == self.seq:
                require('error' not in value, 'cdp_error', 'Browser rejected the requested operation')
                return value.get('result', {})

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
        require('exceptionDetails' not in result, 'stale_element', 'Element is no longer available')
        return result['result'].get('value')

    def execute(self, op):
        action = op['action']
        if action == 'discover':
            return {'windows': [{'native_id': self.target, 'title': 'LAD browser fixture', 'coordinate_space': 'CSS pixels'}]}
        require(op.get('native_id') == self.target, 'stale_target', 'Browser target changed')
        if action == 'screenshot':
            return {'png': self.call('Page.captureScreenshot', {'format': 'png', 'fromSurface': True})['data']}
        if action == 'tree':
            return {'nodes': self.evaluate("Array.from(document.querySelectorAll('button,input:not([type=password]),select')).map(e=>({element:e.id,role:e.tagName,name:e.getAttribute('aria-label')||e.textContent,rect:{x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.clientWidth,height:e.clientHeight}}))")}
        if action == 'geometry':
            return self.evaluate('({width:innerWidth,height:innerHeight,device_scale:devicePixelRatio,coordinate_space:"CSS pixels"})')
        if action == 'set_text':
            require(op.get('element') == 'message', 'protected_content', 'Only the dedicated fixture input is allowed')
            text = op.get('text')
            require(isinstance(text, str) and len(text) <= 4096, 'invalid_argument', 'Text must be at most 4096 characters')
            self.evaluate("document.getElementById('message').focus();document.getElementById('message').select()")
            self.call('Input.insertText', {'text': text})
        elif action in ('click', 'scroll', 'drag'):
            size = self.execute(dict(op, action='geometry'))
            def check(x, y):
                require(type(x) is int and type(y) is int and 0 <= x < size['width'] and 0 <= y < size['height'],
                        'out_of_bounds', 'Coordinates must be inside the viewport in CSS pixels')
            x, y = op.get('x'), op.get('y')
            check(x, y)
            if action == 'scroll':
                steps = op.get('steps', 1)
                require(type(steps) is int and 0 < abs(steps) <= 20, 'invalid_argument', 'Scroll steps must be nonzero and within 20')
                self.call('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': x, 'y': y, 'deltaX': 0, 'deltaY': steps*80})
            else:
                if action == 'drag':
                    check(op.get('end_x'), op.get('end_y'))
                self.call('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
                if action == 'drag':
                    for i in range(1, 11):
                        self.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x+(op['end_x']-x)*i/10,
                                  'y': y+(op['end_y']-y)*i/10, 'button': 'left', 'buttons': 1})
                    x, y = op['end_x'], op['end_y']
                self.call('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
        elif action == 'type':
            text = op.get('text')
            require(isinstance(text, str) and len(text) <= 4096, 'invalid_argument', 'Text must be at most 4096 characters')
            self.call('Input.insertText', {'text': text})
        elif action == 'key':
            require(op.get('modifier', 'none') in ('none', 'ctrl', 'shift', 'alt'), 'invalid_argument', 'Unknown modifier')
            keys = {'Return': ('Enter', 13), 'Tab': ('Tab', 9), 'Escape': ('Escape', 27),
                    'BackSpace': ('Backspace', 8), 'a': ('a', 65)}
            require(op.get('key') in keys, 'unsupported_key', 'Key not supported by the browser adapter')
            key, code = keys[op['key']]
            modifiers = {'none': 0, 'ctrl': 2, 'shift': 8, 'alt': 1}[op.get('modifier', 'none')]
            for t in ('keyDown', 'keyUp'):
                self.call('Input.dispatchKeyEvent', {'type': t, 'key': key, 'windowsVirtualKeyCode': code, 'modifiers': modifiers})
        elif action == 'dialog':
            require(type(op.get('accept')) is bool, 'invalid_argument', 'accept must be boolean')
            self.call('Page.handleJavaScriptDialog', {'accept': op['accept']})
        else:
            raise DesktopError('unsupported_action', 'Unsupported browser operation')
        return {'delivered': True, 'verified_effect': False, 'dialog_open': self.dialog_open, 'host_focus': 'unaffected: headless browser'}
