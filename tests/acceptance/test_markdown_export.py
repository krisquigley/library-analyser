import tempfile
import unittest
from pathlib import Path

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.review import StoredTrack
from music_analyzer.application.use_cases.review import ReviewTracks
from music_analyzer.domain.analysis import ScoreWindow, summarize_scores
from music_analyzer.infrastructure.filesystem.review_output import FileReviewOutput
from music_analyzer.interface_adapters.mappers.review import review_to_mapping
from music_analyzer.interface_adapters.presenters.markdown import markdown_track, MARKDOWN_HEADER


class MarkdownTests(unittest.TestCase):
    def report(self, run=None, overrides=(), locations=()):
        class Store:
            def read_track(self, track):
                return StoredTrack('id', 'sha', 42, locations, run, overrides)
        return ReviewTracks(Store()).show('id')

    def test_missing_failed_manual_and_untrusted_text(self):
        title = '音 [click](evil.example) | *x* `x` <script>\n# heading\u202e.flac'
        report = self.report(AnalysisReport('r', 'failed', (), 'bad <input>'),
                             (('genres', title),), ('/music/' + title,))
        text = markdown_track(report)
        self.assertIn('## 音', text)
        self.assertIn('Track ID: id', text)
        self.assertIn('SHA256: sha', text)
        self.assertIn('Location: /music/', text)
        self.assertIn('Genres (manual override):', text)
        self.assertIn('missing / no selection', text)
        self.assertIn('failed', text)
        self.assertIn('bad &lt;input&gt;', text)
        self.assertIn('genres: missing result', text)
        for unsafe in ('[click]', '<script>', '\n# heading', '\u202e', '| *x*'):
            self.assertNotIn(unsafe, text)
        self.assertIn('&#124;', text)
        self.assertIn('\\[click\\]', text)
        self.assertIn(r'No identity\-linked analysis', markdown_track(self.report()))

    def test_top_five_numeric_scores_provenance_and_manual_energy(self):
        labels = ('low', 'second', 'third', 'fourth', 'fifth', 'highest')
        windows = (ScoreWindow(0, 10, (.1, .8, .7, .6, .5, 2.)),)
        stage = StageResult('genres', (('model', 'test<model>'),), 'uncalibrated',
            windows=windows, summary=summarize_scores(labels, windows, 40))
        text = markdown_track(self.report(AnalysisReport('run', 'completed', (stage,)),
                                         (('energy', 'my assessment'),)))
        self.assertIn('highest: 2', text)
        self.assertNotIn('low: 0.1', text)
        self.assertLess(text.index('highest: 2'), text.index('second: 0.8'))
        self.assertIn('top 5 of 6', text)
        self.assertIn('25.0%', text)
        self.assertIn('1 window', text)
        self.assertIn('model=test&lt;model&gt;', text)
        self.assertIn('Energy (manual override): my assessment', text)
        self.assertIn('not probabilities', MARKDOWN_HEADER)


    def test_categorical_string_values_render_without_score_sort_crash(self):
        stage = StageResult('genres', (), 'reviewed', values=(
            ('primary', 'House & garage'), ('secondary', 'Jazz'), ('maybe', 'Rock'),
            ('support', 'Ambient'), ('low', 'Funk'), ('extra', 'Classical')))
        text = markdown_track(self.report(AnalysisReport('run', 'completed', (stage,))))
        self.assertIn('primary: House &amp; garage', text)
        self.assertIn('secondary: Jazz', text)
        self.assertIn('extra: Classical', text)
        self.assertNotIn('top 5 of 6', text)

    def test_mood_and_instrument_mixed_legal_values_keep_numeric_top_five_only(self):
        stages = (
            StageResult('mood', (), 'reviewed', values=(('warm', 'manual'), ('bright', 0.8), ('dark', 0.2))),
            StageResult('instruments', (), 'reviewed', values=(('piano', 0.4), ('drums', 'present'))),
        )
        text = markdown_track(self.report(AnalysisReport('run', 'completed', stages)))
        self.assertIn('warm: manual; bright: 0.8; dark: 0.2', text)
        self.assertIn('piano: 0.4; drums: present', text)
        self.assertNotIn('top 3 of 3', text)
        self.assertNotIn('top 2 of 2', text)

    def test_atomic_cleanup_no_overwrite_and_symlink_refusal(self):
        output = FileReviewOutput(review_to_mapping, markdown_track, MARKDOWN_HEADER)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'new.md'
            def broken():
                yield self.report()
                raise ValueError('failed iteration')
            with self.assertRaises(ValueError): output.write(broken(), 'markdown', target)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            output.write(iter(()), 'markdown', target)
            self.assertEqual(target.read_text(), MARKDOWN_HEADER)
            with self.assertRaises(FileExistsError): output.write(iter(()), 'markdown', target)
            link = Path(tmp) / 'link.md'
            link.symlink_to(target)
            with self.assertRaises(ValueError): output.write(iter(()), 'markdown', link)
            self.assertEqual(target.read_text(), MARKDOWN_HEADER)
