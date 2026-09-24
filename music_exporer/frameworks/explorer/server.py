"""Tiny read-only localhost HTTP server for personal track journey exploration."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from math import isfinite
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from importlib import resources
from urllib.parse import parse_qs, unquote, urlparse

from music_exporer.application.dto.candidates import CandidateQuery, SelectionControlDto
from music_exporer.application.use_cases.candidates import SelectExplorerCandidates
from music_exporer.application.use_cases.explorer import BuildMoodAxisGraph, FilterMoodAxisGraph, GetExplorerTrackDetail, ListExplorerTracks
from music_exporer.application.use_cases.projection_artifacts import _build_artifact
from music_exporer.domain.projection import ProjectionParameters
from music_exporer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository

MAX_BODY = 64 * 1024


class RequestTooLarge(Exception):
    pass


DEFAULT_CONTROLS = (
    SelectionControlDto('tempo', 'off', 1.0),
    SelectionControlDto('harmony', 'off', 1.0),
    SelectionControlDto('energy', 'off', 1.0),
    SelectionControlDto('genre', 'off', 1.0),
    SelectionControlDto('mood', 'off', 1.0),
)


class ExplorerState:
    def __init__(self, repository):
        self.repository = repository
        self.current_track_id = None
        self.history: list[str] = []

    def set_current(self, track_id: str):
        if track_id not in self.repository.track_ids():
            raise ValueError('Unknown explorer track')
        if self.current_track_id != track_id:
            self.history.append(self.current_track_id)
        self.current_track_id = track_id

    def undo(self):
        if self.history:
            self.current_track_id = self.history.pop()

    def reset(self):
        self.current_track_id = None
        self.history.clear()


def create_server(database_path: str, host: str = '127.0.0.1', port: int = 8765):
    repository = ReadOnlyExplorerSQLiteRepository(database_path)
    state = ExplorerState(repository)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'MusicAnalyzerExplorer/0.1'

        def do_GET(self):
            try:
                self._route_get()
            except Exception as error:  # small local tool: convert expected failures to JSON
                self._json({'error': str(error)}, HTTPStatus.BAD_REQUEST)

        def do_POST(self):
            try:
                self._route_post()
            except RequestTooLarge as error:
                self._json({'error': str(error)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            except ValueError as error:
                self._json({'error': str(error)}, HTTPStatus.BAD_REQUEST)
            except Exception as error:
                self._json({'error': str(error)}, HTTPStatus.BAD_REQUEST)

        def _route_get(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == '/':
                return self._asset('index.html', 'text/html; charset=utf-8')
            if path in {'/app.js', '/style.css', '/vendor/3d-force-graph/3d-force-graph.min.js', '/vendor/3d-force-graph/NOTICE'}:
                return self._asset(path[1:], 'text/javascript; charset=utf-8' if path.endswith('.js') else ('text/plain; charset=utf-8' if path.endswith('NOTICE') else 'text/css; charset=utf-8'))
            if path == '/api/state':
                return self._json({'current_track_id': state.current_track_id, 'history': list(state.history)})
            if path == '/api/tracks':
                query = parse_qs(parsed.query)
                raw_limit = query.get('limit', ['100'])[0]
                limit = 'all' if raw_limit == 'all' else int(raw_limit)
                after = query.get('after', [None])[0]
                return self._json(_to_json(ListExplorerTracks(repository).execute(limit, after)))
            if path.startswith('/api/tracks/'):
                track_id = unquote(path[len('/api/tracks/'):])
                return self._json(_to_json(GetExplorerTrackDetail(repository).execute(track_id)))
            if path == '/api/candidates':
                query = parse_qs(parsed.query)
                current = query.get('current', [state.current_track_id])[0]
                if current is None:
                    return self._json({'error': 'No current track'}, HTTPStatus.BAD_REQUEST)
                controls = _parse_controls(query.get('control', ()))
                limit = int(query.get('limit', ['50'])[0])
                result = SelectExplorerCandidates(repository).execute(CandidateQuery(current, controls, limit=limit))
                return self._json(_to_json(result))
            if path == '/api/projection':
                artifact = _build_artifact(repository, ProjectionParameters(10, False), None)
                return self._json(_to_json({'policy_versions': artifact['policy_versions'], 'tracks': artifact['tracks'], 'edges': artifact['edges']}))
            if path == '/api/mood-axis-graph':
                query = parse_qs(parsed.query)
                mood = query.get('mood', [None])[0]
                graph = BuildMoodAxisGraph(repository).execute(mood)
                bpm_min = _optional_float(query.get('bpm_min', [None])[0])
                bpm_max = _optional_float(query.get('bpm_max', [None])[0])
                genres = tuple(g for value in query.get('genre', ()) for g in value.split(',') if g)
                return self._json(_to_json(FilterMoodAxisGraph().execute(graph, bpm_min, bpm_max, genres)))
            return self._json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

        def _route_post(self):
            parsed = urlparse(self.path)
            if parsed.path not in {'/api/current', '/api/undo', '/api/reset'}:
                return self._json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)
            data = self._body()
            if parsed.path == '/api/current':
                track_id = data.get('track_id')
                if not isinstance(track_id, str):
                    raise ValueError('track_id is required')
                state.set_current(track_id)
            elif parsed.path == '/api/undo':
                state.undo()
            else:
                state.reset()
            return self._json({'current_track_id': state.current_track_id, 'history': list(state.history)})

        def _body(self):
            length = int(self.headers.get('Content-Length', '0') or '0')
            if length > MAX_BODY:
                raise RequestTooLarge('Request too large')
            raw = self.rfile.read(length) if length else b'{}'
            if not raw:
                return {}
            data = json.loads(raw.decode('utf-8'))
            if not isinstance(data, dict):
                raise ValueError('JSON object required')
            return data

        def _asset(self, name, content_type):
            if name not in {'index.html', 'app.js', 'style.css', 'vendor/3d-force-graph/3d-force-graph.min.js', 'vendor/3d-force-graph/NOTICE'}:
                return self._json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)
            text = resources.files('music_exporer.frameworks.explorer.assets').joinpath(name).read_text(encoding='utf-8')
            payload = text.encode('utf-8')
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, payload, status=HTTPStatus.OK):
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            return

    return ThreadingHTTPServer((host, port), Handler)


def _parse_controls(values):
    if not values:
        return DEFAULT_CONTROLS
    controls = []
    for value in values:
        name, mode, weight, *rest = value.split(':')
        controls.append(SelectionControlDto(name, mode, float(weight or 0), _params(name, rest)))
    return tuple(controls)


def _params(name, parts):
    params = {}
    for part in parts:
        if '=' in part:
            key, value = part.split('=', 1)
            try:
                value = float(value)
            except ValueError:
                pass
            params[key] = value
    return params


def _to_json(value):
    if is_dataclass(value):
        return {key: _to_json(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _to_json(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_to_json(item) for item in value]
    if isinstance(value, list):
        return [_to_json(item) for item in value]
    return value


def _optional_float(value):
    if value in (None, ''):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('Filter bound must be finite')
    if not isfinite(number):
        raise ValueError('Filter bound must be finite')
    return number
