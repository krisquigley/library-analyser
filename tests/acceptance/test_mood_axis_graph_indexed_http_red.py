import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from music_explorer.application.dto.explorer import AxisValue, MoodAxisEdge, MoodAxisGraph, MoodAxisNode
from music_explorer.frameworks.explorer.server import create_server
from music_explorer.interface_adapters.mood_axis_graph_http import to_compact_mood_axis_graph_http
from tests.acceptance.test_explorer_3d_graph_assets import create_three_track_graph_db


class IndexedMoodAxisGraphHttpContractRedTests(unittest.TestCase):
    def _indexed_mapper(self):
        from music_explorer.interface_adapters import mood_axis_graph_http

        mapper = getattr(mood_axis_graph_http, 'to_indexed_mood_axis_graph_http', None)
        self.assertTrue(
            callable(mapper),
            'Issue #44 v3 red test expects an indexed/dictionary HTTP mapper named '
            'to_indexed_mood_axis_graph_http before the synthetic size gate can run.',
        )
        return mapper

    def _get_json(self, url):
        try:
            with urlopen(url, timeout=5) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except HTTPError as exc:
            body = exc.read().decode('utf-8')
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {'raw_body': body}
            return exc.code, payload

    def _with_server(self):
        td = tempfile.TemporaryDirectory()
        db = Path(td.name) / 'analysis.sqlite'
        ids = create_three_track_graph_db(db)
        server = create_server(str(db), port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return td, server, ids

    def test_contract_v3_returns_indexed_graph_without_changing_legacy_or_v2(self):
        td, server, ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            legacy_status, legacy = self._get_json(base + '/api/mood-axis-graph?mood=relaxing')
            compact_status, compact = self._get_json(base + '/api/mood-axis-graph?contract=v2&mood=relaxing')
            indexed_status, indexed = self._get_json(base + '/api/mood-axis-graph?contract=v3&mood=relaxing')
            self.assertEqual(legacy_status, 200)
            self.assertEqual(compact_status, 200)
            self.assertEqual(
                indexed_status,
                200,
                f'contract=v3 should be an opt-in indexed graph response, got HTTP {indexed_status}: {indexed}',
            )
            self.assertIn('positioned', legacy)
            self.assertNotIn('dto_version', legacy)
            self.assertEqual(compact['dto_version'], 'mood-axis-graph-compact-v1')
            self.assertEqual(indexed['dto_version'], 'mood-axis-graph-indexed-v1')
            self.assertEqual(indexed['selected_mood'], 'relaxing')
            self.assertEqual(set(indexed), {'dto_version', 'selected_mood', 'available_moods', 'metadata', 'axis', 'genre_labels', 'reason_text', 'provenance_table', 'explanation_table', 'link_defaults', 'nodes', 'unpositioned', 'links'})
            self.assertNotIn('positioned', indexed)
            self.assertNotIn('edges', indexed)
            self.assertEqual({node[0] for node in indexed['nodes']}, set(ids[:2]))
            self.assertEqual(len(indexed['unpositioned']), 1)
            self.assertTrue(all(isinstance(link[0], int) and isinstance(link[1], int) for link in indexed['links']))
            json.dumps(indexed, sort_keys=True, ensure_ascii=False, allow_nan=False)
        finally:
            server.shutdown(); server.server_close(); td.cleanup()

    def test_duplicate_conflicting_contract_including_v3_is_rejected_clearly(self):
        td, server, _ids = self._with_server()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            status, body = self._get_json(base + '/api/mood-axis-graph?contract=v2&contract=v3')
            self.assertEqual(status, 400)
            self.assertIn('contract', json.dumps(body).lower())
        finally:
            server.shutdown(); server.server_close(); td.cleanup()

    def test_indexed_payload_is_substantially_smaller_than_v2_on_public_synthetic_fixture(self):
        to_indexed_mood_axis_graph_http = self._indexed_mapper()

        graph = self._synthetic_repeated_string_graph(180)
        compact_bytes = json.dumps(to_compact_mood_axis_graph_http(graph), sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
        indexed_bytes = json.dumps(to_indexed_mood_axis_graph_http(graph), sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.assertLess(len(indexed_bytes), 45_000)
        self.assertLess(len(indexed_bytes), len(compact_bytes) * 0.30)

    def _synthetic_repeated_string_graph(self, count):
        nodes = []
        for index in range(count):
            nodes.append(MoodAxisNode(
                track_id=f'sha256:{index:064x}',
                display_label=f'Synthetic {index:04d}.flac',
                x=AxisValue('valence', (index % 100) / 100, (index % 100) / 100, 'native-emomusic-valence-regression'),
                y=AxisValue('arousal', ((index * 3) % 100) / 100, ((index * 3) % 100) / 100, 'native-emomusic-arousal-regression'),
                z=AxisValue('BPM', 80.0 + (index % 60), (80.0 + (index % 60)) / 20.0, 'fixed-BPM/20-display-units'),
                bpm=80.0 + (index % 60),
                genres=(('rock', 0.8), ('jazz', 0.2)),
                reasons=('genre threshold 0.5',),
                genre_threshold=0.5,
                mood_score=AxisValue('relaxing', 0.75, 0.75, 'sigmoid_mean_score_0_1'),
            ))
        edges = tuple(
            MoodAxisEdge(
                a=nodes[index].track_id,
                b=nodes[index + 1].track_id,
                score=0.75,
                explanation='axis-independent relatedness',
                provenance={'policy': 'sparse_k10', 'source': 'persisted-positioned-edges'},
                supported_group_count=3,
            )
            for index in range(count - 1)
        )
        return MoodAxisGraph(
            metadata={'graph_status': {'state': 'ready'}, 'track_count': count},
            selected_mood='relaxing',
            available_moods=('relaxing', 'heavy'),
            positioned=tuple(nodes),
            unpositioned=(),
            edges=edges,
        )


if __name__ == '__main__':
    unittest.main()
