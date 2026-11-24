"""Tags-only successions in the analysis database (#223): who may continue whom, and the move itself.

A departure is a track whose file is gone but whose analysis runs or overrides remain. An arrival is an
available track with no runs or overrides of its own. Each is identified by its audio stream. Carrying over
moves the runs, overrides and batch state to the successor in one transaction, records the succession, and
rebuilds the derived graph feature evidence for the successor from the moved run's stored stages. Stage
results, the raw evidence, are never rewritten.
"""
from music_analyzer.application.ports.track_successions import SuccessionCandidates
from music_analyzer.domain.track_succession import StreamedTrack, TrackSuccession
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository

_AVAILABLE = 'EXISTS(SELECT 1 FROM locations l WHERE l.track_id=s.track_id AND l.available=1)'
_HAS_EVIDENCE = ('(EXISTS(SELECT 1 FROM run_tracks r WHERE r.track_id=s.track_id) '
                 'OR EXISTS(SELECT 1 FROM overrides o WHERE o.track_id=s.track_id))')
_DEPARTED = (f'NOT {_AVAILABLE} AND {_HAS_EVIDENCE} '
             'AND NOT EXISTS(SELECT 1 FROM track_successions t WHERE t.predecessor_id=s.track_id)')
_ARRIVED = (f'{_AVAILABLE} AND NOT {_HAS_EVIDENCE} '
            'AND NOT EXISTS(SELECT 1 FROM batch_jobs b WHERE b.track_id=s.track_id AND b.state=\'running\') '
            'AND NOT EXISTS(SELECT 1 FROM track_successions t WHERE t.successor_id=s.track_id)')


class SQLiteTrackSuccessions(SQLiteAnalysisRepository):
    def candidates(self) -> SuccessionCandidates:
        with self._read_transaction() as db:
            departures = db.execute(
                f'SELECT s.track_id,s.audio_sha256 FROM track_streams s WHERE {_DEPARTED} ORDER BY s.track_id').fetchall()
            arrivals = db.execute(
                f'''SELECT s.track_id,s.audio_sha256 FROM track_streams s WHERE {_ARRIVED}
                    AND s.audio_sha256 IN (SELECT s.audio_sha256 FROM track_streams s WHERE {_DEPARTED})
                    ORDER BY s.track_id''').fetchall()
        return SuccessionCandidates(_streamed(arrivals), _streamed(departures))

    def carry_over(self, succession: TrackSuccession) -> bool:
        predecessor, successor = succession.predecessor_id, succession.successor_id
        with self._transaction() as db:
            if not (_holds(db, _DEPARTED, predecessor, succession.audio_sha256)
                    and _holds(db, _ARRIVED, successor, succession.audio_sha256)):
                return False
            db.execute('UPDATE run_tracks SET track_id=? WHERE track_id=?', (successor, predecessor))
            db.execute('UPDATE overrides SET track_id=? WHERE track_id=?', (successor, predecessor))
            db.execute('DELETE FROM batch_jobs WHERE track_id=?', (successor,))
            db.execute('UPDATE batch_jobs SET track_id=? WHERE track_id=?', (successor, predecessor))
            db.execute('DELETE FROM graph_feature_evidence WHERE track_id=?', (predecessor,))
            db.execute('INSERT INTO track_successions(successor_id,predecessor_id,audio_sha256) VALUES(?,?,?)',
                       (successor, predecessor, succession.audio_sha256))
            self._invalidate_current_graph_snapshot(db, successor)
            latest = self._latest_active_run_for_track(db, successor)
            if latest is not None and latest[1] == 'completed':
                self._persist_graph_feature_evidence(db, successor, latest[0])
            return True


def _holds(db, condition, track_id, audio_sha256) -> bool:
    return db.execute(f'SELECT 1 FROM track_streams s WHERE s.track_id=? AND s.audio_sha256=? AND {condition}',
                      (track_id, audio_sha256)).fetchone() is not None


def _streamed(rows) -> tuple[StreamedTrack, ...]:
    return tuple(StreamedTrack(track_id, audio_sha256) for track_id, audio_sha256 in rows)
