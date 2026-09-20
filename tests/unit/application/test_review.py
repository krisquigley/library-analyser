import unittest
from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.review import StoredTrack
from music_analyzer.application.use_cases.review import ReviewTracks
from music_analyzer.domain.analysis import ScoreWindow, summarize_scores


class Store:
    def __init__(self):
        self.overrides = {}
        windows = (ScoreWindow(0, 10, (.2, .8)),)
        self.run = AnalysisReport('r1', 'completed', (StageResult('genres', (), 'uncalibrated',
            windows=windows, summary=summarize_scores(('a', 'b'), windows, 10)),))
    def read_track(self, track):
        if track != 't': raise ValueError('Unknown track')
        return StoredTrack('t', 'sha', 42, ('音.flac',), self.run, tuple(self.overrides.items()))
    def track_ids(self): return iter(('t',))
    def set_override(self, track, field, value):
        self.read_track(track)
        if value is None: self.overrides.pop(field, None)
        else: self.overrides[field] = value


class ReviewTests(unittest.TestCase):
    def test_manual_precedence_clear_and_reanalysis_preservation(self):
        store = Store(); review = ReviewTracks(store)
        review.override('t', 'genres', 'human choice')
        self.assertEqual(dict(review.show('t').effective)['genres'], 'human choice')
        store.run = AnalysisReport('r2', 'failed', ())
        result = review.show('t')
        self.assertEqual(dict(result.effective)['genres'], 'human choice')
        self.assertTrue(result.needs_review)
        review.override('t', 'genres', None)
        self.assertIsNone(dict(review.show('t').effective)['genres'])

    def test_threshold_is_explicit_transient_and_uses_only_retained_scores(self):
        store = Store(); review = ReviewTracks(store)
        self.assertEqual(dict(review.show('t', .5).selections)['genres'], ('b',))
        self.assertEqual(dict(review.show('t', .1).selections)['genres'], ('a', 'b'))
        self.assertEqual(review.show('t').selections, ())
        self.assertEqual(store.run.run_id, 'r1')
        with self.assertRaises(ValueError): review.show('t', float('nan'))
        review.override('t', 'genres', 'manual')
        self.assertEqual(dict(review.show('t', .5).effective)['genres'], 'manual')

    def test_missing_uncertain_and_invalid_overrides(self):
        review = ReviewTracks(Store())
        self.assertEqual(len(tuple(review.list(True))), 1)
        for field, value in [('unknown', 'x'), ('bpm', ''), ('key', 'x'*4097)]:
            with self.assertRaises(ValueError): review.override('t', field, value)
        with self.assertRaises(ValueError): review.show('missing')

    def test_export_uses_output_port_and_lazy_reports(self):
        class Output:
            def write(self, reports, format, destination):
                self.args = (tuple(reports), format, destination)
        output = Output()
        ReviewTracks(Store()).export(output, 'json', 'destination')
        self.assertEqual(output.args[0][0].track.track_id, 't')
        self.assertEqual(output.args[1:], ('json', 'destination'))

    def test_summary_only_results_expose_labelled_means_not_missing_or_selected_tags(self):
        store = Store()
        stages = [StageResult('bpm', (), 'estimate', values=(('bpm', 128.),)),
                  StageResult('key', (), 'estimate', values=(('key', 'A'), ('scale', 'minor')))]
        for field, labels, scores in (
                ('genres', ('Electronic---House', 'Jazz'), (.2, .8)),
                ('mood', ('happy', 'sad'), (.1, .3)),
                ('instruments', ('guitar', 'drums'), (.05, .6)),
                ('energy', ('valence', 'arousal'), (5.1, 7.2))):
            windows = (ScoreWindow(0, 10, scores), ScoreWindow(20, 40, tuple(x / 2 for x in scores)))
            stages.append(StageResult(field, (), 'uncalibrated', windows=windows,
                summary=summarize_scores(labels, windows, 60)))
        store.run = AnalysisReport('r', 'completed', tuple(stages))
        review = ReviewTracks(store)
        report = review.show('t')
        for stage in stages:
            expected = stage.values or tuple(zip(stage.summary.labels, stage.summary.mean))
            self.assertEqual(dict(report.effective)[stage.stage], expected)
        self.assertTrue(report.needs_review)
        self.assertEqual(report.selections, ())
        self.assertEqual(tuple(review.list())[0], report)
        review.override('t', 'energy', 'human assessment')
        self.assertEqual(dict(review.show('t').effective)['energy'], 'human assessment')
        review.override('t', 'energy', None)
        self.assertEqual(review.show('t'), report)
        self.assertEqual(store.run.stages, tuple(stages))

    def test_empty_evidence_remains_absent_and_explicit_values_take_precedence(self):
        store = Store()
        summary = store.run.stages[0].summary
        store.run = AnalysisReport('r', 'completed', (
            StageResult('genres', (), 'missing'),
            StageResult('energy', (), 'raw', values=(('arousal', 7.),), summary=summary)))
        effective = dict(ReviewTracks(store).show('t').effective)
        self.assertIsNone(effective['genres'])
        self.assertIsNone(effective['mood'])
        self.assertEqual(effective['energy'], (('arousal', 7.),))
