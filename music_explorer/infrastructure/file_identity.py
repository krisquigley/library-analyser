"""A file's identity as the analyzer's scan records it: the hex SHA-256 of all its bytes (#132)."""
import hashlib

_CHUNK = 1024 * 1024


class Sha256FileIdentity:
    def sha256(self, location: str) -> str | None:
        digest = hashlib.sha256()
        try:
            with open(location, 'rb') as audio:
                for chunk in iter(lambda: audio.read(_CHUNK), b''):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()
