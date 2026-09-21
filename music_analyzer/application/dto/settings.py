"""Resolved configuration values; no filesystem or environment dependencies."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    config_file: str
    config_loaded: bool
    database: str
    model_directory: str
