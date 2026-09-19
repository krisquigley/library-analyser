"""Official Essentia standard APIs; native framing stays inside the predictors.

Three disjoint sections, at most 90s total, for semantic estimates. Coverage is
section exposure, not independent frame coverage or calibrated confidence.
An instance owns only one track's in-memory embedding reuse; no disk cache.
"""
from music_analyzer.application.dto.analysis import AnalysisError, StageResult
from music_analyzer.domain.analysis import ScoreWindow, finite, summarize_scores

HEADS = {'genres': 'genre_discogs400-discogs-effnet-1',
         'mood': 'mtg_jamendo_moodtheme-discogs-effnet-1',
         'instruments': 'mtg_jamendo_instrument-discogs-effnet-1',
         'energy': 'emomusic-msd-musicnn-2'}


def sample_regions(duration):
    if not finite(duration) or duration <= 0:
        raise ValueError('Positive finite duration required')
    if duration <= 90:
        return ((0, duration),)
    return ((0, 30), ((duration - 30) / 2, (duration + 30) / 2), (duration - 30, duration))


class PCMReader:
    def __init__(self, numpy, library):
        self.numpy, self.library = numpy, library

    def __call__(self, audio, start, end, rate):
        # Seek the once-decoded PCM; only requested sections enter RAM.
        with open(audio.handle, 'rb') as stream:
            stream.seek(round(start * audio.sample_rate) * 4)
            values = self.numpy.fromfile(stream, dtype='<f4',
                                         count=round((end - start) * audio.sample_rate))
        if rate != audio.sample_rate:
            values = self.library.Resample(inputSampleRate=audio.sample_rate,
                                          outputSampleRate=rate, quality=1)(values)
        return values


def load_backend():
    try:
        import essentia
        import essentia.standard as library
        import numpy
        for name in ('RhythmExtractor2013', 'KeyExtractor', 'Resample',
                     'TensorflowPredictEffnetDiscogs', 'TensorflowPredictMusiCNN', 'TensorflowPredict2D'):
            if not hasattr(library, name):
                raise ImportError(f'{name} unavailable')
        return library, essentia.__version__, PCMReader(numpy, library)
    except (ImportError, OSError) as error:
        raise AnalysisError('Essentia with TensorFlow and NumPy required; use a compatible isolated Python environment and run doctor. ' + str(error)) from error


class EssentiaEngine:
    def __init__(self, library, version, manifest, resolve_model, read_audio):
        self.library, self.version, self.manifest = library, version, manifest
        self.resolve_model, self.read_audio = resolve_model, read_audio
        self._audio = None
        self._embeddings = {}
        self._predictors = {}
        self._hashes = {}

    def _predictor(self, model, purpose):
        if model not in self._predictors:
            metadata = self.manifest[model]['metadata']
            path, checksum = self.resolve_model(model)
            self._hashes[model] = checksum
            output = next(item['name'] for item in metadata['schema']['outputs']
                          if item['output_purpose'] == purpose)
            algorithm = metadata['inference']['algorithm']
            params = dict(graphFilename=path, input=metadata['schema']['inputs'][0]['name'], output=output)
            if algorithm == 'TensorflowPredict2D':
                params.update(dimensions=metadata['schema']['inputs'][0]['shape'][-1], patchSize=1, batchSize=64)
            else:
                params.update(lastPatchMode='repeat', batchSize=64)
                if algorithm == 'TensorflowPredictEffnetDiscogs':
                    params.update(lastBatchMode='same', patchSize=128, patchHopSize=62)
                else:
                    params.update(patchSize=187, patchHopSize=93)
            self._predictors[model] = getattr(self.library, algorithm)(**params)
        return self._predictors[model]

    def analyze(self, stage, audio):
        try:
            if audio.sample_rate != 44100:
                raise ValueError('Expected decoder mono 44100Hz PCM')
            if audio != self._audio:
                self._audio, self._embeddings = audio, {}
            provenance = [('engine', 'Essentia'), ('version', str(self.version))]
            if stage in ('bpm', 'key'):
                signal = self.read_audio(audio, 0, audio.duration, 44100)
                if stage == 'bpm':
                    bpm, _, confidence, _, _ = self.library.RhythmExtractor2013(method='multifeature')(signal)
                    values = (('bpm', float(bpm)), ('confidence', float(confidence)))
                else:
                    key, scale, strength = self.library.KeyExtractor(sampleRate=44100)(signal)
                    values = (('key', str(key)), ('scale', str(scale)), ('strength', float(strength)))
                if any(not finite(value) for _, value in values if not isinstance(value, str)):
                    raise ValueError('nonfinite output')
                return StageResult(stage, tuple(provenance),
                    'Whole-track estimate; strength/confidence not calibrated. Tempo octave and key ambiguity unresolved.',
                    values + (('coverage', 1.0),))
            model = HEADS[stage]
            metadata = self.manifest[model]['metadata']
            embedding_model = metadata['inference']['embedding_model']['model_name']
            regions = sample_regions(audio.duration)
            if embedding_model not in self._embeddings:
                predictor = self._predictor(embedding_model, 'embeddings')
                rate = self.manifest[embedding_model]['metadata']['inference']['sample_rate']
                self._embeddings[embedding_model] = tuple(predictor(self.read_audio(audio, start, end, rate))
                                                          for start, end in regions)
            width = metadata['schema']['inputs'][0]['shape'][-1]
            for embedding in self._embeddings[embedding_model]:
                if len(embedding) == 0 or any(len(row) != width or not all(finite(float(v)) for v in row) for row in embedding):
                    raise ValueError('invalid embedding output shape or nonfinite output')
            predictor = self._predictor(model, 'predictions')
            labels = tuple(metadata['classes'])
            windows = []
            for (start, end), embeddings in zip(regions, self._embeddings[embedding_model]):
                rows = tuple(tuple(float(score) for score in row) for row in predictor(embeddings))
                if len(rows) != len(embeddings) or not rows or any(len(row) != len(labels) or not all(finite(v) for v in row) for row in rows):
                    raise ValueError('invalid output shape or nonfinite output')
                mean = tuple(sum(row[i] / len(rows) for row in rows) for i in range(len(labels)))
                windows.append(ScoreWindow(start, end, mean))
            provenance.extend([(m, self._hashes[m]) for m in (embedding_model, model)])
            provenance.extend([('sampling', 'disjoint-sections-v1; <=90s; native overlapping patches; repeat final patch'),
                               ('aggregation', 'native patch mean per section; duration-weighted section mean')])
            uncertainty = 'Section exposure coverage; patch means, not calibrated probabilities; section ranges may hide brief events.'
            if stage == 'energy':
                uncertainty += ' Provisional energy proxy: raw arousal only, with valence retained; no DJ energy scale or thresholds.'
            return StageResult(stage, tuple(provenance), uncertainty, windows=tuple(windows),
                               summary=summarize_scores(labels, tuple(windows), audio.duration))
        except AnalysisError:
            raise
        except (RuntimeError, ValueError, TypeError, KeyError, OSError, AttributeError, StopIteration) as error:
            raise AnalysisError(f'Essentia {stage} failed: {error}; verify model bundles and TensorFlow-enabled Essentia compatibility') from error


class VerifiedModels:
    """Read-only resolution; never download implicitly during analysis."""
    def __init__(self, storage):
        self.storage = storage

    def __call__(self, model):
        from music_analyzer.application.dto.models import ModelError
        from music_analyzer.infrastructure.models.storage import digest
        try:
            self.storage.verify(model)
            path = self.storage.root / model / 'model.pb'
            return str(path), digest(path)
        except ModelError as error:
            raise AnalysisError(f'{error} Obtain approval before models download; analysis never downloads weights.') from error
