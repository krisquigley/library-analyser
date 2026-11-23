"""Issue #133: `music-analyzer export-mixxx` creates a new Mixxx 2.5 library file from the analysis, end to end."""
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.use_cases.scan_library import ScanLibrary
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.frameworks.cli.main import main
from music_analyzer.infrastructure.filesystem.inventory import LocalInventory
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


def mood_stage(*, valence, arousal):
    summary = ScoreSummary(('valence', 'arousal'), (valence, arousal), (valence, arousal), (valence, arousal), 1.0)
    return StageResult('energy', (('model', 'emomusic-msd-musicnn-2'),), 'provisional', summary=summary)


class MixxxExportCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.music, self.exports = self.root / 'music', self.root / 'exports'
        self.music.mkdir(), self.exports.mkdir()
        self.database = self.root / 'analysis.db'
        for name in ('analysed.flac', 'unanalysed.mp3', 'quiet.flac'):
            (self.music / name).write_bytes(b'synthetic, not audio: ' + name.encode())
        repository = SQLiteAnalysisRepository(str(self.database))
        tags = TrackMetadata(common=(('title', 'Synthetic Title'), ('artist', 'Synthetic Artist')),
                             duration_seconds=240.0, duration_source='mutagen')
        reader = type('Reader', (), {'read': lambda self, path: tags})()
        files = ScanLibrary(LocalInventory(reader), repository).execute(str(self.music)).files
        self.ids = {Path(file.location).name: file.identity.track_id for file in files}
        run = repository.start(AudioSource('synthetic', self.ids['analysed.flac']))
        repository.save_stage(run, StageResult('bpm', (), 'estimate', (('bpm', 126.0), ('confidence', 3.0))))
        repository.save_stage(run, StageResult('key', (), 'estimate', (('key', 'A'), ('scale', 'minor'),
                                                                         ('strength', 0.9))))
        repository.save_stage(run, mood_stage(valence=6.0, arousal=7.0))
        repository.finish(run, 'completed', '')
        run = repository.start(AudioSource('synthetic', self.ids['quiet.flac']))
        repository.save_stage(run, mood_stage(valence=5.0, arousal=2.0))
        repository.finish(run, 'completed', '')
        repository.set_override(self.ids['analysed.flac'], 'key', 'C major')

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                patch('music_analyzer.frameworks.cli.main.load_backend', side_effect=AssertionError('no inference')):
            code = main(['--database', str(self.database), 'export-mixxx', *args])
        return code, out.getvalue(), err.getvalue()

    def test_a_dry_run_reports_the_plan_and_writes_nothing(self):
        before = self.database.read_bytes()
        code, out, err = self.call('--output', str(self.exports / 'mixxxdb.sqlite'), '--dry-run')
        self.assertEqual((0, ''), (code, err))
        self.assertIn('Dry run: would export 2 tracks', out)
        self.assertIn(f'Skipped {self.ids["unanalysed.mp3"]}: Not analysed yet', out)
        self.assertEqual([], list(self.exports.iterdir()))
        self.assertEqual(before, self.database.read_bytes())

    def test_the_export_creates_a_new_mixxx_file_with_the_listeners_overrides(self):
        before = self.database.read_bytes()
        destination = self.exports / 'mixxxdb.sqlite'
        code, out, err = self.call('--output', str(destination))
        self.assertEqual((0, ''), (code, err))
        self.assertIn(f'Exported 2 tracks to {destination} (Mixxx 2.5, schema 39); 1 skipped.', out)
        mixxx = sqlite3.connect(f'file:{destination}?mode=ro', uri=True)
        self.addCleanup(mixxx.close)
        self.assertEqual([(str(self.music / 'analysed.flac'), 'Synthetic Title', 'Synthetic Artist', 126.0, 'C', 1,
                           'flac')], mixxx.execute(
            'SELECT l.location, b.title, b.artist, b.bpm, b.key, b.key_id, b.filetype '
            'FROM library b JOIN track_locations l ON l.id = b.location WHERE l.filename = ?', ('analysed.flac',)).fetchall())
        self.assertEqual(before, self.database.read_bytes())

    def test_an_existing_destination_is_refused_and_left_untouched(self):
        destination = self.exports / 'mixxxdb.sqlite'
        destination.write_bytes(b'someone else\'s file')
        code, out, err = self.call('--output', str(destination))
        self.assertEqual((1, ''), (code, out))
        self.assertIn('already exists', err)
        self.assertEqual(b'someone else\'s file', destination.read_bytes())

    def test_chosen_tracks_only_and_an_unknown_track_is_an_error(self):
        code, out, _ = self.call('--output', str(self.exports / 'one.sqlite'), '--dry-run',
                                 '--track', self.ids['unanalysed.mp3'])
        self.assertEqual(0, code)
        self.assertIn('would export 0 tracks', out)
        code, out, err = self.call('--output', str(self.exports / 'two.sqlite'), '--track', 'absent')
        self.assertEqual((1, ''), (code, out))
        self.assertIn('Unknown track', err)
        self.assertEqual([], list(self.exports.iterdir()))

    def test_a_blank_track_or_output_is_rejected_at_the_command_line(self):
        for args in (('--output', ' '), ('--output', str(self.exports / 'x.sqlite'), '--track', ' ')):
            with self.subTest(args=args):
                with self.assertRaises(SystemExit) as raised:
                    self.call(*args)
                self.assertEqual(2, raised.exception.code)


    def test_mood_quadrant_colours_are_reported_in_the_dry_run_and_written(self):
        destination = self.exports / 'coloured.sqlite'
        code, out, err = self.call('--output', str(destination), '--colour', 'mood-quadrant', '--dry-run')
        self.assertEqual((0, ''), (code, err))
        self.assertIn('Mood-quadrant colours, relative to the 2 exported tracks with valence and arousal', out)
        self.assertIn('  upbeat (high arousal, high valence): 1\n', out)
        self.assertIn('  sombre (low arousal, low valence): 1\n', out)
        self.assertFalse(destination.exists())
        code, out, err = self.call('--output', str(destination), '--colour', 'mood-quadrant')
        self.assertEqual((0, ''), (code, err))
        mixxx = sqlite3.connect(f'file:{destination}?mode=ro', uri=True)
        self.addCleanup(mixxx.close)
        self.assertEqual([('analysed.flac', 0xF8D200), ('quiet.flac', 0x0044FF)], mixxx.execute(
            'SELECT l.filename, b.color FROM library b JOIN track_locations l ON l.id = b.location '
            'ORDER BY l.filename').fetchall())

    def test_without_the_colour_option_no_colour_is_written(self):
        destination = self.exports / 'plain.sqlite'
        self.assertEqual(0, self.call('--output', str(destination))[0])
        mixxx = sqlite3.connect(f'file:{destination}?mode=ro', uri=True)
        self.addCleanup(mixxx.close)
        self.assertEqual([(None,), (None,)], mixxx.execute('SELECT color FROM library').fetchall())


if __name__ == '__main__':
    unittest.main()
