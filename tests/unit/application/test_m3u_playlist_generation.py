from dataclasses import dataclass
import importlib
import unittest

from music_explorer.application.dto.explorer import AxisValue, MoodAxisEdge, MoodAxisGraph, MoodAxisNode


@dataclass(frozen=True)
class _PlayableTrack:
    track_id: str
    bpm: float
    path: str
    exists: bool = True
    active: bool = True
    catalogued: bool = True
    title: str = ''
    artist: str = ''


class _FakePlaylistRepository:
    def __init__(self, *, tracks, edges):
        self._tracks = tuple(tracks)
        self._edges = tuple(edges)
        self.graph_reads = 0
        self.track_reads = 0

    def mood_axis_graph_snapshot(self, mood=None, sparse_k=10):
        self.graph_reads += 1
        nodes = tuple(_node(track.track_id, track.bpm) for track in self._tracks)
        return MoodAxisGraph(
            metadata={'track_count': len(nodes)},
            selected_mood='',
            available_moods=(),
            positioned=nodes,
            unpositioned=(),
            edges=self._edges,
        )

    def playlist_export_tracks(self):
        self.track_reads += 1
        return self._tracks

    # Candidate method names document the port contract without forcing production yet.
    def playable_track_candidates(self):
        self.track_reads += 1
        return self._tracks

    def playlist_candidates(self):
        self.track_reads += 1
        return self._tracks


def _node(track_id, bpm):
    return MoodAxisNode(
        track_id=track_id,
        display_label=track_id,
        x=AxisValue('valence', 0.0, 0.0, 'native'),
        y=AxisValue('arousal', 0.0, 0.0, 'native'),
        z=AxisValue('bpm', bpm, bpm / 20.0, 'bpm / 20'),
        bpm=bpm,
        genres=(),
    )


def _edge(a, b, score):
    return MoodAxisEdge(a, b, score, 'fixture', {'source': 'unit-test'}, 1)


def _load_use_case_class():
    candidates = (
        ('music_explorer.application.use_cases.playlists', 'GenerateBpmGraphM3U'),
        ('music_explorer.application.use_cases.playlists', 'GenerateBpmGraphM3UPlaylist'),
        ('music_explorer.application.use_cases.explorer', 'GenerateBpmGraphM3U'),
        ('music_explorer.application.use_cases.explorer', 'GenerateBpmGraphM3UPlaylist'),
    )
    for module_name, class_name in candidates:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        use_case = getattr(module, class_name, None)
        if use_case is not None:
            return use_case
    return None


def _generate(repository, *, start='start', bpm_min=100, bpm_max=130, length=2):
    use_case_class = _load_use_case_class()
    if use_case_class is None:
        raise AssertionError(
            'Missing application use case for Issue #58: expected GenerateBpmGraphM3U '
            'or GenerateBpmGraphM3UPlaylist in the application use-case layer'
        )
    use_case = use_case_class(repository)
    return use_case.execute(start_track_id=start, bpm_min=bpm_min, bpm_max=bpm_max, length=length)


def _content(result):
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get('content') or result.get('m3u') or ''
    return getattr(result, 'content', '') or getattr(result, 'm3u', '')


def _track_ids(result):
    if isinstance(result, dict):
        return tuple(result.get('track_ids', ()))
    return tuple(getattr(result, 'track_ids', ()))


def _warning(result):
    if isinstance(result, dict):
        return result.get('warning')
    return getattr(result, 'warning', None)


class M3UPlaylistGenerationTests(unittest.TestCase):
    def test_length_includes_start_and_bpm_bounds_are_inclusive(self):
        repo = _FakePlaylistRepository(
            tracks=(
                _PlayableTrack('start', 100, '/library/start.flac'),
                _PlayableTrack('next', 130, '/library/next.flac'),
            ),
            edges=(_edge('start', 'next', 0.9),),
        )

        result = _generate(repo, start='start', bpm_min=100, bpm_max=130, length=2)

        self.assertEqual(('start', 'next'), _track_ids(result))
        self.assertEqual('#EXTM3U\n/library/start.flac\n/library/next.flac\n', _content(result))

    def test_rejects_start_outside_bpm_range(self):
        repo = _FakePlaylistRepository(
            tracks=(_PlayableTrack('start', 99.9, '/library/start.flac'),),
            edges=(),
        )

        with self.assertRaisesRegex(ValueError, 'start.*BPM.*range'):
            _generate(repo, start='start', bpm_min=100, bpm_max=130, length=1)

    def test_rejects_missing_or_invalid_bounds_and_non_positive_length(self):
        repo = _FakePlaylistRepository(
            tracks=(_PlayableTrack('start', 120, '/library/start.flac'),),
            edges=(),
        )

        invalid_requests = (
            {'bpm_min': None, 'bpm_max': 130, 'length': 1},
            {'bpm_min': 100, 'bpm_max': None, 'length': 1},
            {'bpm_min': 131, 'bpm_max': 130, 'length': 1},
            {'bpm_min': 100, 'bpm_max': 130, 'length': 0},
            {'bpm_min': 100, 'bpm_max': 130, 'length': 1001},
        )
        for request in invalid_requests:
            with self.subTest(request=request):
                with self.assertRaisesRegex(ValueError, 'BPM|bound|length|between|positive'):
                    _generate(repo, start='start', **request)

    def test_rejects_unplayable_or_unsafe_start_path(self):
        unsafe = _FakePlaylistRepository(
            tracks=(_PlayableTrack('start', 120, '/library/bad\npath.flac'),),
            edges=(),
        )
        missing = _FakePlaylistRepository(
            tracks=(_PlayableTrack('start', 120, '/library/missing.flac', exists=False),),
            edges=(),
        )

        with self.assertRaisesRegex(ValueError, 'start.*playable|path.*safe|control'):
            _generate(unsafe, start='start', bpm_min=100, bpm_max=130, length=1)
        with self.assertRaisesRegex(ValueError, 'start.*playable|exist'):
            _generate(missing, start='start', bpm_min=100, bpm_max=130, length=1)

    def test_greedy_highest_relatedness_undirected_neighbor_with_track_id_tie_break(self):
        repo = _FakePlaylistRepository(
            tracks=(
                _PlayableTrack('a', 120, '/library/a.flac'),
                _PlayableTrack('b', 121, '/library/b.flac'),
                _PlayableTrack('c', 122, '/library/c.flac'),
                _PlayableTrack('d', 123, '/library/d.flac'),
            ),
            edges=(
                _edge('b', 'a', 0.9),  # reverse-stored edge is still connected to a
                _edge('a', 'c', 0.9),  # equal score: b wins by stable track id
                _edge('b', 'd', 0.95),
            ),
        )

        result = _generate(repo, start='a', bpm_min=100, bpm_max=130, length=3)

        self.assertEqual(('a', 'b', 'd'), _track_ids(result))
        self.assertEqual('#EXTM3U\n/library/a.flac\n/library/b.flac\n/library/d.flac\n', _content(result))

    def test_dead_end_returns_partial_playlist_warning_without_jump_or_repeat(self):
        repo = _FakePlaylistRepository(
            tracks=(
                _PlayableTrack('start', 120, '/library/start.flac'),
                _PlayableTrack('end', 121, '/library/end.flac'),
                _PlayableTrack('other-component', 122, '/library/other.flac'),
            ),
            edges=(_edge('start', 'end', 0.8),),
        )

        result = _generate(repo, start='start', bpm_min=100, bpm_max=130, length=4)

        self.assertEqual(('start', 'end'), _track_ids(result))
        self.assertNotIn('other-component', _track_ids(result))
        self.assertEqual(len(set(_track_ids(result))), len(_track_ids(result)))
        self.assertRegex(_warning(result) or '', 'shorter|dead end|connected')

    def test_filters_ineligible_neighbors_by_bpm_and_playable_path(self):
        repo = _FakePlaylistRepository(
            tracks=(
                _PlayableTrack('start', 120, '/library/start.flac'),
                _PlayableTrack('too-slow', 90, '/library/slow.flac'),
                _PlayableTrack('unsafe', 121, '/library/unsafe\r.flac'),
                _PlayableTrack('missing', 122, '/library/missing.flac', exists=False),
                _PlayableTrack('inactive', 123, '/library/inactive.flac', active=False),
                _PlayableTrack('uncatalogued', 124, '/library/uncatalogued.flac', catalogued=False),
                _PlayableTrack('ok', 125, '/library/ok.flac'),
            ),
            edges=(
                _edge('start', 'too-slow', 1.0),
                _edge('start', 'unsafe', 0.99),
                _edge('start', 'missing', 0.98),
                _edge('start', 'inactive', 0.97),
                _edge('start', 'uncatalogued', 0.96),
                _edge('start', 'ok', 0.5),
            ),
        )

        result = _generate(repo, start='start', bpm_min=100, bpm_max=130, length=2)

        self.assertEqual(('start', 'ok'), _track_ids(result))
        self.assertEqual('#EXTM3U\n/library/start.flac\n/library/ok.flac\n', _content(result))

    def test_rejects_m3u_line_injection_in_paths_or_metadata(self):
        for bad_path in ('/library/evil\n#EXTINF:999.flac', '/library/evil\r.flac', '/library/evil\x00.flac', '/library/evil\x1f.flac'):
            with self.subTest(path=bad_path):
                repo = _FakePlaylistRepository(
                    tracks=(_PlayableTrack('start', 120, bad_path),),
                    edges=(),
                )
                with self.assertRaisesRegex(ValueError, 'control|newline|safe|injection'):
                    _generate(repo, start='start', bpm_min=100, bpm_max=130, length=1)

    def test_traversal_is_bounded_by_requested_length_and_indexes_inputs_once(self):
        tracks = tuple(_PlayableTrack(f'track-{idx:03d}', 120, f'/library/{idx:03d}.flac') for idx in range(50))
        edges = tuple(_edge(f'track-{idx:03d}', f'track-{idx + 1:03d}', 1.0) for idx in range(49))
        repo = _FakePlaylistRepository(tracks=tracks, edges=edges)

        result = _generate(repo, start='track-000', bpm_min=100, bpm_max=130, length=5)

        self.assertEqual(tuple(f'track-{idx:03d}' for idx in range(5)), _track_ids(result))
        self.assertEqual(1, repo.graph_reads)
        self.assertEqual(1, repo.track_reads)


if __name__ == '__main__':
    unittest.main()
