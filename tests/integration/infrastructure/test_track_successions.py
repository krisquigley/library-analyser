"""Issue #223: a tags-only rescan keeps the track's analysis and overrides, against a real analysis database."""
from contextlib import closing, redirect_stdout
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.use_cases.carry_over_tag_changes.carry_over_tag_changes import (
    CarryOverTagChanges, TrackEvidenceCarriedOver)
from music_analyzer.application.use_cases.scan_library import ScanLibrary
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.track_succession import TrackSuccession
from music_analyzer.frameworks.cli.main import main as analyzer_main
from music_analyzer.infrastructure.filesystem.inventory import LocalInventory
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_analyzer.infrastructure.persistence.track_successions import SQLiteTrackSuccessions
from tests.support.synthetic_tagged_audio import MP3_AUDIO, with_id3v2

import hashlib

AUDIO_SHA256 = hashlib.sha256(MP3_AUDIO).hexdigest()


class TimedMetadata:
    def read(self, location):
        return TrackMetadata(duration_seconds=180.0, duration_source='mutagen')


def analysis_stages():
    return (
        StageResult('bpm', (('algorithm', 'test-bpm'),), 'steady', (('bpm', 121.0),)),
        StageResult('key', (('algorithm', 'test-key'),), 'top label',
                    (('key', '8A'), ('scale', 'minor'), ('strength', 0.7), ('coverage', 1.0))),
        StageResult('genres', (('algorithm', 'test-genre'),), 'multi-label', (('genre', 'house'),)),
        StageResult('mood', (('algorithm', 'test-mood'),), 'uncalibrated',
                    summary=ScoreSummary(('happy', 'dark'), (0.75, 0.20), (0.70, 0.10), (0.80, 0.30), 1.0)),
        StageResult('energy', (('algorithm', 'test-energy'),), 'uncalibrated',
                    summary=ScoreSummary(('energy',), (0.66,), (0.60,), (0.70,), 1.0)),
    )


class RecordingEvents:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


class TagsOnlyRescanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'music'
        self.root.mkdir()
        self.db = str(Path(temp.name) / 'analysis.sqlite')
        self.song = self.root / 'song.mp3'
        self.events = RecordingEvents()

    def scan(self):
        files = ScanLibrary(LocalInventory(TimedMetadata()), SQLiteAnalysisRepository(self.db)).execute(str(self.root)).files
        return {Path(file.location).name: file.identity.track_id for file in files}

    def carry_over(self):
        return CarryOverTagChanges(SQLiteTrackSuccessions(self.db), self.events).execute()

    def analysed_track(self):
        self.song.write_bytes(with_id3v2(MP3_AUDIO, b'first tags' + bytes(30)))
        old = self.scan()['song.mp3']
        repository = SQLiteAnalysisRepository(self.db)
        run_id = repository.start(AudioSource(str(self.song), old))
        for stage in analysis_stages():
            repository.save_stage(run_id, stage)
        repository.finish(run_id, 'completed', '')
        repository.set_override(old, 'bpm', '124')
        return old, run_id

    def rows(self, sql, *parameters):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute(sql, parameters).fetchall()

    def test_a_tags_only_change_keeps_the_analysis_and_overrides(self):
        old, run_id = self.analysed_track()
        self.song.write_bytes(with_id3v2(MP3_AUDIO, b'BPM 124 written' + bytes(80)))
        new = self.scan()['song.mp3']
        self.assertNotEqual(new, old)
        self.assertEqual(self.carry_over(), (TrackSuccession(old, new, AUDIO_SHA256),))
        self.assertEqual(self.events.published, [TrackEvidenceCarriedOver(old, new)])
        self.assertEqual(self.rows('SELECT track_id FROM run_tracks WHERE run_id=?', run_id), [(new,)])
        self.assertEqual(self.rows('SELECT track_id,field,value FROM overrides'), [(new, 'bpm', '124')])
        self.assertEqual(self.rows('SELECT track_id,run_id FROM graph_feature_evidence WHERE is_current=1'), [(new, run_id)])
        self.assertEqual(self.rows('SELECT count(*) FROM graph_feature_evidence WHERE track_id=?', old), [(0,)])
        self.assertEqual(self.rows('SELECT predecessor_id,successor_id,audio_sha256 FROM track_successions'),
                         [(old, new, AUDIO_SHA256)])
        self.assertEqual(self.carry_over(), (), 'running again carries nothing more')
        with redirect_stdout(io.StringIO()) as report:
            self.assertEqual(analyzer_main(['--database', self.db, 'integrity']), 0, report.getvalue())

    def test_an_audio_change_keeps_nothing(self):
        old, run_id = self.analysed_track()
        self.song.write_bytes(with_id3v2(MP3_AUDIO[:-1] + b'\x01', b'first tags' + bytes(30)))
        self.scan()
        self.assertEqual(self.carry_over(), ())
        self.assertEqual(self.rows('SELECT track_id FROM run_tracks WHERE run_id=?', run_id), [(old,)])

    def test_a_track_whose_file_is_still_present_elsewhere_is_not_continued(self):
        old, run_id = self.analysed_track()
        (self.root / 'copy.mp3').write_bytes(self.song.read_bytes())
        self.song.write_bytes(with_id3v2(MP3_AUDIO, b'retagged' + bytes(60)))
        self.scan()
        self.assertEqual(self.carry_over(), ())
        self.assertEqual(self.rows('SELECT track_id FROM overrides'), [(old,)])

    def test_a_new_file_that_was_already_analysed_keeps_its_own_analysis(self):
        old, _ = self.analysed_track()
        self.song.write_bytes(with_id3v2(MP3_AUDIO, b'retagged' + bytes(60)))
        new = self.scan()['song.mp3']
        repository = SQLiteAnalysisRepository(self.db)
        own_run = repository.start(AudioSource(str(self.song), new))
        repository.finish(own_run, 'failed', 'synthetic failure')
        self.assertEqual(self.carry_over(), ())
        self.assertEqual(self.rows('SELECT track_id FROM overrides'), [(old,)])


    def test_a_pairing_that_stops_holding_before_it_is_carried_over_changes_nothing(self):
        old, run_id = self.analysed_track()
        self.song.write_bytes(with_id3v2(MP3_AUDIO, b'retagged' + bytes(60)))
        new = self.scan()['song.mp3']
        successions = SQLiteTrackSuccessions(self.db)
        self.assertEqual([t.track_id for t in successions.candidates().arrivals], [new])
        SQLiteAnalysisRepository(self.db).set_override(new, 'key', 'A minor')
        self.assertFalse(successions.carry_over(TrackSuccession(old, new, AUDIO_SHA256)))
        self.assertEqual(self.rows('SELECT track_id FROM run_tracks WHERE run_id=?', run_id), [(old,)])
        self.assertEqual(self.rows('SELECT count(*) FROM track_successions'), [(0,)])

    def test_a_saved_recipe_starting_on_the_retagged_track_follows_it(self):
        from music_analyzer.domain.playlist_recipe import VERSION, PlaylistRecipe
        from music_analyzer.infrastructure.persistence.playlist_recipes import SQLitePlaylistRecipeStore
        old, _ = self.analysed_track()
        recipes = SQLitePlaylistRecipeStore(self.db)
        for name, start in (('Warm-up', old), ('Elsewhere', 'sha256:' + '9' * 64)):
            document = PlaylistRecipe(start, 118.0, 126.0, ('tracks', 12), False, 0.5, (), None).to_document()
            recipes.store_recipe(name, document, VERSION)
        self.song.write_bytes(with_id3v2(MP3_AUDIO, b'retagged' + bytes(60)))
        new = self.scan()['song.mp3']
        self.carry_over()
        starts = {recipe.name: recipe.document['start_track_id'] for recipe in recipes.stored_recipes()}
        self.assertEqual(starts, {'Warm-up': new, 'Elsewhere': 'sha256:' + '9' * 64})
        with redirect_stdout(io.StringIO()) as report:
            self.assertEqual(analyzer_main(['--database', self.db, 'integrity']), 0, report.getvalue())

if __name__ == '__main__':
    unittest.main()
