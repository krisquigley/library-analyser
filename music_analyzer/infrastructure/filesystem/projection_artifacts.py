"""Filesystem implementation of the prepared projection artifact store."""
import json
import os
from pathlib import Path
import tempfile
import stat

from music_analyzer.application.use_cases.projection_artifacts import ProjectionArtifactError, _validate_artifact


class FileProjectionArtifactStore:
    def __init__(self, artifact_path, source_database_path=None, max_bytes=64 * 1024 * 1024, protected_audio_paths=()):
        self.artifact_path = Path(artifact_path)
        self.source_database_path = Path(source_database_path).resolve() if source_database_path else None
        self.max_bytes = max_bytes
        self.protected_audio_paths = tuple(Path(path) for path in protected_audio_paths)

    def load(self):
        try:
            if self.artifact_path.stat().st_size > self.max_bytes:
                raise ProjectionArtifactError('resource_limit_exceeded')
            with self.artifact_path.open('r', encoding='utf-8') as handle:
                artifact = json.load(handle)
        except FileNotFoundError as error:
            raise ProjectionArtifactError('missing') from error
        except json.JSONDecodeError as error:
            raise ProjectionArtifactError('corrupt') from error
        _validate_artifact(artifact)
        return artifact

    def replace(self, artifact):
        self._ensure_safe_location()
        serializable = _serializable(artifact)
        _validate_artifact(serializable)
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.artifact_path.name + '.', suffix='.tmp', dir=str(self.artifact_path.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(serializable, handle, sort_keys=True, separators=(',', ':'), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            if tmp.stat().st_size > self.max_bytes:
                raise ProjectionArtifactError('resource_limit_exceeded')
            with tmp.open('r', encoding='utf-8') as handle:
                reread = json.load(handle)
            _validate_artifact(reread)
            os.replace(tmp, self.artifact_path)
            _fsync_directory(self.artifact_path.parent)
        except Exception:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise

    def _ensure_safe_location(self):
        if self.source_database_path and _matches_source_database(self.artifact_path, self.source_database_path):
            raise ProjectionArtifactError('safe artifact location must not overwrite source database')
        if _matches_known_audio(self.artifact_path, self.protected_audio_paths):
            raise ProjectionArtifactError('safe artifact location must not overwrite known catalogue audio')


def _matches_source_database(artifact_path, source_database_path):
    resolved = artifact_path.resolve()
    source = source_database_path.resolve()
    return resolved == source or str(resolved) in {str(source) + '-wal', str(source) + '-shm'}


def _matches_known_audio(artifact_path, protected_audio_paths):
    if not protected_audio_paths:
        return False
    artifact_resolved = artifact_path.resolve()
    artifact_stat = _stat_existing(artifact_path)
    for audio_path in protected_audio_paths:
        audio_resolved = audio_path.resolve()
        if artifact_resolved == audio_resolved:
            return True
        audio_stat = _stat_existing(audio_path)
        if artifact_stat and audio_stat and artifact_stat.st_ino == audio_stat.st_ino and artifact_stat.st_dev == audio_stat.st_dev:
            return True
    return False


def _stat_existing(path):
    try:
        return Path(path).stat()
    except FileNotFoundError:
        return None


def _serializable(artifact):
    return {key: value for key, value in artifact.items() if key != 'transform_object'}


def _fsync_directory(path):
    if not hasattr(os, 'O_DIRECTORY'):
        return
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
