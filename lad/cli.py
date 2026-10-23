import argparse
import json
from pathlib import Path
from .protocol import DEFAULT_SOCKET, request


def main():
    parser = argparse.ArgumentParser(prog='lad')
    parser.add_argument('--socket', type=Path, default=DEFAULT_SOCKET)
    parser.add_argument('--observer-port', type=int, default=0)
    parser.add_argument('--owner', default='codex-linux-agent-desktop')
    parser.add_argument('command', choices=['serve','capabilities','revoke-all','attach-revu'])
    args = parser.parse_args()
    if args.command == 'serve':
        from .service import serve
        serve(args.socket, args.observer_port)
    elif args.command == 'attach-revu':
        print(json.dumps(request('operator_enroll_revu', {'owner':args.owner},
                                 owner='local-operator-0000', path=args.socket),indent=2))
    else:
        print(json.dumps(request('operator_revoke_all' if args.command == 'revoke-all' else 'capabilities',
                                 owner='local-operator-0000', path=args.socket), indent=2))

if __name__ == '__main__':
    main()
