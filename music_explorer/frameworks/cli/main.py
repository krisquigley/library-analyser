"""Standalone music-explorer command-line entrypoint."""
import argparse

from music_analyzer.infrastructure.config import load_settings
from music_explorer.frameworks.explorer.server import create_server


def main(argv=None):
    parser = argparse.ArgumentParser(prog='music-explorer', description='Start the standalone read-only music explorer.')
    parser.add_argument('--config')
    parser.add_argument('--database')
    parser.add_argument('--host', default='127.0.0.1', help='Bind host; default 127.0.0.1.')
    parser.add_argument('--port', type=int, default=8765, help='Bind port; default 8765.')
    args = parser.parse_args(argv)
    if args.host != '127.0.0.1':
        parser.error('music-explorer binds 127.0.0.1 only in this local personal-use slice')
    overrides = {'config': args.config} if args.config else {}
    if args.database:
        overrides['database'] = args.database
    settings = load_settings(**overrides)
    server = create_server(settings.database, args.host, args.port)
    try:
        print(f'music-explorer serving read-only explorer on http://{args.host}:{args.port}/', flush=True)
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
