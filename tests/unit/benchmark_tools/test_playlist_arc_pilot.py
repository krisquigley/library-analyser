"""Issue #137: the chained-arc pilot reports aggregates only, never a track."""
import json
import unittest

from music_explorer.application.dto.playlists import EnergyArcRequest
from music_explorer.domain import energy_plan
from tests.unit.application.test_chained_energy_arcs import _even_library
from tools.playlist_arc_pilot import arc_places, parse_chain, run_pilot, summarize


class ParseChainTests(unittest.TestCase):
    def test_a_chain_is_shapes_and_lengths_in_order(self):
        self.assertEqual((EnergyArcRequest('rise', tracks=10), EnergyArcRequest('dip', tracks=4)),
                         parse_chain('rise:10,dip:4', 'tracks'))
        self.assertEqual((EnergyArcRequest('fall', minutes=12.5),), parse_chain('fall:12.5', 'minutes'))

    def test_a_chain_that_cannot_be_read_is_rejected(self):
        for chain in ('', 'rise', 'rise:ten', 'rise:3,'):
            with self.subTest(chain=chain):
                with self.assertRaises(ValueError):
                    parse_chain(chain, 'tracks')


class ArcPlacesTests(unittest.TestCase):
    def test_by_track_count_each_place_falls_in_its_arc(self):
        self.assertEqual([0, 0, 0, 1, 1, 2, 2], arc_places([None] * 7, (3, 2, 2), 'tracks'))

    def test_by_minutes_a_track_belongs_to_the_arc_it_starts_in(self):
        self.assertEqual([0, 0, 1, 2, 2], arc_places([100, 100, 100, 100, 100], (2.5, 1.5, 1), 'minutes'))

    def test_a_track_past_the_end_stays_in_the_last_arc(self):
        self.assertEqual([0, 1, 1], arc_places([None] * 3, (1, 1), 'tracks'))


class SummarizeTests(unittest.TestCase):
    def test_the_mean_miss_per_arc_the_mean_relation_and_timings(self):
        runs = [
            {'placements': [(0, 0.5, 0.5), (0, 0.7, 0.6), (1, None, 0.4)], 'relations': [0.9, 0.8], 'seconds': 0.2,
             'complete': True},
            {'placements': [(0, 0.2, 0.5), (1, 0.3, 0.4)], 'relations': [0.7], 'seconds': 0.4, 'complete': False},
        ]
        summary = summarize(runs, arc_count=2)

        self.assertEqual([0, 1], [arc['arc'] for arc in summary['arcs']])
        self.assertEqual([3, 2], [arc['placed'] for arc in summary['arcs']])
        self.assertEqual([3, 1], [arc['known_energy'] for arc in summary['arcs']])
        self.assertAlmostEqual((0.0 + 0.1 + 0.3) / 3, summary['arcs'][0]['mean_target_miss'])
        self.assertAlmostEqual(0.1, summary['arcs'][1]['mean_target_miss'])
        self.assertAlmostEqual(0.8, summary['mean_relation_score'])
        self.assertEqual({'runs': 2, 'incomplete': 1, 'p50': 0.2, 'p95': 0.4, 'max': 0.4},
                         {key: summary[key] for key in ('runs', 'incomplete', 'p50', 'p95', 'max')})

    def test_an_arc_without_known_energy_has_no_mean(self):
        summary = summarize([{'placements': [(0, None, 0.5)], 'relations': [], 'seconds': 0.1, 'complete': True}], arc_count=1)

        self.assertIsNone(summary['arcs'][0]['mean_target_miss'])
        self.assertIsNone(summary['mean_relation_score'])


class RunPilotTests(unittest.TestCase):
    def test_a_pilot_over_sampled_starts_reports_aggregates_for_each_weight(self):
        report = run_pilot(_even_library(), parse_chain('rise:3,fall:3', 'tracks'), unit='tracks', starts=4, seed=7,
                           bpm_range=(100, 130), weights=(0.6, 0.2))

        self.assertEqual([0.6, 0.2], [result['arc_weight'] for result in report['results']])
        self.assertEqual({'runs': 4, 'failures': 0}, {key: report['results'][0][key] for key in ('runs', 'failures')})
        self.assertEqual(2, len(report['results'][0]['arcs']))
        self.assertNotRegex(json.dumps(report), r't\d|/library|flac', 'no track ids, titles or paths')
        self.assertEqual(0.6, energy_plan.ARC_WEIGHT, 'the weight is put back after the pilot')

    def test_more_starts_than_eligible_tracks_uses_them_all(self):
        report = run_pilot(_even_library(), parse_chain('steady:2', 'tracks'), unit='tracks', starts=50, seed=1,
                           bpm_range=(100, 130), weights=(0.6,))

        self.assertEqual(10, report['results'][0]['runs'])


if __name__ == '__main__':
    unittest.main()
