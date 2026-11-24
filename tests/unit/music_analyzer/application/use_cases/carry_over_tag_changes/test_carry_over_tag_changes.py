"""Issue #223: after a scan, each tags-only change keeps its track's analysis and overrides."""
import unittest

from music_analyzer.application.ports.track_successions import SuccessionCandidates
from music_analyzer.application.use_cases.carry_over_tag_changes.carry_over_tag_changes import (
    CarryOverTagChanges, TrackEvidenceCarriedOver)
from music_analyzer.domain.track_succession import StreamedTrack, TrackSuccession

AUDIO = 'a' * 64
OLD, NEW = StreamedTrack('sha256:' + '1' * 64, AUDIO), StreamedTrack('sha256:' + '2' * 64, AUDIO)


class FakeTrackSuccessions:
    def __init__(self, candidates, *, still_holds=True):
        self._candidates, self._still_holds, self.carried = candidates, still_holds, []

    def candidates(self):
        return self._candidates

    def carry_over(self, succession):
        if self._still_holds:
            self.carried.append(succession)
        return self._still_holds


class RecordingEvents:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


class CarryOverTagChangesTests(unittest.TestCase):
    def test_each_unambiguous_succession_is_carried_over_and_announced(self):
        successions, events = FakeTrackSuccessions(SuccessionCandidates((NEW,), (OLD,))), RecordingEvents()
        carried = CarryOverTagChanges(successions, events).execute()
        expected = TrackSuccession(OLD.track_id, NEW.track_id, AUDIO)
        self.assertEqual((successions.carried, carried), ([expected], (expected,)))
        self.assertEqual(events.published, [TrackEvidenceCarriedOver(OLD.track_id, NEW.track_id)])

    def test_nothing_to_pair_carries_nothing_and_announces_nothing(self):
        successions, events = FakeTrackSuccessions(SuccessionCandidates((NEW,), ())), RecordingEvents()
        self.assertEqual(CarryOverTagChanges(successions, events).execute(), ())
        self.assertEqual((successions.carried, events.published), ([], []))

    def test_a_succession_that_no_longer_holds_when_carried_is_left_alone(self):
        successions, events = FakeTrackSuccessions(SuccessionCandidates((NEW,), (OLD,)), still_holds=False), RecordingEvents()
        self.assertEqual(CarryOverTagChanges(successions, events).execute(), ())
        self.assertEqual(events.published, [])


if __name__ == '__main__':
    unittest.main()
