from dataclasses import dataclass
import importlib
import unittest

from music_explorer.application.dto.explorer import AxisValue, MoodAxisEdge, MoodAxisGraph, MoodAxisNode
from music_explorer.application.dto.playlists import EnergyArcRequest, PlaylistRecipe


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
    manual_overrides: tuple[str, ...] = ()
    duration_seconds: float | None = 180.0
    key: str | None = None
    scale: str | None = None
    key_strength: float | None = None
    arousal: float | None = None
    mood_scores: tuple[tuple[str, float], ...] = ()


class _FakePlaylistRepository:
    def __init__(self, *, tracks, edges, graph_state='ready'):
        self._tracks = tuple(tracks)
        self._edges = tuple(edges)
        self._graph_state = graph_state
        self.graph_reads = 0
        self.edge_reads = []
        self.mood_evidence_reads = []
        self.track_reads = 0

    def playlist_mood_evidence(self, mood):
        from music_explorer.application.dto.playlists import PlaylistMoodEvidence
        self.mood_evidence_reads.append(mood)
        return {track.track_id: PlaylistMoodEvidence(track.arousal, dict(track.mood_scores).get(mood) if mood else None)
                for track in self._tracks}

    def related_track_edges(self, sparse_k):
        self.edge_reads.append(sparse_k)
        return {'state': self._graph_state}, self._edges

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
        ('music_explorer.application.use_cases.download_playlist.download_playlist', 'GenerateBpmGraphM3U'),
        ('music_explorer.application.use_cases.download_playlist.download_playlist', 'GenerateBpmGraphM3UPlaylist'),
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
    return use_case.execute(PlaylistRecipe(start_track_id=start, bpm_min=bpm_min, bpm_max=bpm_max, length=length))


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
    def test_walks_past_a_dead_end_instead_of_stopping_short(self):
        # Issue #121: greedy took 'dead-end' and stopped at two tracks.
        repo = _FakePlaylistRepository(
            tracks=(
                _PlayableTrack('start', 120, '/library/start.flac'),
                _PlayableTrack('dead-end', 121, '/library/dead.flac'),
                _PlayableTrack('via', 122, '/library/via.flac'),
                _PlayableTrack('onward', 123, '/library/onward.flac'),
            ),
            edges=(_edge('start', 'dead-end', 0.9), _edge('start', 'via', 0.5), _edge('via', 'onward', 0.5)),
        )

        result = _generate(repo, start='start', bpm_min=100, bpm_max=130, length=3)

        self.assertEqual(('start', 'via', 'onward'), _track_ids(result))
        self.assertIsNone(_warning(result))

    def test_no_same_artist_back_to_back(self):
        repo = _FakePlaylistRepository(
            tracks=(
                _PlayableTrack('start', 120, '/library/start.flac', artist='Boards of Canada'),
                _PlayableTrack('same', 121, '/library/same.flac', artist='Boards of Canada'),
                _PlayableTrack('other', 122, '/library/other.flac', artist='Autechre'),
            ),
            edges=(_edge('start', 'same', 0.9), _edge('start', 'other', 0.5)),
        )

        result = _generate(repo, start='start', bpm_min=100, bpm_max=130, length=2)

        self.assertEqual(('start', 'other'), _track_ids(result))

    def _harmonic_repo(self, *, b_strength=0.9, b_overrides=()):
        # b relates more strongly to a, but only c is key-compatible (C major -> G major).
        return _FakePlaylistRepository(
            tracks=(_PlayableTrack('a', 120, '/library/a.flac', key='C', scale='major', key_strength=0.9),
                    _PlayableTrack('b', 120, '/library/b.flac', key='D', scale='major', key_strength=b_strength,
                                   manual_overrides=b_overrides),
                    _PlayableTrack('c', 120, '/library/c.flac', key='G', scale='major', key_strength=0.9)),
            edges=(_edge('a', 'b', 0.88), _edge('a', 'c', 0.82)))

    def _second_track(self, repo, **options):
        result = _load_use_case_class()(repo).execute(PlaylistRecipe(start_track_id='a', bpm_min=100, bpm_max=130, length=2, **options))
        return result.track_ids[1]

    def test_harmonic_mixing_is_on_by_default_and_prefers_a_compatible_key(self):
        self.assertEqual('c', self._second_track(self._harmonic_repo()))

    def test_harmonic_mixing_can_be_turned_off(self):
        self.assertEqual('b', self._second_track(self._harmonic_repo(), harmonic_mixing=False))

    def test_a_key_weaker_than_the_minimum_strength_is_neutral(self):
        repo = self._harmonic_repo(b_strength=0.4)

        self.assertEqual('b', self._second_track(repo, minimum_key_strength=0.5))
        self.assertEqual('c', self._second_track(repo, minimum_key_strength=0.3))

    def test_a_manual_key_override_makes_the_detected_key_unknown(self):
        self.assertEqual('b', self._second_track(self._harmonic_repo(b_overrides=('key',))))

    def test_harmonic_mixing_prefers_a_smooth_bpm_step(self):
        repo = _FakePlaylistRepository(
            tracks=(_PlayableTrack('a', 120, '/library/a.flac'), _PlayableTrack('b', 130, '/library/b.flac'),
                    _PlayableTrack('c', 122, '/library/c.flac')),
            edges=(_edge('a', 'b', 0.86), _edge('a', 'c', 0.83)))

        self.assertEqual('c', self._second_track(repo))

    def _energy_repo(self, *, a_b=0.9, a_c=0.85, b_overrides=()):
        # Energy levels (percentiles): d 0, a 1/3, c 2/3, b 1.
        return _FakePlaylistRepository(
            tracks=(_PlayableTrack('a', 120, '/library/a.flac', arousal=5.0),
                    _PlayableTrack('b', 120, '/library/b.flac', arousal=9.0, manual_overrides=b_overrides),
                    _PlayableTrack('c', 120, '/library/c.flac', arousal=5.2),
                    _PlayableTrack('d', 120, '/library/d.flac', arousal=1.0)),
            edges=(_edge('a', 'b', a_b), _edge('a', 'c', a_c)))

    def test_no_energy_arc_by_default_and_no_mood_evidence_is_read(self):
        repo = self._energy_repo()

        self.assertEqual('b', self._second_track(repo))
        self.assertEqual([], repo.mood_evidence_reads)

    def test_a_steady_arc_prefers_a_track_near_the_start_energy(self):
        self.assertEqual('c', self._second_track(self._energy_repo(), energy_plan=(EnergyArcRequest('steady'),)))

    def test_a_rising_arc_prefers_higher_energy_towards_the_end(self):
        repo = self._energy_repo(a_b=0.85, a_c=0.87)

        self.assertEqual('c', self._second_track(repo))
        self.assertEqual('b', self._second_track(repo, energy_plan=(EnergyArcRequest('rise'),)))

    def test_a_rising_arc_heads_for_the_high_of_its_energy_range(self):
        # #136: a rises from 1/3; capped at 0.7, c (2/3) is closer than b (1).
        repo = self._energy_repo(a_b=0.85, a_c=0.87)

        self.assertEqual('c', self._second_track(repo, energy_plan=(EnergyArcRequest('rise', energy_high=0.7),)))

    def test_an_invalid_energy_range_is_rejected_before_any_evidence_is_read(self):
        repo = self._energy_repo()

        with self.assertRaisesRegex(ValueError, 'Energy low must be below energy high'):
            self._second_track(repo, energy_plan=(EnergyArcRequest('rise', energy_low=0.8, energy_high=0.4),))
        self.assertEqual([], repo.mood_evidence_reads)

    def test_a_manual_energy_override_makes_the_arousal_unknown(self):
        # Known, b (level 1) misses the steady target (a, level 1/3) by more than c does.
        # Overridden, b costs only a quarter-range miss, while c (now level 1) misses a (now 1/2) by 1/2.
        self.assertEqual('c', self._second_track(self._energy_repo(a_b=0.85, a_c=0.85), energy_plan=(EnergyArcRequest('steady'),)))
        self.assertEqual('b', self._second_track(self._energy_repo(a_b=0.85, a_c=0.85, b_overrides=('energy',)),
                                                 energy_plan=(EnergyArcRequest('steady'),)))

    def test_a_dip_sinks_towards_the_low_end_where_a_rise_climbs(self):
        # #137: over four tracks the second sits a third of the way into the arc. From a (1/3),
        # a dip heads for 0.2, nearest d (0); a rise heads for about 0.5, nearest c (2/3).
        repo = _FakePlaylistRepository(
            tracks=self._energy_repo()._tracks, edges=(_edge('a', 'c', 0.9), _edge('a', 'd', 0.8)))

        def second(shape):
            recipe = PlaylistRecipe(start_track_id='a', bpm_min=100, bpm_max=130, length=4,
                                    energy_plan=(EnergyArcRequest(shape),))
            return _load_use_case_class()(repo).execute(recipe).track_ids[1]

        self.assertEqual('d', second('dip'))
        self.assertEqual('c', second('rise'))

    def test_an_unknown_arc_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'steady, rise, fall, peak or dip'):
            self._second_track(self._energy_repo(), energy_plan=(EnergyArcRequest('wave'),))

    def _mood_repo(self, *, b_overrides=()):
        return _FakePlaylistRepository(
            tracks=(_PlayableTrack('a', 120, '/library/a.flac', mood_scores=(('calm', 0.5),)),
                    _PlayableTrack('b', 120, '/library/b.flac', mood_scores=(('calm', 0.9),), manual_overrides=b_overrides),
                    _PlayableTrack('c', 120, '/library/c.flac')),
            edges=(_edge('a', 'b', 0.85), _edge('a', 'c', 0.87)))

    def test_a_mood_hold_prefers_tracks_stronger_in_that_mood(self):
        repo = self._mood_repo()

        self.assertEqual('b', self._second_track(repo, mood_hold='calm'))
        self.assertEqual(['calm'], repo.mood_evidence_reads)

    def test_a_manual_mood_override_makes_the_mood_score_unknown(self):
        # c has no mood score: neutral. Overridden, b is neutral too, so the stronger relation (c) wins.
        self.assertEqual('c', self._second_track(self._mood_repo(b_overrides=('mood',)), mood_hold='calm'))

    def test_a_mood_no_eligible_track_has_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "No eligible track has a score for the mood 'sunny'"):
            self._second_track(self._mood_repo(), mood_hold='sunny')

    def test_target_duration_instead_of_a_track_count(self):
        repo = _FakePlaylistRepository(
            tracks=tuple(_PlayableTrack(f't{i}', 120, f'/library/{i}.flac', duration_seconds=240.0) for i in range(6)),
            edges=tuple(_edge(f't{i}', f't{i + 1}', 0.9) for i in range(5)),
        )

        result = _load_use_case_class()(repo).execute(PlaylistRecipe(start_track_id='t0', bpm_min=100, bpm_max=130, duration_minutes=10))

        self.assertEqual(('t0', 't1', 't2'), _track_ids(result), '3 x 4 min reaches 10 min')
        self.assertIsNone(_warning(result))

    def test_duration_shortfall_is_reported(self):
        repo = _FakePlaylistRepository(
            tracks=(_PlayableTrack('a', 120, '/library/a.flac', duration_seconds=240.0),
                    _PlayableTrack('b', 120, '/library/b.flac', duration_seconds=240.0)),
            edges=(_edge('a', 'b', 0.9),),
        )

        result = _load_use_case_class()(repo).execute(PlaylistRecipe(start_track_id='a', bpm_min=100, bpm_max=130, duration_minutes=60))

        self.assertEqual(('a', 'b'), _track_ids(result))
        self.assertRegex(_warning(result) or '', 'shorter than the requested duration')

    def test_duration_mode_rejects_a_start_without_a_duration_and_invalid_targets(self):
        repo = _FakePlaylistRepository(
            tracks=(_PlayableTrack('start', 120, '/library/start.flac', duration_seconds=None),),
            edges=(),
        )
        use_case = _load_use_case_class()(repo)

        with self.assertRaisesRegex(ValueError, 'start track.*duration'):
            use_case.execute(PlaylistRecipe(start_track_id='start', bpm_min=100, bpm_max=130, duration_minutes=10))
        for bad in (0, -1, float('nan'), 1441, 'ten'):
            with self.subTest(duration_minutes=bad):
                with self.assertRaisesRegex(ValueError, 'duration'):
                    use_case.execute(PlaylistRecipe(start_track_id='start', bpm_min=100, bpm_max=130, duration_minutes=bad))
        with self.assertRaisesRegex(ValueError, 'length|duration'):
            use_case.execute(PlaylistRecipe(start_track_id='start', bpm_min=100, bpm_max=130))

    def test_manual_bpm_override_makes_the_detected_bpm_unusable_as_in_the_graph(self):
        # Issue #120: a spurious detected BPM is overridden; the playlist must not use it.
        repo = _FakePlaylistRepository(
            tracks=(
                _PlayableTrack('start', 120, '/library/start.flac'),
                _PlayableTrack('spurious', 121, '/library/spurious.flac', manual_overrides=('bpm',)),
                _PlayableTrack('next', 122, '/library/next.flac'),
            ),
            edges=(_edge('start', 'spurious', 0.99), _edge('start', 'next', 0.5)),
        )

        result = _generate(repo, start='start', bpm_min=100, bpm_max=130, length=2)

        self.assertEqual(('start', 'next'), _track_ids(result))

    def test_rejects_start_with_manual_bpm_override(self):
        repo = _FakePlaylistRepository(
            tracks=(_PlayableTrack('start', 120, '/library/start.flac', manual_overrides=('bpm',)),),
            edges=(),
        )

        with self.assertRaisesRegex(ValueError, 'start track.*manual BPM override'):
            _generate(repo, start='start', bpm_min=100, bpm_max=130, length=1)

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
        self.assertEqual(1, repo.track_reads)

    def test_reads_only_the_related_track_edges_not_the_whole_mood_graph(self):
        # Issue #129: building the mood-axis graph took ~5 s at ~3.4k tracks, for edges alone.
        repo = _FakePlaylistRepository(tracks=(_PlayableTrack('a', 120, '/library/a.flac'),
                                               _PlayableTrack('b', 120, '/library/b.flac')),
                                       edges=(_edge('a', 'b', 0.9),))

        result = _generate(repo, start='a', bpm_min=100, bpm_max=130, length=2)

        self.assertEqual(('a', 'b'), _track_ids(result))
        self.assertEqual(0, repo.graph_reads, 'the mood-axis graph is not built')
        self.assertEqual([10], repo.edge_reads, 'the same sparse_k=10 edges the graph shows')

    def test_edges_of_a_graph_that_is_not_ready_are_not_walked(self):
        repo = _FakePlaylistRepository(tracks=(_PlayableTrack('a', 120, '/library/a.flac'),
                                               _PlayableTrack('b', 120, '/library/b.flac')),
                                       edges=(_edge('a', 'b', 0.9),), graph_state='stale')

        result = _generate(repo, start='a', bpm_min=100, bpm_max=130, length=2)

        self.assertEqual(('a',), _track_ids(result))
        self.assertIsNotNone(result.warning)


if __name__ == '__main__':
    unittest.main()
