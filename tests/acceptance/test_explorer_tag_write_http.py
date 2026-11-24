"""Issue #132: the Explorer previews a tag write with GET and applies it with one approved POST.

Only BPM and key tags of the previewed files change; the analysis database is never written; the approval
works once, and only from the Explorer's own page.
"""
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if importlib.util.find_spec('mutagen') is None:
    raise unittest.SkipTest('mutagen is not installed in the dependency-free test environment')

from music_analyzer.application.dto.analysis import AudioSource, StageResult  # noqa: E402
from music_analyzer.application.dto.catalogue import TrackMetadata  # noqa: E402
from music_analyzer.application.use_cases.scan_library import ScanLibrary  # noqa: E402
from music_analyzer.infrastructure.filesystem.inventory import LocalInventory  # noqa: E402
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository  # noqa: E402
from music_explorer.application.ports.track_tags import OwnedTags  # noqa: E402
from music_explorer.frameworks.explorer.server import create_server  # noqa: E402
from music_explorer.infrastructure.track_tags import MutagenTrackTags  # noqa: E402
from tests.support.synthetic_tagged_audio import synthetic_flac, synthetic_mp3  # noqa: E402


class ExplorerTagWriteHTTPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        music = root / 'music'
        music.mkdir()
        self.mp3, self.flac = synthetic_mp3(music / 'one.mp3'), synthetic_flac(music / 'two.flac')
        self.database = root / 'analysis.sqlite'
        repository = SQLiteAnalysisRepository(str(self.database))
        probed = TrackMetadata(duration_seconds=200.0, duration_source='mutagen')
        reader = type('Reader', (), {'read': lambda self, path: probed})()
        files = ScanLibrary(LocalInventory(reader), repository).execute(str(music)).files
        self.ids = {Path(file.location).name: file.identity.track_id for file in files}
        for name, bpm, key in (('one.mp3', 123.6, 'A'), ('two.flac', 90.2, 'D')):
            run = repository.start(AudioSource('synthetic', self.ids[name]))
            repository.save_stage(run, StageResult('bpm', (), 'estimate', (('bpm', bpm), ('confidence', 3.0))))
            repository.save_stage(run, StageResult('key', (), 'estimate', (('key', key), ('scale', 'minor'),
                                                                             ('strength', 0.9))))
            repository.finish(run, 'completed', '')
        server = create_server(str(self.database), host='127.0.0.1', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.base = f'http://127.0.0.1:{server.server_port}'
        self.database_bytes = self.database.read_bytes()

    def preview(self, *names, **query):
        params = [('track', self.ids[name]) for name in names] + list(query.items())
        with urlopen(f'{self.base}/api/tag-write/preview?{urlencode(params)}', timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))

    def apply(self, body, origin='SELF', host=None):
        headers = {'Content-Type': 'application/json'}
        if origin is not None:
            headers['Origin'] = self.base if origin == 'SELF' else origin
        if host is not None:
            headers['Host'] = host
        request = Request(f'{self.base}/api/tag-write/apply', data=json.dumps(body).encode('utf-8'), headers=headers,
                          method='POST')
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode('utf-8'))

    def owned(self, path):
        return MutagenTrackTags().read_owned(str(path))

    def test_the_preview_shows_each_change_and_writes_nothing(self):
        before = (self.mp3.read_bytes(), self.flac.read_bytes())
        preview = self.preview('one.mp3', 'two.flac')
        self.assertTrue(preview['token'])
        self.assertEqual([
            {'file': 'one.mp3', 'field': 'bpm', 'current': None, 'proposed': '124', 'replaces': False},
            {'file': 'one.mp3', 'field': 'key', 'current': None, 'proposed': 'Am', 'replaces': False},
            {'file': 'two.flac', 'field': 'bpm', 'current': None, 'proposed': '90', 'replaces': False},
            {'file': 'two.flac', 'field': 'key', 'current': None, 'proposed': 'Dm', 'replaces': False},
        ], preview['changes'])
        self.assertEqual([], preview['skipped'])
        self.assertEqual(before, (self.mp3.read_bytes(), self.flac.read_bytes()))
        self.assertEqual(self.database_bytes, self.database.read_bytes())

    def test_an_approved_action_writes_the_tags_once_and_never_the_analysis_database(self):
        token = self.preview('one.mp3', 'two.flac')['token']
        status, report = self.apply({'token': token})
        self.assertEqual(200, status)
        self.assertEqual([{'file': 'one.mp3', 'status': 'written', 'detail': 'BPM 124, key Am'},
                          {'file': 'two.flac', 'status': 'written', 'detail': 'BPM 90, key Dm'}], report['outcomes'])
        self.assertIn('rescan', report['notice'])
        self.assertEqual((OwnedTags('124', 'Am'), OwnedTags('90', 'Dm')), (self.owned(self.mp3), self.owned(self.flac)))
        self.assertEqual(self.database_bytes, self.database.read_bytes())
        status, body = self.apply({'token': token})
        self.assertEqual((409, 'This approval has already been used: preview again'), (status, body['error']))

    def test_an_unknown_or_missing_token_or_a_stale_preview_writes_nothing(self):
        for body in ({'token': 'forged'}, {}, {'token': 7}):
            with self.subTest(body=body):
                status, reply = self.apply(body)
                self.assertEqual((409, 'This approval is unknown: preview again'), (status, reply['error']))
        token = self.preview('one.mp3')['token']
        MutagenTrackTags().write_owned(str(self.mp3), OwnedTags(key='Em'))
        status, reply = self.apply({'token': token})
        self.assertEqual(409, status)
        self.assertIn('changed since the preview', reply['error'])
        self.assertEqual(OwnedTags(None, 'Em'), self.owned(self.mp3))

    def test_an_apply_from_another_origin_or_host_is_refused_and_writes_nothing(self):
        token = self.preview('one.mp3')['token']
        for origin, host in (('http://evil.example', None), (None, None), ('null', None),
                             ('SELF', 'evil.example')):
            with self.subTest(origin=origin, host=host):
                status, reply = self.apply({'token': token}, origin=origin, host=host)
                self.assertEqual((403, 'Tags can only be written from the Explorer page'), (status, reply['error']))
        self.assertEqual(OwnedTags(), self.owned(self.mp3))
        self.assertEqual(200, self.apply({'token': token})[0])

    def test_an_invalid_preview_request_is_a_400_saying_why(self):
        for query, message in ((('policy', 'overwrite'),), 'fill-empty or replace-existing'), \
                ((('minimum_key_strength', 'strong'),), 'between 0 and 1'):
            with self.subTest(message=message):
                params = urlencode([('track', self.ids['one.mp3']), *query])
                with self.assertRaises(HTTPError) as caught:
                    urlopen(f'{self.base}/api/tag-write/preview?{params}', timeout=5)
                self.assertEqual(400, caught.exception.code)
                self.assertIn(message, json.loads(caught.exception.read().decode('utf-8'))['error'])


if __name__ == '__main__':
    unittest.main()
