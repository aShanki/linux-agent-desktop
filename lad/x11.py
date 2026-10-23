"""Window-directed XSendEvent, never XTest, focus changes, or pointer warps."""
import base64
import io
import time
from Xlib import X, XK, display, protocol
from PIL import Image
from .errors import DesktopError, require


class X11:
    def __init__(self, pid):
        self.d = display.Display()
        self.pid = pid
        self.root = self.d.screen().root

    def discover(self):
        result = []
        def walk(parent, depth=0):
            if depth > 8:
                return
            for w in parent.query_tree().children:
                prop = w.get_full_property(self.d.intern_atom('_NET_WM_PID'), X.AnyPropertyType)
                if prop and int(prop.value[0]) == self.pid:
                    if w.get_attributes().map_state == X.IsViewable:
                        g = w.get_geometry()
                        result.append({'native_id': w.id, 'title': w.get_wm_name() or '',
                                       'pid': self.pid, 'width': g.width, 'height': g.height,
                                       'coordinate_space': 'window physical pixels'})
                else:
                    walk(w, depth+1)
        walk(self.root)
        return {'windows': result}

    def window(self, xid):
        require(isinstance(xid, int), 'invalid_target', 'A discovered native_id is required')
        w = self.d.create_resource_object('window', xid)
        prop = w.get_full_property(self.d.intern_atom('_NET_WM_PID'), X.AnyPropertyType)
        require(prop is not None and int(prop.value[0]) == self.pid, 'stale_target', 'Window identity no longer matches owned process')
        require(w.get_attributes().map_state == X.IsViewable, 'not_viewable', 'Window is not viewable')
        return w

    def state(self):
        f = self.d.get_input_focus().focus
        p = self.root.query_pointer()
        return {'focus': f if isinstance(f, int) else f.id, 'pointer': [p.root_x, p.root_y], 'buttons': p.mask}

    def geometry(self, w):
        g = w.get_geometry()
        p = self.root.translate_coords(w, 0, 0)
        return {'x': p.x, 'y': p.y, 'width': g.width, 'height': g.height,
                'coordinate_space': 'window physical pixels', 'depth': g.depth}

    def event(self, w, cls, x=0, y=0, detail=0, state=0):
        position = self.root.translate_coords(w, x, y)
        ev = cls(time=X.CurrentTime, root=self.root, window=w, child=X.NONE,
                 root_x=position.x, root_y=position.y, event_x=x, event_y=y,
                 state=state, detail=detail, same_screen=1)
        w.send_event(ev, propagate=False, event_mask=0)
        self.d.sync()

    def click(self, w, x, y, button=1):
        self.event(w, protocol.event.ButtonPress, x, y, button)
        self.event(w, protocol.event.ButtonRelease, x, y, button)

    def key(self, w, name, modifiers=0):
        keysym = ord(name) if isinstance(name, str) and len(name) == 1 else XK.string_to_keysym(name)
        require(bool(keysym), 'unsupported_key', 'Unknown X11 key symbol')
        keycode = self.d.keysym_to_keycode(keysym)
        require(keycode != 0, 'unsupported_key', 'Key not present in this display keymap')
        pairs = self.d.keysym_to_keycodes(keysym)
        index = next((idx for code, idx in pairs if code == keycode), 0)
        require(index in (0, 1), 'unsupported_key', 'Key requires an unsupported keyboard group')
        modifiers |= X.ShiftMask if index == 1 else 0
        self.event(w, protocol.event.KeyPress, detail=keycode, state=modifiers)
        self.event(w, protocol.event.KeyRelease, detail=keycode, state=modifiers)

    def execute(self, op):
        action = op['action']
        if action == 'discover':
            return self.discover()
        w = self.window(op.get('native_id'))
        before = self.state()
        result = {}
        if action == 'geometry':
            result = self.geometry(w)
        elif action == 'screenshot':
            g = w.get_geometry()
            require(g.depth == 24, 'unsupported_visual', 'Capture currently requires a 24-bit TrueColor visual')
            frame = w.get_image(0, 0, g.width, g.height, X.ZPixmap, 0xffffffff)
            require(frame is not None, 'capture_failed', 'Window capture failed')
            # Xvfb uses little-endian 32-bit BGRX with a 24-bit visual.
            require(self.d.display.info.image_byte_order == X.LSBFirst, 'unsupported_visual', 'Unsupported image byte order')
            im = Image.frombytes('RGB', (g.width, g.height), frame.data, 'raw', 'BGRX', 0, 1)
            data = io.BytesIO()
            im.save(data, format='PNG')
            result = {'png': base64.b64encode(data.getvalue()).decode(), 'width': g.width, 'height': g.height}
        elif action in ('click', 'scroll', 'drag'):
            g = w.get_geometry()
            def point(x, y):
                require(isinstance(x, int) and isinstance(y, int) and 0 <= x < g.width and 0 <= y < g.height,
                        'out_of_bounds', 'Coordinates must be inside the window in physical pixels')
            x, y = op.get('x'), op.get('y')
            point(x, y)
            if action == 'click':
                self.click(w, x, y)
            elif action == 'scroll':
                raise DesktopError('unsupported_action', 'Qt rejected directed wheel events in validation; use the CDP backend or explicit navigation keys')
            else:
                ex, ey = op.get('end_x'), op.get('end_y')
                point(ex, ey)
                self.event(w, protocol.event.ButtonPress, x, y, 1)
                for i in range(1, 11):
                    self.event(w, protocol.event.MotionNotify, x+(ex-x)*i//10, y+(ey-y)*i//10, state=X.Button1Mask)
                self.event(w, protocol.event.ButtonRelease, ex, ey, 1)
            result = {'delivered': True, 'verified_effect': False}
        elif action == 'type':
            text = op.get('text')
            require(isinstance(text, str) and 0 < len(text) <= 4096 and text.isascii() and text.isprintable(),
                    'unsupported_text', 'XSendEvent typing supports printable ASCII up to 4096 characters; use semantic input for Unicode')
            # Validate the entire string before any event is delivered.
            for ch in text:
                require(self.d.keysym_to_keycode(ord(ch)) != 0, 'unsupported_text', 'Character is absent from keyboard map')
            for ch in text:
                name = XK.keysym_to_string(ord(ch)) or ch
                self.key(w, name)
            result = {'delivered': True, 'verified_effect': False}
        elif action == 'key':
            modifiers = {'none': 0, 'ctrl': X.ControlMask, 'shift': X.ShiftMask, 'alt': X.Mod1Mask}
            require(op.get('modifier', 'none') in modifiers, 'invalid_argument', 'Unknown modifier')
            self.key(w, op.get('key', ''), modifiers[op.get('modifier', 'none')])
            result = {'delivered': True, 'verified_effect': False}
        else:
            raise DesktopError('unsupported_action', 'This X11 action is not implemented')
        time.sleep(.04)
        after = self.state()
        return dict(result, isolated_display_focus_unchanged=before['focus'] == after['focus'],
                    pointer_unchanged=before['pointer'] == after['pointer'], host_input_isolated=True)
