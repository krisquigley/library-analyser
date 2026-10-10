"""Process-local, outward observation of owned diagnostic server requests.

Wrappers retain all reader policy and call original methods. Install only while
an owned server runs; never use with unrelated concurrent repository readers.
Socket write completion is not client receipt. One monotonic clock is used.
"""
from contextlib import contextmanager, ExitStack
from functools import wraps
from http import HTTPStatus
import itertools
import threading
import time
from urllib.parse import urlparse


from music_explorer.infrastructure import explorer_readonly as reader
from music_explorer.application.use_cases import explorer as use_cases
from music_explorer.frameworks.explorer import server as server_module


@contextmanager
def _replace(owner, name, value):
    original = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, original)



class ServerObservation:
    def __init__(self):
        self.local = threading.local()
        self.ids = itertools.count(1)
        self.requests = []
        self.lock = threading.Lock()

    @contextmanager
    def span(self, phase):
        context = getattr(self.local, 'context', None)
        if context is None:
            yield None
            return
        record = dict(phase=phase, start_ms=time.monotonic() * 1000,
                      end_ms=None, span_id=str(next(self.ids)),
                      parent_id=context['stack'][-1]['span_id'] if context['stack'] else None,
                      request_id=context['request_id'], thread_id=str(threading.get_ident()),
                      clock='monotonic', status='ok')
        context['spans'].append(record)
        context['stack'].append(record)
        try:
            yield record
        except StopIteration:
            # Cursor exhaustion is a completed fetch, not a failed reader.
            raise
        except BaseException:
            record['status'] = 'failed'
            raise
        finally:
            record['end_ms'] = time.monotonic() * 1000
            context['stack'].pop()

    def _wrapper(self, original, phase):
        @wraps(original)
        def wrapped(*args, **kwargs):
            with self.span(phase):
                return original(*args, **kwargs)
        return wrapped

    @contextmanager
    def installed(self):
        repository = reader.ReadOnlyExplorerSQLiteRepository
        with ExitStack() as patches:
            for name, phase in [('track_ids', 'membership'), ('read_track', 'selected_read'),
                                ('_validate_rows', 'validation_rows'),
                                ('_validate_graph_rows', 'validation_graph'),
                                ('_validate_graph_feature_rows', 'validation_evidence'),
                                ('_stage_from_payload', 'stage_decode')]:
                original = getattr(repository, name)
                wrapped = self._wrapper(original, phase)
                if name == '_validate_rows':
                    # Schema checks precede the first row-validation call in _validate.
                    row_wrapper = wrapped
                    def wrapped(*args, **kwargs):
                        schema = getattr(self.local, 'schema', None)
                        if schema is not None:
                            self.local.schema = None
                            schema.__exit__(None, None, None)
                        return row_wrapper(*args, **kwargs)
                patches.enter_context(_replace(repository, name, wrapped))
            original_validate = repository._validate
            @wraps(original_validate)
            def validate(*args, **kwargs):
                with self.span('validation'):
                    schema = self.span('validation_schema')
                    schema.__enter__()
                    self.local.schema = schema
                    try:
                        return original_validate(*args, **kwargs)
                    except BaseException as error:
                        if self.local.schema is schema:
                            self.local.schema = None
                            schema.__exit__(type(error), error, error.__traceback__)
                        raise
                    finally:
                        if self.local.schema is schema:
                            self.local.schema = None
                            schema.__exit__(None, None, None)
            patches.enter_context(_replace(repository, '_validate', validate))
            original_read = repository._read_track
            @wraps(original_read)
            def read_track(repo, db, *args, **kwargs):
                proxy = _StagePreflightConnection(db, self)
                try:
                    return original_read(repo, proxy, *args, **kwargs)
                except BaseException as error:
                    proxy.finish(type(error), error, error.__traceback__)
                    raise
                finally:
                    proxy.finish()
            patches.enter_context(_replace(repository, '_read_track', read_track))
            patches.enter_context(_replace(use_cases, '_map_track', self._wrapper(use_cases._map_track, 'mapping')))
            # _to_json recurses through its module global: observe the outer call only.
            original_json = server_module._to_json
            def to_json(value):
                if getattr(self.local, 'serializing', False):
                    return original_json(value)
                with self.span('dto_serialization'):
                    self.local.serializing = True
                    try:
                        return original_json(value)
                    finally:
                        self.local.serializing = False
            patches.enter_context(_replace(server_module, '_to_json', to_json))
            self._install_evidence(patches, repository)
            yield self

    def _install_evidence(self, patches, repository):
        original_rows = repository._iter_validated_graph_feature_rows
        original_chunks = repository._iter_graph_feature_evidence_payload_chunks
        original_json = reader.json
        observer = self

        def evidence_rows(*args, **kwargs):
            iterator = original_rows(*args, **kwargs)
            first = True
            try:
                while True:
                    self.local.evidence_active = True
                    if first:
                        first = False
                        preflight = self.span('validation_evidence_preflight')
                        preflight.__enter__()
                        self.local.evidence_preflight = preflight
                    try:
                        row = next(iterator)
                    except StopIteration:
                        return
                    except BaseException as error:
                        self._finish_evidence_preflight(type(error), error, error.__traceback__)
                        raise
                    finally:
                        self._finish_evidence_preflight()
                        self.local.evidence_active = False
                    yield row
            finally:
                iterator.close()

        def chunks(*args, **kwargs):
            iterator = original_chunks(*args, **kwargs)
            try:
                while True:
                    active = getattr(self.local, 'evidence_active', False)
                    if active:
                        self._finish_evidence_preflight()
                    try:
                        with (self.span('validation_evidence_fetch') if active else _no_span()):
                            cursor = next(iterator)
                    except StopIteration:
                        return
                    yield _EvidenceCursor(cursor, self) if active else cursor
            finally:
                iterator.close()

        class ReaderJSON:
            # Replace only reader's module reference, never shared json.loads.
            def loads(self, *args, **kwargs):
                with (observer.span('validation_evidence_decode')
                      if getattr(observer.local, 'evidence_active', False) else _no_span()):
                    return original_json.loads(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(original_json, name)

        original_payload = reader.validate_graph_feature_evidence_payload
        def payload(*args, **kwargs):
            with (self.span('validation_evidence_payload')
                  if getattr(self.local, 'evidence_active', False) else _no_span()):
                return original_payload(*args, **kwargs)

        patches.enter_context(_replace(repository, '_iter_validated_graph_feature_rows', evidence_rows))
        patches.enter_context(_replace(repository, '_iter_graph_feature_evidence_payload_chunks', chunks))
        patches.enter_context(_replace(reader, 'json', ReaderJSON()))
        patches.enter_context(_replace(reader, 'validate_graph_feature_evidence_payload', payload))

    def _finish_evidence_preflight(self, *error):
        preflight = getattr(self.local, 'evidence_preflight', None)
        if preflight is not None:
            self.local.evidence_preflight = None
            preflight.__exit__(*(error or (None, None, None)))

    def instrument_server(self, server):
        original = server.RequestHandlerClass
        observer = self
        class ObservedHandler(original):
            def _observed(self, method):
                route = urlparse(self.path).path
                if route.startswith('/api/tracks/') and route != '/api/tracks/summary':
                    route = '/api/tracks/:handle'
                context = dict(request_id=self.headers.get('X-Diagnostic-Request-ID') or str(next(observer.ids)), method=method,
                               route=route, spans=[], stack=[])
                observer.local.context = context
                try:
                    with observer.span('request'):
                        return getattr(super(), 'do_' + method)()
                finally:
                    observer.local.context = None
                    with observer.lock:
                        observer.requests.append(context)
            def do_GET(self):
                return self._observed('GET')
            def do_POST(self):
                return self._observed('POST')
            def _json(self, payload, status=HTTPStatus.OK):
                # Same packaged JSON options and HTTP operations, separated at
                # the otherwise fused dumps(...).encode(...) expression.
                with observer.span('dto_serialization'):
                    text = server_module.json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
                with observer.span('utf8_encoding') as span:
                    encoded = text.encode('utf-8')
                    span['bytes'] = len(encoded)
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                with observer.span('socket_write') as span:
                    span['scope'] = 'server_socket_write_not_client_receipt'
                    self.wfile.write(encoded)
                    # Failed sendall cannot establish a known body-byte count.
                    span['bytes'] = len(encoded)
        server.RequestHandlerClass = ObservedHandler
        return server

    def attach(self, requests, mode):
        remaining = list(self.requests)
        for request in requests:
            request['observer_mode'] = mode
            route = urlparse(request['url']).path
            if route.startswith('/api/tracks/') and route != '/api/tracks/summary':
                route = '/api/tracks/:handle'
            match = next((item for item in remaining
                          if item['request_id'] == request.get('request_id')
                          and item['method'] == request['method'] and item['route'] == route), None)
            request['server_spans'] = [] if match is None else match['spans']
            if match is not None:
                remaining.remove(match)


@contextmanager
def _no_span():
    yield


class _EvidenceCursor:
    """Time actual lazy fetch calls, never time the consumer's yield lifetime."""
    def __init__(self, cursor, observer):
        self.cursor, self.observer = cursor, observer
        self.iterator = iter(cursor)

    def __iter__(self):
        return self

    def __next__(self):
        with self.observer.span('validation_evidence_fetch'):
            return next(self.iterator)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class _StagePreflightConnection:
    """Observe original selected stage size query, drain and size checks.

    The span ends before the first payload SELECT; no payload is read by this
    adapter and the original size rejection runs unchanged inside the span.
    """
    def __init__(self, db, observer):
        self.db, self.observer, self.preflight = db, observer, None

    def execute(self, sql, *args, **kwargs):
        if sql.startswith('SELECT stage,') and ' FROM stages WHERE run_id=' in sql:
            self.preflight = self.observer.span('stage_preflight')
            self.preflight.__enter__()
        elif self.preflight is not None:
            # With zero stages, the next query is overrides, not payload.
            # Neither that query nor any payload belongs to size preflight.
            self.finish()
        return self.db.execute(sql, *args, **kwargs)

    def finish(self, *error):
        if self.preflight is not None:
            span, self.preflight = self.preflight, None
            span.__exit__(*(error or (None, None, None)))

    def __getattr__(self, name):
        return getattr(self.db, name)
