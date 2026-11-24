"""Tiny read-only localhost HTTP server for personal track journey exploration."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import re
from math import isfinite
import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from importlib import resources
from urllib.parse import parse_qs, unquote, urlparse

from music_explorer.application.use_cases.label_tracks.label_tracks import LabelTracks, TrackLabelRequestError
from music_explorer.application.dto.candidates import CandidateQuery, SelectionControlDto
from music_explorer.application.use_cases.candidates import SelectExplorerCandidates
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph, FilterMoodAxisGraph, GetExplorerTrackDetail, ListExplorerTracks, ListExplorerTrackSummaries
from music_explorer.application.use_cases.download_playlist.download_playlist import GenerateBpmGraphM3UPlaylist
from music_explorer.application.use_cases.preview_playlist.preview_playlist import PreviewPlaylist
from music_explorer.application.use_cases.list_saved_playlist_recipes import ListSavedPlaylistRecipes
from music_explorer.application.use_cases.load_saved_playlist_recipe import LoadSavedPlaylistRecipe
from music_explorer.domain.saved_playlist_recipe import saved_playlist_recipe_name
from music_explorer.interface_adapters.mood_axis_graph_http import to_compact_mood_axis_graph_http, to_indexed_mood_axis_graph_http
from music_explorer.interface_adapters.playlist_recipe_query import playlist_recipe_from_query
from music_explorer.application.use_cases.projection_artifacts import BuildLiveProjection, ProjectionArtifactError
from music_explorer.infrastructure.explorer_readonly import AnalysisError, ReadOnlyExplorerSQLiteRepository
from music_explorer.application.use_cases.apply_tag_write.apply_tag_write import ApplyTagWrite, TagWriteApprovalError
from music_explorer.application.use_cases.preview_tag_write.preview_tag_write import PreviewTagWrite
from music_explorer.infrastructure.event_bus import InProcessEventBus
from music_explorer.infrastructure.file_identity import Sha256FileIdentity
from music_explorer.infrastructure.tag_write_actions import InMemoryTagWriteActions
from music_explorer.infrastructure.taggable_tracks import ReadOnlyTaggableTracks
from music_explorer.infrastructure.track_tags import MutagenTrackTags
from music_explorer.interface_adapters.tag_write_http import (
    preview_request_from_query, tag_write_preview_to_http, tag_write_report_to_http)
from music_explorer.interface_adapters.track_labels_http import label_request_from_query, track_labels_to_http
from music_analyzer.application.dto.analysis import AnalysisError as AnalyzerAnalysisError

MAX_BODY = 64 * 1024

# Only fixed, public messages cross the ordinary read boundary. In particular,
# arbitrary ValueError text may contain a stored value or malformed request.
_READ_ERRORS = frozenset({
    'Not a supported music-analyzer analysis database',
    'Explorer database must already exist',
    'Refusing Mixxx-named or symlink database path',
    'Invalid explorer summary cursor',
    'Unknown explorer track',
    'Invalid stored metadata',
    'Invalid stored stage',
    'Oversized stored stage (16 MiB limit)',
    'Invalid stored graph feature evidence',
    'Oversized stored graph feature evidence (16 MiB limit)',
    'Unexpected analysis database rows',
    'Unexpected analysis database schema',
    'Analysis database error',
})
_REQUEST_ERRORS = frozenset({
    'Invalid explorer request',
    'Unknown explorer track',
    'Explorer list limit must be between 1 and 500 or all',
    'Explorer summary limit must be between 1 and 100',
    'Explorer summary query must be at most 200 characters',
    'Explorer summary query must not contain NUL characters',
    'Explorer summary order must be title, artist, or id',
    'Cursor paging is not supported for candidate selection',
    'Candidate limit must be between 1 and 500',
    'Unknown current track',
    'track_id is required',
    'selection_token must be an integer',
    'selection_epoch must be an integer',
    'selection_client_id must be a string',
    'selection_token, selection_epoch, and selection_client_id are required together',
    'JSON object required',
})


# Endpoints whose existing validation messages are fixed policy text authored in
# the application/domain (candidate controls, mood selection, playlist export).
# R1 keeps their 400 contract rather than redesigning those validation APIs.
_POLICY_VALIDATION_PATHS = frozenset({'/api/candidates', '/api/mood-axis-graph', '/api/playlists/m3u', '/api/playlists/preview',
                                      '/api/playlist-recipes', '/api/playlist-recipes/load',
                                      '/api/tag-write/preview'})
_FOREIGN_TAG_WRITE = 'Tags can only be written from the Explorer page'


def _request_integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError('Invalid explorer request') from None


def _request_length(value):
    length = _request_integer(value)
    if length < 0:
        raise ValueError('Invalid explorer request')
    return length


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
        self.history: list[str | None] = []
        self.selection_epoch = 0
        self._selection_tokens_by_client: dict[str, int] = {}
        self._lock = threading.Lock()

    def snapshot(self):
        with self._lock:
            return self.snapshot_unlocked()

    def set_current(
        self,
        track_id: str,
        selection_token: int | None = None,
        selection_epoch: int | None = None,
        selection_client_id: str | None = None,
    ):
        if not self.repository.contains_active_track(track_id):
            raise ValueError('Unknown explorer track')
        with self._lock:
            if not self._accept_selection_unlocked(selection_token, selection_epoch, selection_client_id):
                return self.snapshot_unlocked()
            if self.current_track_id != track_id:
                self.history.append(self.current_track_id)
            self.current_track_id = track_id
            return self.snapshot_unlocked()

    def _accept_selection_unlocked(
        self,
        selection_token: int | None,
        selection_epoch: int | None,
        selection_client_id: str | None,
    ):
        if selection_token is None and selection_epoch is None and selection_client_id is None:
            return True
        if selection_epoch != self.selection_epoch:
            return False
        previous_token = self._selection_tokens_by_client.get(selection_client_id, 0)
        if selection_token <= previous_token:
            return False
        self._selection_tokens_by_client[selection_client_id] = selection_token
        return True

    def snapshot_unlocked(self):
        return {
            'current_track_id': self.current_track_id,
            'history': list(self.history),
            'selection_epoch': self.selection_epoch,
        }

    def undo(self):
        with self._lock:
            if self.history:
                self.current_track_id = self.history.pop()
            self.selection_epoch += 1
            self._selection_tokens_by_client.clear()
            return self.snapshot_unlocked()

    def reset(self):
        with self._lock:
            self.current_track_id = None
            self.history.clear()
            self.selection_epoch += 1
            self._selection_tokens_by_client.clear()
            return self.snapshot_unlocked()


_STATIC_ASSETS = frozenset({'/style.css', '/vendor/3d-force-graph/3d-force-graph.min.js',
                            '/vendor/3d-force-graph/NOTICE'})
# The browser app's ES modules (#146): lower-case, hyphenated names under /app/, never `..`.
_APP_MODULE = re.compile(r'/app/(?:[a-z0-9-]+/)*[a-z0-9-]+\.js')

def _tag_write_use_cases(repository):
    tracks, track_tags, actions, events = (ReadOnlyTaggableTracks(repository), MutagenTrackTags(),
                                           InMemoryTagWriteActions(), InProcessEventBus())
    return (PreviewTagWrite(tracks, track_tags, actions, events),
            ApplyTagWrite(tracks, track_tags, Sha256FileIdentity(), actions, events))


def create_server(database_path: str, host: str = '127.0.0.1', port: int = 8765):
    repository = ReadOnlyExplorerSQLiteRepository(database_path)
    state = ExplorerState(repository)
    preview_tag_write, apply_tag_write = _tag_write_use_cases(repository)
    # One approved tag write at a time, so a token can never be spent twice by racing requests.
    tag_write_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'MusicAnalyzerExplorer/0.1'

        def do_GET(self):
            try:
                self._route_get()
            except Exception as error:
                self._failure(error)

        def do_POST(self):
            try:
                self._route_post()
            except RequestTooLarge as error:
                self._json({'error': str(error)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            except Exception as error:
                self._failure(error)

        def _failure(self, error):
            message = str(error)
            if isinstance(error, (AnalysisError, AnalyzerAnalysisError)) and message in _READ_ERRORS:
                return self._json({'error': message}, HTTPStatus.BAD_REQUEST)
            if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
                return self._json({'error': 'Invalid explorer request'}, HTTPStatus.BAD_REQUEST)
            if isinstance(error, TrackLabelRequestError):
                return self._json({'error': message}, HTTPStatus.BAD_REQUEST)
            if isinstance(error, TagWriteApprovalError):
                return self._json({'error': message}, HTTPStatus.CONFLICT)
            if isinstance(error, ProjectionArtifactError):
                # Fixed projection categories (stale, resource limit, shape).
                return self._json({'error': message}, HTTPStatus.BAD_REQUEST)
            if isinstance(error, ValueError):
                if message in _REQUEST_ERRORS:
                    return self._json({'error': message}, HTTPStatus.BAD_REQUEST)
                if urlparse(self.path).path in _POLICY_VALIDATION_PATHS:
                    return self._json({'error': message}, HTTPStatus.BAD_REQUEST)
            return self._json({'error': 'Explorer request failed'}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _route_get(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == '/':
                return self._asset('index.html', 'text/html; charset=utf-8')
            if path in _STATIC_ASSETS or _APP_MODULE.fullmatch(path):
                return self._asset(path[1:], 'text/javascript; charset=utf-8' if path.endswith('.js') else ('text/plain; charset=utf-8' if path.endswith('NOTICE') else 'text/css; charset=utf-8'))
            if path == '/api/state':
                return self._json(state.snapshot())
            if path == '/api/tracks':
                query = parse_qs(parsed.query)
                raw_limit = query.get('limit', ['100'])[0]
                limit = 'all' if raw_limit == 'all' else _request_integer(raw_limit)
                after = query.get('after', [None])[0]
                return self._json(_to_json(ListExplorerTracks(repository).execute(limit, after)))
            if path in ('/api/tracks/summary', '/api/track-summaries'):
                query = parse_qs(parsed.query)
                limit = _request_integer(query.get('limit', ['100'])[0])
                cursor = query.get('cursor', [None])[0]
                search = query.get('query', query.get('q', ['']))[0]
                order = query.get('order', ['title'])[0]
                return self._json(_to_json(ListExplorerTrackSummaries(repository).execute(limit, cursor, search, order)))
            if path.startswith('/api/tracks/'):
                track_id = unquote(path[len('/api/tracks/'):])
                return self._json(_to_json(GetExplorerTrackDetail(repository).execute(track_id)))
            if path == '/api/candidates':
                query = parse_qs(parsed.query)
                current = query.get('current', [state.current_track_id])[0]
                if current is None:
                    return self._json({'error': 'No current track'}, HTTPStatus.BAD_REQUEST)
                controls = _parse_controls(query.get('control', ()))
                limit = _request_integer(query.get('limit', ['50'])[0])
                result = SelectExplorerCandidates(repository).execute(CandidateQuery(current, controls, limit=limit))
                return self._json(_to_json(result))
            if path == '/api/projection':
                projection = BuildLiveProjection(repository).execute()
                return self._json(_to_json(projection))
            if path == '/api/playlists/m3u':
                recipe = playlist_recipe_from_query(parse_qs(parsed.query, keep_blank_values=True))
                result = GenerateBpmGraphM3UPlaylist(repository).execute(recipe)
                return self._m3u(result.content, result.warning)
            if path == '/api/playlists/preview':
                recipe = playlist_recipe_from_query(parse_qs(parsed.query, keep_blank_values=True))
                return self._json(_to_json(PreviewPlaylist(repository).execute(recipe)))
            if path == '/api/playlist-recipes':
                return self._json({'recipes': _to_json(ListSavedPlaylistRecipes(repository).execute())})
            if path == '/api/playlist-recipes/load':
                name = saved_playlist_recipe_name(parse_qs(parsed.query).get('name', [None])[0])
                return self._json(_to_json(LoadSavedPlaylistRecipe(repository).execute(name)))
            if path == '/api/track-labels':
                request = label_request_from_query(parse_qs(parsed.query, keep_blank_values=True))
                return self._json(track_labels_to_http(LabelTracks(repository).execute(request)))
            if path == '/api/tag-write/preview':
                preview = preview_tag_write.execute(
                    preview_request_from_query(parse_qs(parsed.query, keep_blank_values=True)))
                return self._json(tag_write_preview_to_http(preview))
            if path == '/api/mood-axis-graph':
                query = parse_qs(parsed.query)
                contract, contract_error = _parse_mood_axis_graph_contract(parsed.query)
                if contract_error:
                    return self._json({'error': contract_error}, HTTPStatus.BAD_REQUEST)
                mood = query.get('mood', [None])[0]
                graph = BuildMoodAxisGraph(repository).execute(mood)
                bpm_min = _optional_float(query.get('bpm_min', [None])[0])
                bpm_max = _optional_float(query.get('bpm_max', [None])[0])
                genres = tuple(g for g in query.get('genre', ()) if g)
                filtered = FilterMoodAxisGraph().execute(graph, bpm_min, bpm_max, genres)
                if contract == 'v2':
                    return self._json(to_compact_mood_axis_graph_http(filtered))
                if contract == 'v3':
                    return self._json(to_indexed_mood_axis_graph_http(filtered))
                return self._json(_to_json(filtered))
            return self._json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

        def _route_post(self):
            parsed = urlparse(self.path)
            if parsed.path == '/api/tag-write/apply':
                return self._apply_tag_write()
            if parsed.path not in {'/api/current', '/api/undo', '/api/reset'}:
                return self._json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)
            data = self._body()
            if parsed.path == '/api/current':
                track_id = data.get('track_id')
                if not isinstance(track_id, str):
                    raise ValueError('track_id is required')
                selection_token = data.get('selection_token')
                if selection_token is not None and not isinstance(selection_token, int):
                    raise ValueError('selection_token must be an integer')
                selection_epoch = data.get('selection_epoch')
                if selection_epoch is not None and not isinstance(selection_epoch, int):
                    raise ValueError('selection_epoch must be an integer')
                selection_client_id = data.get('selection_client_id')
                if selection_client_id is not None and not isinstance(selection_client_id, str):
                    raise ValueError('selection_client_id must be a string')
                has_protocol_field = selection_token is not None or selection_epoch is not None or selection_client_id is not None
                if has_protocol_field and (selection_token is None or selection_epoch is None or not selection_client_id):
                    raise ValueError('selection_token, selection_epoch, and selection_client_id are required together')
                snapshot = state.set_current(track_id, selection_token, selection_epoch, selection_client_id)
            elif parsed.path == '/api/undo':
                snapshot = state.undo()
            else:
                snapshot = state.reset()
            return self._json(snapshot)

        def _apply_tag_write(self):
            if not self._from_explorer_page():
                return self._json({'error': _FOREIGN_TAG_WRITE}, HTTPStatus.FORBIDDEN)
            token = self._body().get('token')
            with tag_write_lock:
                report = apply_tag_write.execute(token)
            return self._json(tag_write_report_to_http(report))

        def _from_explorer_page(self):
            # CSRF protection for a localhost server: only the Explorer's own page may approve a write.
            port = self.server.server_port
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            return (self.headers.get('Host') in hosts
                    and self.headers.get('Origin') in {f'http://{host}' for host in hosts})

        def _body(self):
            length = _request_length(self.headers.get('Content-Length', '0') or '0')
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
            asset = resources.files('music_explorer.frameworks.explorer.assets').joinpath(name)
            if not (name == 'index.html' or '/' + name in _STATIC_ASSETS or _APP_MODULE.fullmatch('/' + name)) or not asset.is_file():
                return self._json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)
            text = asset.read_text(encoding='utf-8')
            payload = text.encode('utf-8')
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _m3u(self, content: str, warning: str | None = None):
            safe_warning = _safe_playlist_warning(warning)
            if safe_warning:
                content = content.replace('#EXTM3U\n', f'#EXTM3U\n#PLAYLIST-WARNING: {safe_warning}\n', 1)
            encoded = content.encode('utf-8')
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'audio/x-mpegurl; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="library-graph-playlist.m3u"')
            if safe_warning:
                self.send_header('X-Music-Explorer-Playlist-Warning', safe_warning)
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

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


def _safe_playlist_warning(warning):
    if not warning:
        return None
    return ''.join(ch if ch not in '<>\r\n' and ord(ch) >= 32 and ord(ch) != 127 else ' ' for ch in str(warning)).strip()


def _parse_mood_axis_graph_contract(query_string):
    values = parse_qs(query_string, keep_blank_values=True).get('contract', [])
    if not values:
        return None, None
    if len(values) != 1:
        return None, 'Exactly one mood-axis-graph contract value is allowed'
    contract = values[0]
    if contract in {'v2', 'v3'}:
        return contract, None
    if contract == '':
        return None, 'Mood-axis-graph contract must not be blank'
    return None, f'Unsupported mood-axis-graph contract: {contract}'


def _parse_controls(values):
    if not values:
        return DEFAULT_CONTROLS
    controls = []
    for value in values:
        try:
            name, mode, weight, *rest = value.split(':')
            weight = float(weight or 0)
        except ValueError:
            raise ValueError('Invalid explorer request') from None
        controls.append(SelectionControlDto(name, mode, weight, _params(name, rest)))
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
