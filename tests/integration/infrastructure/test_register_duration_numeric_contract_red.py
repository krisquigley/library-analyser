"""Public register must reject boolean duration before SQLite turns it into 1.0.

NaN/Inf normalization and duration eligibility are existing, separate policies;
this regression does not replace them with a blanket finite/positive rule.
"""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.explorer_readonly import ReadOnlyExplorerSQLiteRepository


class RegisterDurationNumericContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'analysis.sqlite'
        self.writer = SQLiteAnalysisRepository(str(self.path))
        self.root = '/synthetic/duration'
        self.files = tuple(self._file(suffix, seconds) for suffix, seconds in (('a', 180), ('b', 240)))
        self.assertEqual(self.writer.register(Inventory(self.root, self.files, (), True)), ())
        self.reader = ReadOnlyExplorerSQLiteRepository(str(self.path))
        self.ids = tuple(file.identity.track_id for file in self.files)
        self.assertEqual(tuple(self.writer.track_ids()), self.ids)
        self.revision = self.writer.source_revision()
        a, b = self.ids
        self.history_id = self.writer.replace_graph_snapshot(
            (ProjectionEdge(a, b, 0.25, 2),), 2, 'duration-historical',
            positioned_edges=(ProjectionEdge(a, b, 0.25, 2),), source_revision=self.revision,
        )
        self.current_id = self.writer.replace_graph_snapshot(
            (ProjectionEdge(a, b, 0.5, 2),), 2, 'duration-current',
            positioned_edges=(ProjectionEdge(a, b, 0.5, 2),), source_revision=self.revision,
        )
        self.assertNotEqual(self.history_id, self.current_id)
        self.assertEqual(self.writer.current_graph_snapshot(2, self.revision)['state'], 'ready')
        self.assertTrue(self.reader.current_graph_edges(2))
        self.assertTrue(self.reader.current_positioned_graph_edges(2))

    def _file(self, suffix, seconds, source='mutagen'):
        return ScannedFile(
            f'{self.root}/{suffix}.flac', FileIdentity(suffix * 64, 123), 17, 'flac',
            TrackMetadata(
                common=(('title', 'original-' + suffix),),
                tags=(('TITLE', ('original-' + suffix,)),), warnings=('baseline metadata',),
                duration_seconds=seconds, duration_source=source,
            ),
        )

    def _public_snapshot(self):
        return (
            tuple(self.writer.track_ids()),
            tuple(self.writer.read_track(track_id) for track_id in self.ids),
            tuple(self.writer.locations(track_id) for track_id in self.ids),
            self.writer.source_revision(),
            self.writer.current_graph_snapshot(2, self.revision),
            self.reader.metadata(),
            tuple(self.reader.track_ids()),
            tuple(self.reader.available_audio_paths()),
            tuple(self.reader.read_track(track_id) for track_id in self.ids),
            self.reader.current_graph_edges(2),
            self.reader.current_positioned_graph_edges(2),
        )

    def _persisted_snapshot(self):
        # Public SQLite API against the disposable test database, never a
        # repository private connection. Includes scan roots, unavailable
        # locations, both current mirrors and all retained build histories.
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            return '\n'.join(connection.iterdump())

    def _replacement_proposal(self):
        first = replace(
            self.files[0], location=f'{self.root}/replacement-a.flac', mtime_ns=23,
            metadata=replace(
                self.files[0].metadata,
                common=(('title', 'replacement title'),),
                tags=(('TITLE', ('replacement title',)),), warnings=('replacement metadata',),
            ),
        )
        malformed = self._file('c', True)
        self.assertNotIn(malformed.identity.track_id, self.ids)
        # The second identity is unseen: no trusted stored 180s evidence can
        # turn this into a duplicate-duration-conflict rejection instead.
        return Inventory(self.root, (first, malformed), (), True)

    def test_late_fresh_boolean_duration_rejected_atomically_then_valid_retry(self):
        proposal = self._replacement_proposal()
        malformed = proposal.files[1]
        public_before = self._public_snapshot()
        persisted_before = self._persisted_snapshot()
        with self.assertRaises(AnalysisError) as rejected:
            self.writer.register(proposal)
        detail = str(rejected.exception).lower()
        self.assertRegex(detail, r'duration|audio')
        self.assertRegex(detail, r'invalid|boolean|bool|numeric|number|persisted')
        self.assertEqual(self._persisted_snapshot(), persisted_before)
        self.assertEqual(self._public_snapshot(), public_before)
        # A fresh writer must still validate the persisted database normally.
        reopened = SQLiteAnalysisRepository(str(self.path))
        self.assertEqual(tuple(reopened.track_ids()), self.ids)
        with self.assertRaises(AnalysisError):
            reopened.read_track(malformed.identity.track_id)
        self._assert_valid_replacement(proposal)

    def test_valid_replacement_retry_control(self):
        self._assert_valid_replacement(self._replacement_proposal())

    def _assert_valid_replacement(self, proposal):
        reopened = SQLiteAnalysisRepository(str(self.path))
        first, malformed = proposal.files
        corrected = replace(malformed, metadata=replace(malformed.metadata, duration_seconds=300))
        missing = reopened.register(replace(proposal, files=(first, corrected)))
        self.assertEqual(missing, tuple(sorted(file.location for file in self.files)))
        self.assertEqual(reopened.read_track(self.ids[0]).metadata.common, first.metadata.common)
        self.assertEqual(reopened.locations(self.ids[0]), (first.location,))
        self.assertEqual(reopened.locations(self.ids[1]), ())
        stored = reopened.read_track(corrected.identity.track_id)
        self.assertEqual(stored.size, 123)
        self.assertEqual(stored.metadata.duration_seconds, 300)
        self.assertIn(corrected.identity.track_id, tuple(reopened.track_ids()))
        self.assertEqual(self.reader.read_track(corrected.identity.track_id).metadata.duration_seconds, 300)
        self.assertNotEqual(reopened.current_graph_snapshot(2, self.revision)['state'], 'ready')

    def test_duration_policy_controls_and_nonnegative_integer_identity_roundtrip(self):
        cases = (
            ('unknown', None, '', None, False),
            ('unverified', 180, 'tag', 180, False),
            ('zero', 0, 'mutagen', 0, False),
            ('overlong', 1201, 'mutagen', 1201, False),
            ('nan', float('nan'), 'mutagen', None, False),
            ('positive infinity', float('inf'), 'ffprobe', None, False),
            ('negative infinity', float('-inf'), 'mutagen', None, False),
            ('eligible integer duration', 180, 'ffprobe', 180, True),
        )
        for index, (label, seconds, source, expected, active) in enumerate(cases):
            with self.subTest(label=label):
                file = self._file(format(index, 'x'), seconds, source)
                # Zero size/mtime are valid integers, not malformed booleans.
                file = replace(file, identity=FileIdentity(file.identity.sha256, 0), mtime_ns=0)
                self.assertEqual(self.writer.register(Inventory(self.root + '/' + str(index), (file,), (), True)), ())
                reopened = SQLiteAnalysisRepository(str(self.path))
                stored = reopened.read_track(file.identity.track_id)
                self.assertEqual(stored.sha256, file.identity.sha256)
                self.assertEqual(stored.size, 0)
                self.assertEqual(stored.locations, (file.location,))
                self.assertEqual(stored.metadata.duration_seconds, expected)
                self.assertEqual(stored.metadata.duration_source, source)
                self.assertEqual(file.identity.track_id in tuple(reopened.track_ids()), active)
                self.assertEqual(self.reader.read_track(file.identity.track_id).metadata.duration_seconds, expected)


if __name__ == '__main__':
    unittest.main()
