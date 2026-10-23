import argparse
import json
from pathlib import Path
from .protocol import DEFAULT_SOCKET, request


def main():
    parser = argparse.ArgumentParser(prog='lad')
    parser.add_argument('--socket', type=Path, default=DEFAULT_SOCKET)
    parser.add_argument('--observer-port', type=int, default=0)
    parser.add_argument('--owner', default='codex-linux-agent-desktop')
    parser.add_argument('command', choices=['serve','capabilities','revoke-all','attach-revu','sway-targets','attach-sway'])
    parser.add_argument('--native-id', type=int)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--consent-session', action='store_true', help='Grant exclusive use of the configured Sway session seat and visible capture for five minutes')
    args = parser.parse_args()
    if args.command == 'serve':
        from .service import serve
        serve(args.socket, args.observer_port)
    elif args.command in ('sway-targets','attach-sway'):
        params = {} if args.command == 'sway-targets' else dict(owner=args.owner, native_id=args.native_id, pid=args.pid, consent_session=args.consent_session)
        print(json.dumps(request('operator_sway_targets' if args.command == 'sway-targets' else 'operator_enroll_sway', params, owner='local-operator-0000', path=args.socket), indent=2))
    elif args.command == 'attach-revu':
        print(json.dumps(request('operator_enroll_revu', {'owner':args.owner},
                                 owner='local-operator-0000', path=args.socket),indent=2))
    else:
        print(json.dumps(request('operator_revoke_all' if args.command == 'revoke-all' else 'capabilities',
                                 owner='local-operator-0000', path=args.socket), indent=2))

if __name__ == '__main__':
    main()
