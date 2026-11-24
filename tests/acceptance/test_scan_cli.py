import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from music_analyzer.application.dto.analysis import AnalysisReport
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.frameworks.cli.main import main


class ScanCLITests(unittest.TestCase):
    def test_scan_then_analyze_track_and_stale_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'selected'
            root.mkdir()
            audio = root / '日本語.flac'
            audio.write_bytes(b'temporary fixture not real inference')
            database = str(Path(tmp) / 'analysis.sqlite')
            out = io.StringIO()
            with patch('music_analyzer.frameworks.cli.main.MutagenMetadataReader.read', return_value=TrackMetadata(duration_seconds=120.0, duration_source='mutagen')):
                with contextlib.redirect_stdout(out):
                    self.assertEqual(main(['scan', str(root), '--database', database, '--json']), 0)
            track = json.loads(out.getvalue())['files'][0]['track_id']
            with patch('music_analyzer.frameworks.cli.main.build_analysis') as build:
                build.return_value.execute.return_value = AnalysisReport('run', 'completed', ())
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['analyze', '--track', track, '--database', database]), 0)
                self.assertEqual(build.return_value.execute.call_args.args[0].location, str(audio))
                audio.write_bytes(b'changed')
                build.reset_mock()
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(main(['analyze', '--track', track, '--database', database, '--json']), 1)
                build.assert_not_called()
                self.assertIn('scan', json.loads(out.getvalue())['detail'])

    def test_scan_partial_and_setup_errors_are_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'
            root.mkdir()
            (root / 'large.mp3').write_bytes(b'12345')
            for selected in (root, root / 'absent'):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(main(['scan', str(selected), '--max-file-bytes', '2', '--database', str(Path(tmp) / 'db'), '--json']), 1)
                self.assertTrue(json.loads(out.getvalue())['issues'])

    def test_track_and_file_are_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['analyze', '--file', 'x', '--track', 'id'])


class TagsOnlyRescanCLITests(unittest.TestCase):
    """#223: a rescan after a tags-only change keeps the track's analysis and overrides, and says so."""

    def scan(self, root, database, *extra):
        out = io.StringIO()
        with patch('music_analyzer.frameworks.cli.main.MutagenMetadataReader.read',
                   return_value=TrackMetadata(duration_seconds=120.0, duration_source='mutagen')):
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(['scan', str(root), '--database', database, *extra]), 0)
        return out.getvalue()

    def test_a_rescan_reports_the_tracks_whose_tags_changed_and_keeps_their_overrides(self):
        from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
        from tests.support.synthetic_tagged_audio import MP3_AUDIO, with_id3v2
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'selected'
            root.mkdir()
            song = root / 'song.mp3'
            song.write_bytes(with_id3v2(MP3_AUDIO, b'first' + bytes(20)))
            database = str(Path(tmp) / 'analysis.sqlite')
            old = json.loads(self.scan(root, database, '--json'))['files'][0]['track_id']
            SQLiteAnalysisRepository(database).set_override(old, 'bpm', '124')
            song.write_bytes(with_id3v2(MP3_AUDIO, b'retagged' + bytes(50)))
            report = json.loads(self.scan(root, database, '--json'))
            new = report['files'][0]['track_id']
            self.assertEqual(report['carried_over'], [{'predecessor_id': old, 'successor_id': new}])
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('SELECT track_id,field,value FROM overrides').fetchall(), [(new, 'bpm', '124')])
            text = self.scan(root, database)
            self.assertIn('0 tracks kept their analysis after a tags-only change', text)
            song.write_bytes(with_id3v2(MP3_AUDIO, b'third tags' + bytes(70)))
            text = self.scan(root, database)
            self.assertIn('1 track kept its analysis after a tags-only change', text)
            self.assertIn(f'KEPT {new} -> ', text)


if __name__ == '__main__':
    unittest.main()
