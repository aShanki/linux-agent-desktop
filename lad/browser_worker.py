"""Keep the owned CDP connection alive across dialogs and sequential actions."""
import json
import sys
from .browser import Browser
from .errors import DesktopError


def main():
    browser = Browser()
    for line in sys.stdin:
        try:
            value = browser.execute(json.loads(line))
        except DesktopError as exc:
            value = {'error': {'code': exc.code, 'message': str(exc)}}
        except Exception:
            value = {'error': {'code': 'backend_failed', 'message': 'Owned browser connection failed'}}
        print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()
