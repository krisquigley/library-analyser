import unittest
from contextlib import nullcontext

from music_analyzer.application.dto.analysis import AnalysisReport
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.application.ports.batch import BatchJob
from music_analyzer.application.use_cases.analyze_batch import AnalyzeBatch
from music_analyzer.application.use_cases.explorer import GetExplorerTrackDetail, ListExplorerTracks


INCLUDED = 'sha256:' + 'a' * 64
TOO_LONG = 'sha256:' + 'b' * 64
UNKNOWN = 'sha256:' + 'c' * 64


def record(track_id, duration):
    return ExplorerStoredTrack(track_id, track_id.split(':', 1)[1], 1, track_id[-6:] + '.flac', 1,
                               AnalysisReport('run-' + track_id[-1], 'completed', ()), (),
                               TrackMetadata(duration_seconds=duration))


class ExplorerRepo:
    def __init__(self):
        self.records = (record(INCLUDED, 1200.0), record(TOO_LONG, 1200.01), record(UNKNOWN, None))

    def metadata(self):
        return {'application_id': 0x4D414E41, 'schema_version': 6, 'read_policy': 'bounded_read_transaction'}

    def candidate_snapshot(self):
        return self.metadata(), self.records

    def list_tracks(self, limit, after=None):
        records = self.records if after is None else tuple(r for r in self.records if r.track_id > after)
        return self.metadata(), len(records), records[:limit]

    def track_ids(self):
        return tuple(r.track_id for r in self.records)

    def read_track(self, track_id):
        return next(r for r in self.records if r.track_id == track_id)


class BatchQueue:
    def __init__(self):
        self.jobs = []

    def exclusive(self): return nullcontext()
    def recover(self): pass
    def tracks(self): return (INCLUDED, TOO_LONG, UNKNOWN)
    def active_tracks(self): return (INCLUDED,)
    def ineligible_tracks(self): return {TOO_LONG: 'duration 1200.01s exceeds active-library limit 1200.0s', UNKNOWN: 'duration unknown; rescan with metadata support before active use'}
    def get_job(self, track_id): return None
    def put_job(self, job): self.jobs.append(job)
    def status(self): return tuple(self.jobs)


class ActiveDurationExclusionTests(unittest.TestCase):
    def test_explorer_active_list_excludes_too_long_and_unknown_but_detail_explains(self):
        repo = ExplorerRepo()
        listed = ListExplorerTracks(repo).execute(limit='all')
        self.assertEqual(tuple(t.track_id for t in listed.tracks), (INCLUDED,))
        self.assertEqual(listed.metadata.track_count, 1)

        long_detail = GetExplorerTrackDetail(repo).execute(TOO_LONG)
        self.assertIn('Excluded from active library: Duration 1200.010s exceeds active-library limit of 1200.0s', long_detail.reasons)
        unknown_detail = GetExplorerTrackDetail(repo).execute(UNKNOWN)
        self.assertIn('Excluded from active library: Duration unknown; rescan with a readable measured audio duration before active-library use', unknown_detail.reasons)

    def test_batch_uses_active_tracks_and_selected_track_cannot_bypass_with_retry_or_force(self):
        queue = BatchQueue()
        analyzed = []
        batch = AnalyzeBatch(queue, lambda t: object(), lambda source, duration: analyzed.append(source) or AnalysisReport('r', 'completed', ()), lambda t: True)
        batch.execute('recipe')
        self.assertEqual([job.track_id for job in queue.jobs if job.state == 'running'], [INCLUDED])
        with self.assertRaisesRegex(ValueError, 'ineligible'):
            batch.execute('recipe', retry_failed=True, force=True, selected_tracks=(TOO_LONG,))


if __name__ == '__main__':
    unittest.main()
