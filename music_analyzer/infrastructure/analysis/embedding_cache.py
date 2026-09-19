"""Disposable JSON cache; atomic replace, digest integrity, oldest-write eviction.

Limits are per entry and per directory after a successful write; concurrent
writers can temporarily exceed the total. Never deserialize executable objects.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile


class FileEmbeddingCache:
    def __init__(self, root, max_bytes=256 * 1024**2, max_entry_bytes=16 * 1024**2):
        self.root = Path(root)
        self.max_bytes, self.max_entry_bytes = max_bytes, max_entry_bytes

    def _path(self, key):
        return self.root / (hashlib.sha256(key.encode()).hexdigest() + '.json')

    def get(self, key):
        try:
            with self._path(key).open('rb') as stream:
                data = stream.read(self.max_entry_bytes + 1)
            if len(data) > self.max_entry_bytes: return None
            envelope = json.loads(data)
            payload = envelope['payload']
            if envelope['sha256'] != hashlib.sha256(payload.encode()).hexdigest(): return None
            return tuple(tuple(tuple(row) for row in matrix) for matrix in json.loads(payload))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
            return None

    def put(self, key, value):
        temporary = None
        try:
            payload = json.dumps(value, allow_nan=False, separators=(',', ':'))
            data = json.dumps(dict(payload=payload, sha256=hashlib.sha256(payload.encode()).hexdigest())).encode()
            if len(data) > min(self.max_entry_bytes, self.max_bytes): return
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(dir=self.root, prefix='.write-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(key))
            entries = sorted(self.root.glob('*.json'), key=lambda p: p.stat().st_mtime_ns)
            total = sum(p.stat().st_size for p in entries)
            for path in entries:
                if total <= self.max_bytes: break
                size = path.stat().st_size
                path.unlink()
                total -= size
        except (OSError, ValueError, TypeError):
            pass  # Optional optimization; read-only/full disks must not fail analysis.
        finally:
            if temporary is not None:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass
