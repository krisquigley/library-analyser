"""Public, bounded SQLite contract for visible Explorer summary search.

PR2 red boundary: AND over whitespace-separated literal tokens; each token may
match either visible title or visible artist. No query language or hidden JSON.
"""
import json
import tempfile
import unittest
from pathlib import Path

from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from tests.integration.infrastructure.test_standalone_explorer_readonly_repository import create_db


class ExplorerSummaryQueryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'synthetic.sqlite'
        self.db = create_db(self.path)
        self.addCleanup(self.db.close)
        self.repo = ReadOnlyExplorerSQLiteRepository(str(self.path))

    def add_track(self, number, title=None, artist=None, *, common=None,
                  tags=(), label=None, directory='public-fixture', audio='eligible',
                  available=True):
        digest = f'{number:064x}'
        handle = 'sha256:' + digest
        self.db.execute('INSERT INTO tracks VALUES(?,?,?)', (handle, digest, 10))
        if audio == 'eligible':
            audio_values = (120.0, 'mutagen', audio, '')
        elif audio == 'excluded':
            audio_values = (0.0, 'mutagen', audio, 'duration invalid; excluded from active library until mutagen/ffprobe verifies a positive finite duration; rescan audio metadata')
        else:
            audio_values = (None, 'mutagen', audio, 'duration unverified; excluded from active library until mutagen/ffprobe verifies duration; rescan audio metadata')
        self.db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)', (handle, *audio_values))
        if label is not None:
            self.db.execute('INSERT INTO locations VALUES(?,?,?,?,?)',
                            (f'/{directory}/{label}', handle, 1, 'flac', int(available)))
        if common is None:
            common = []
            if title is not None:
                common.append(('title', title))
            if artist is not None:
                common.append(('artist', artist))
        self.db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)',
                        (handle, json.dumps(common), json.dumps(tags), '[]'))
        return handle

    def page(self, query='', *, limit=20, cursor=None, order='title'):
        self.db.commit()
        return self.repo.list_track_summaries(limit, query=query, cursor=cursor, order=order)

    def assert_matches(self, query, expected):
        _metadata, count, rows, cursor = self.page(query, order='id')
        self.assertEqual(count, len(expected))
        self.assertEqual(tuple(row.handle for row in rows), tuple(expected))
        self.assertIsNone(cursor)

    def test_tokens_can_match_across_title_and_artist_in_either_order(self):
        wanted = self.add_track(1, 'Northern Lights', 'River Ensemble')
        self.add_track(2, 'Northern Lights', 'Other Ensemble')
        self.add_track(3, 'Other Song', 'River Ensemble')
        for query in ('northern river', 'river northern'):
            with self.subTest(query=query):
                self.assert_matches(query, (wanted,))

    def test_tokens_in_one_field_need_not_be_adjacent_or_in_query_order(self):
        wanted = self.add_track(1, 'Northern Quiet Lights', 'Elsewhere')
        self.add_track(2, 'Northern Quiet', 'Elsewhere')
        for query in ('northern lights', 'lights northern'):
            with self.subTest(query=query):
                self.assert_matches(query, (wanted,))

    def test_whitespace_separates_tokens_including_tabs_newlines_and_unicode(self):
        wanted = self.add_track(1, 'Northern Lights', 'River Ensemble')
        for query in ('  northern   river  ', 'northern\triver', 'northern\nriver', 'northern\u2003river'):
            with self.subTest(query=query):
                self.assert_matches(query, (wanted,))

    def test_multivalued_artist_and_unicode_casefold_work_across_fields(self):
        wanted = self.add_track(1, 'Straße Lights', ['Änne', 'River'])
        self.add_track(2, 'Straße Lights', ['Elsewhere'])
        self.assert_matches('STRASSE ÄNNE', (wanted,))

    def test_literal_backslash_is_not_an_escape_or_a_wildcard(self):
        wanted = self.add_track(1, r'Road\Mix')
        self.add_track(2, 'RoadMix')
        self.add_track(3, 'RoadAnythingMix')
        self.assert_matches(r'Road\Mix', (wanted,))

    def test_literal_backslash_before_percent_and_underscore(self):
        wanted = self.add_track(1, r'Rate\%\_Mix')
        self.add_track(2, 'Rate%_Mix')
        self.add_track(3, r'Rate\anything\ZMix')
        self.assert_matches(r'Rate\%\_Mix', (wanted,))

    # Passing controls preserve behavior rather than pretending it is missing.
    def test_percent_and_underscore_are_literal_substrings(self):
        wanted = self.add_track(1, '100%_Mix')
        self.add_track(2, '100XYZMix')
        self.assert_matches('100%_Mix', (wanted,))

    def test_single_token_title_artist_and_unicode_casefold(self):
        wanted = self.add_track(1, 'Straße Lights', ['Änne', 'River'])
        self.add_track(2, 'Other Song', 'Elsewhere')
        for query in ('STRASSE', 'ÄNNE', 'river'):
            with self.subTest(query=query):
                self.assert_matches(query, (wanted,))

    def test_matches_are_active_only_without_changing_location_eligibility(self):
        eligible = self.add_track(1, 'Beacon', audio='eligible')
        unavailable = self.add_track(2, 'Beacon', label='Unavailable.flac', available=False)
        self.add_track(3, 'Beacon', audio='excluded')
        self.add_track(4, 'Beacon', audio='unknown')
        self.assert_matches('beacon', (eligible, unavailable))

    def test_common_metadata_precedes_tags_and_filename(self):
        wanted = self.add_track(1, 'Visible', ['First', 'Second'],
                                tags=(('title', ['HiddenTag']), ('artist', ['HiddenArtist'])),
                                label='HiddenFilename.flac')
        for query in ('visible', 'second'):
            with self.subTest(query=query):
                self.assert_matches(query, (wanted,))
        for query in ('HiddenTag', 'HiddenArtist', 'HiddenFilename'):
            with self.subTest(query=query):
                self.assert_matches(query, ())

    def test_title_falls_back_to_tags_then_filename_then_id(self):
        tag = self.add_track(1, common=(('title', ''),), tags=(('title', ['Tag Title']),))
        filename = self.add_track(2, label='FilenameFallback.flac')
        handle = self.add_track(3)
        self.assert_matches('tag', (tag,))
        self.assert_matches('filenamefallback', (filename,))
        self.assert_matches(handle, (handle,))
        self.assert_matches('unknown', ())  # UI placeholder is not artist evidence.

    def test_path_directories_unrelated_json_keys_and_values_do_not_match(self):
        self.add_track(1, 'Visible', 'Artist', directory='SecretDirectory', label='Public.flac',
                       common=(('title', 'Visible'), ('artist', 'Artist'), ('SecretKey', 'SecretValue')),
                       tags=(('comment', ['SecretComment']),))
        for query in ('SecretDirectory', 'SecretKey', 'SecretValue', 'SecretComment', 'comment'):
            with self.subTest(query=query):
                self.assert_matches(query, ())

    def test_blank_query_and_stable_keyset_pages_keep_count_and_id_ties(self):
        # Deliberately insert in a different order from the expected ID tie-break.
        third = self.add_track(3, 'ALPHA', 'SAME')
        first = self.add_track(1, 'Alpha', 'Same')
        second = self.add_track(2, 'alpha', 'same')
        for query in ('', '   ', 'alpha'):
            for order in ('title', 'artist', 'id'):
                with self.subTest(query=query, order=order):
                    handles, cursor = [], None
                    for page_number in range(3):
                        _metadata, count, rows, cursor = self.page(query, limit=1, cursor=cursor, order=order)
                        self.assertEqual(count, 3)
                        self.assertEqual(len(rows), 1)
                        handles.append(rows[0].handle)
                        if page_number < 2:
                            self.assertIsNotNone(cursor)
                        else:
                            self.assertIsNone(cursor)
                    self.assertEqual(handles, [first, second, third])


if __name__ == '__main__':
    unittest.main()
