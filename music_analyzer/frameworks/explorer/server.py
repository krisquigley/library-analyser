"""Compatibility wrapper for the standalone music_explorer server."""
from music_explorer.frameworks.explorer import server as _standalone


def create_server(database_path: str, host: str = '127.0.0.1', port: int = 8765):
    """Return the standalone explorer server for existing analyzer callers."""
    return _standalone.create_server(database_path, host, port)
