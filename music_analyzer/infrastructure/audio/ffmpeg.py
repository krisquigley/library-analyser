"""Read-only local FFmpeg decoding to bounded disposable mono float32 PCM.

FFmpeg gets one second beyond the requested cap as an overflow sentinel. Such
output is rejected, never presented as a complete track. No whole-audio Python
buffer is allocated. At the hard 3600s cap, PCM uses at most ~606 MiB on disk.
"""
from contextlib import contextmanager
from pathlib import Path
import subprocess
import tempfile

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, DecodedAudio
from music_analyzer.domain.analysis import finite


class FFmpegDecoder:
    def __init__(self, executable: str = 'ffmpeg'):
        self._executable = executable

    @contextmanager
    def decode(self, source: AudioSource, max_duration: float):
        if not finite(max_duration) or not 0 < max_duration <= 3600:
            raise AnalysisError('Maximum duration must be positive and at most 3600 seconds')
        path = Path(source.location).absolute()
        try:
            if not path.is_file():
                raise AnalysisError('Audio source must be an existing local file')
            with tempfile.TemporaryDirectory(prefix='music-analyzer-audio-') as directory:
                output = Path(directory) / 'mono-44100.f32'
                command = [self._executable, '-nostdin', '-v', 'error', '-xerror',
                           '-protocol_whitelist', 'file', '-i', str(path),
                           '-map', '0:a:0', '-vn', '-sn', '-dn', '-ac', '1', '-ar', '44100',
                           '-t', str(max_duration + 1), '-f', 'f32le', str(output)]
                # Do not accumulate untrusted stderr in memory. Exceptions retain
                # actionable context; detailed codec diagnosis is a separate step.
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    returncode = process.wait(timeout=120)
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
                    raise AnalysisError('Audio exceeds duration limit; increase it explicitly (maximum 3600s)')
                yield DecodedAudio(str(output), duration, 44100)
        except subprocess.TimeoutExpired as error:
            raise AnalysisError('FFmpeg decoding exceeded 120 seconds; no partial audio retained') from error
        except OSError as error:
            raise AnalysisError(f'Unable to decode local audio: {error}') from error
