"""Short-lived adapter process limits hangs and isolates display/bus environments."""
import json
import sys
from .errors import DesktopError


def main():
    try:
        op = json.load(sys.stdin)
        if op['kind'].startswith('wayland-'):
            from .kwin import KWin
            result=KWin(op['pid']).execute(op)
        elif op['kind'] == 'browser':
            from .browser import Browser
            result = Browser().execute(op)
        elif op['action'] in ('tree', 'set_text', 'invoke'):
            from .accessibility import Accessibility
            from .x11 import X11
            x = X11(op['pid'])
            x.window(op.get('native_id'))
            before = x.state()
            result = Accessibility(op['pid']).execute(op)
            from .errors import require
            after = x.state()
            result.update(isolated_display_focus_unchanged=before['focus'] == after['focus'],
                          pointer_unchanged=before['pointer'] == after['pointer'], host_input_isolated=True)
        else:
            from .x11 import X11
            result = X11(op['pid']).execute(op)
    except DesktopError as exc:
        result = {'error': {'code': exc.code, 'message': str(exc)}}
    except Exception:
        # Exception messages can include text payloads or DOM content. Never echo them.
        result = {'error': {'code': 'backend_failed', 'message': 'Adapter failed; no input content was logged'}}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
