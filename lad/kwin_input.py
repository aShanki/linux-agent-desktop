"""Retain input capabilities for the lifetime of an owned KWin session."""
import signal
from .kwin import PrivateBus, EmulatedInput
from .errors import DesktopError


def main():
    inputs = EmulatedInput(PrivateBus())

    def stop(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        print('ready', flush=True)
        while True:
            inputs.pump(.25)
    except DesktopError as exc:
        if exc.code != 'input_unavailable':
            raise
    finally:
        inputs.close()


if __name__ == '__main__':
    main()
