"""Read-only local FFmpeg decoding to bounded disposable mono float32 PCM.

FFmpeg gets one second beyond the requested cap as an overflow sentinel. Such
output is rejected, never presented as a complete track. No whole-audio Python
buffer is allocated. At the hard 5000s cap, PCM uses at most ~882 MB on disk; decode preflights
that plus the bounded compressed snapshot with margin before writing.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, DecodedAudio
from music_analyzer.domain.analysis import MAX_ANALYSIS_DURATION_SECONDS, PCM_BYTES_PER_SECOND, finite


class FFmpegDecoder:
    def __init__(self, executable: str = 'ffmpeg', max_source_bytes: int = 512 * 1024**2):
        self.max_source_bytes = max_source_bytes
        self._executable = executable

    @contextmanager
    def decode(self, source: AudioSource, max_duration: float):
        if not finite(max_duration) or not 0 < max_duration <= MAX_ANALYSIS_DURATION_SECONDS:
            raise AnalysisError(f'Maximum duration must be positive and at most {MAX_ANALYSIS_DURATION_SECONDS} seconds')
        path = Path(source.location).absolute()
        try:
            if not path.is_file():
                raise AnalysisError('Audio source must be an existing local file')
            source_size = path.stat().st_size
            with tempfile.TemporaryDirectory(prefix='music-analyzer-audio-') as directory:
                required = min(source_size, self.max_source_bytes) + int((max_duration + 1) * PCM_BYTES_PER_SECOND) + 128 * 1024**2
                if shutil.disk_usage(directory).free < required:
                    raise AnalysisError('Insufficient temporary disk space for bounded decode')
                snapshot = Path(directory) / ('source' + path.suffix)
                identity = hashlib.sha256()
                size = 0
                with path.open('rb') as original, snapshot.open('wb') as target:
                    while chunk := original.read(1024 * 1024):
                        size += len(chunk)
                        if size > self.max_source_bytes:
                            raise AnalysisError('Audio exceeds compressed snapshot limit')
                        target.write(chunk)
                        identity.update(chunk)
                if source.expected_identity and source.expected_identity != 'sha256:' + identity.hexdigest():
                    raise AnalysisError('Audio identity changed; rescan before analysis')
                snapshot.chmod(0o400)
                output = Path(directory) / 'mono-44100.f32'
                command = [self._executable, '-nostdin', '-v', 'error', '-xerror',
                           '-protocol_whitelist', 'file', '-i', str(snapshot),
                           '-map', '0:a:0', '-vn', '-sn', '-dn', '-ac', '1', '-ar', '44100',
                           '-t', str(max_duration + 1), '-f', 'f32le', str(output)]
                # Do not accumulate untrusted stderr in memory. Exceptions retain
                # actionable context; detailed codec diagnosis is a separate step.
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                timeout = min(900, max(120, int(max_duration / 5)))
                try:
                    returncode = process.wait(timeout=timeout)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                if returncode:
                    raise AnalysisError('FFmpeg could not decode audio; check the file and codec support')
                size = output.stat().st_size
                if size == 0 or size % 4:
                    raise AnalysisError('FFmpeg produced empty or invalid audio')
                duration = size / (4 * 44100)
                if duration > max_duration:
                    raise AnalysisError(f'Audio exceeds duration limit; increase it explicitly (maximum {MAX_ANALYSIS_DURATION_SECONDS}s)')
                with output.open('rb') as stream:
                    pcm_identity = hashlib.file_digest(stream, 'sha256').hexdigest()
                yield DecodedAudio(str(output), duration, 44100,
                                   identity.hexdigest() + ':' + pcm_identity)
        except subprocess.TimeoutExpired as error:
            raise AnalysisError('FFmpeg decoding exceeded the bounded timeout; no partial audio retained') from error
        except OSError as error:
            raise AnalysisError(f'Unable to decode local audio: {error}') from error
