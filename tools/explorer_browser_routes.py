"""Owned loopback public synthetic routes; never accepts an external target."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
from urllib.parse import urlsplit

ASSETS = Path(__file__).resolve().parents[1] / 'music_explorer/frameworks/explorer/assets'


class BoundedLoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, address):
        # Unexpected client disconnects never publish a filesystem traceback.
        pass


@contextmanager
def public_routes(fixture, scenario):
    release = threading.Event()
    counters = {'graph': 0, 'search': 0}
    selected = {'current_track_id': None, 'history': [], 'selection_epoch': 0}
    track = {'handle': 'public-00000', 'title': 'Public synthetic 70 node 00000',
             'artist': 'Public synthetic artist', 'display_label': 'Public synthetic 70 node 00000'}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, *args):
            pass

        def send(self, body, status=200, content_type='application/json', gzip=False):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            if gzip:
                self.send_header('Content-Encoding', 'gzip')
            self.end_headers()
            self.wfile.write(body)

        def json(self, value, status=200):
            self.send(json.dumps(value).encode(), status)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/mood-axis-graph':
                counters['graph'] += 1
                if scenario == 'graph-failure-retry' and counters['graph'] == 1:
                    return self.json({'error': 'Public synthetic graph failure'}, 503)
                # Deliberately hold *headers* too: pending detail is independently observable.
                if not release.wait(60):
                    return self.json({'error': 'Public synthetic timeout'}, 504)
                return self.send(fixture['encoded_body'], gzip=True)
            if path == '/api/state':
                return self.json(selected)
            if path == '/api/tracks/summary':
                counters['search'] += 1
                if scenario == 'search-failure' and counters['search'] == 1:
                    return self.json({'error': 'Public synthetic search failure'}, 503)
                tracks = [track]
                if scenario == 'latest-selection':
                    tracks.append(dict(track, handle='public-00001', title='Public synthetic 70 node 00001'))
                return self.json({'tracks': tracks, 'metadata': {}, 'next_cursor': None})
            if path in ('/api/tracks/public-00000', '/api/tracks/public-00001'):
                return self.json({'metadata': dict(track, handle=path.rsplit('/', 1)[1]), 'fields': {}})
            relative = 'index.html' if path == '/' else path.lstrip('/')
            asset = (ASSETS / relative).resolve()
            if not asset.is_relative_to(ASSETS) or not asset.is_file():
                return self.json({'error': 'Not found'}, 404)
            types = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css'}
            return self.send(asset.read_bytes(), content_type=types.get(asset.suffix, 'application/octet-stream'))

        def do_POST(self):
            if urlsplit(self.path).path != '/api/current':
                return self.json({'error': 'Not found'}, 404)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096:
                    raise ValueError('Invalid size')
                value = json.loads(self.rfile.read(size))
                if not isinstance(value, dict):
                    raise ValueError('Invalid input')
            except (ValueError, OSError):
                return self.json({'error': 'Invalid input'}, 400)
            allowed = ('public-00000', 'public-00001') if scenario == 'latest-selection' else ('public-00000',)
            if value.get('track_id') not in allowed:
                return self.json({'error': 'Invalid input'}, 400)
            selected['current_track_id'] = value['track_id']
            self.json(selected)

    server = BoundedLoopbackServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/', release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()
