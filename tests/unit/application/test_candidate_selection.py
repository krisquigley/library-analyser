import unittest

from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.application.dto.candidates import CandidateQuery, SelectionControlDto
from music_analyzer.application.use_cases.candidates import SelectExplorerCandidates


class FakeSnapshotRepository:
    def __init__(self, records):
        self.records = tuple(records)
        self.list_calls = []
        self.read_calls = []

    def metadata(self):
        return {'application_id': 0x4D414E41, 'schema_version': 4, 'read_policy': 'coherent_in_memory_snapshot'}

    def track_ids(self):
        return tuple(record.track_id for record in self.records)

    def read_track(self, track_id):
        self.read_calls.append(track_id)
        for record in self.records:
            if record.track_id == track_id:
                return record
        raise KeyError(track_id)

    def list_tracks(self, limit, after=None):
        self.list_calls.append((limit, after))
        raise AssertionError('candidate selection must not use bounded list pagination')


def stage(name, values=(), summary=(), uncertainty=''):
    return StageResult(name, (), uncertainty, tuple(values), (), ScoreSummary(tuple(k for k, _ in summary), tuple(v for _, v in summary), tuple(v for _, v in summary), tuple(v for _, v in summary), 1.0, False) if summary else None)


def track(suffix, stages=(), overrides=(), label=''):
    return ExplorerStoredTrack('sha256:' + suffix * 64, suffix * 64, 1, label or suffix, 1, AnalysisReport('run-' + suffix, 'completed', tuple(stages)), tuple(overrides))


class SelectExplorerCandidatesTests(unittest.TestCase):
    def test_selects_from_single_coherent_snapshot_after_ranking_not_before(self):
        current = track('a', (stage('bpm', (('bpm', 100.0),)), stage('energy', summary=(('arousal', 0.0),)), stage('key', (('key', 'C'), ('scale', 'major')))))
        far_first = track('b', (stage('bpm', (('bpm', 130.0),)), stage('energy', summary=(('arousal', 0.1),)), stage('key', (('key', 'F#'), ('scale', 'major')))))
        best_late = track('c', (stage('bpm', (('bpm', 101.0),)), stage('energy', summary=(('arousal', 1.0),)), stage('key', (('key', 'C'), ('scale', 'major')))))
        repo = FakeSnapshotRepository((current, far_first, best_late))
        result = SelectExplorerCandidates(repo).execute(CandidateQuery(current.track_id, (SelectionControlDto('energy', 'soft', 1, {'energy_mode': 'rise'}),), limit=1))
        self.assertEqual([c.track_id for c in result.candidates], [best_late.track_id])
        self.assertEqual(repo.list_calls, [])
        self.assertEqual(repo.read_calls, [current.track_id, far_first.track_id, best_late.track_id])
        self.assertEqual(result.policy_versions['override_policy_version'], 'manual-text-display-only-v1')
        self.assertEqual(result.metadata.read_policy, 'coherent_in_memory_snapshot')

    def test_unknown_current_and_one_track_catalogue_are_actionable(self):
        repo = FakeSnapshotRepository(())
        with self.assertRaisesRegex(ValueError, 'Unknown current track'):
            SelectExplorerCandidates(repo).execute(CandidateQuery('missing', ()))
        one = track('a')
        result = SelectExplorerCandidates(FakeSnapshotRepository((one,))).execute(CandidateQuery(one.track_id, ()))
        self.assertEqual(result.candidates, ())
        self.assertIn('No candidates are available in a one-track catalogue', result.no_match_suggestions)

    def test_manual_override_maps_to_unresolved_domain_feature_and_masks_automatic(self):
        current = track('a', (stage('bpm', (('bpm', 100.0),)),))
        candidate = track('b', (stage('bpm', (('bpm', 100.0),)),), overrides=(('bpm', '100 maybe'),))
        result = SelectExplorerCandidates(FakeSnapshotRepository((current, candidate))).execute(CandidateQuery(current.track_id, (SelectionControlDto('tempo', 'soft', 1),)))
        self.assertEqual(result.candidates[0].tier, 'eligible_insufficient_evidence')
        self.assertIn('tempo: candidate bpm has unresolved manual text', result.candidates[0].explanation.missing_evidence)
        self.assertEqual(result.candidates[0].explanation.manual_values, (('bpm', '100 maybe'),))

    def test_rejects_unsupported_cursor_semantics(self):
        one = track('a')
        with self.assertRaisesRegex(ValueError, 'Cursor paging is not supported'):
            SelectExplorerCandidates(FakeSnapshotRepository((one,))).execute(CandidateQuery(one.track_id, (), after='x'))


if __name__ == '__main__':
    unittest.main()
