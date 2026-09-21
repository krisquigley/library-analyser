"""Read-only TOML and XDG configuration boundary. Never creates directories."""
from collections.abc import Mapping
import os
from pathlib import Path
import tomllib

from music_analyzer.application.dto.settings import Settings


class ConfigurationError(ValueError):
    """Invalid or unreadable user configuration, safe to present at the CLI."""


def _path(value: str, base: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ConfigurationError(f'{label}: provide a non-empty path string without NUL characters.')
    path = Path(value)
    return Path(os.path.abspath(path if path.is_absolute() else base / path))


def _validate_target(path: Path, *, directory: bool, label: str) -> None:
    try:
        if path.exists() and not (path.is_dir() if directory else path.is_file()):
            raise ConfigurationError(f'{label}: {path} must be a {"directory" if directory else "file"}. Choose another path.')
        for parent in path.parents:
            if parent.exists() and not parent.is_dir():
                raise ConfigurationError(f'{label}: parent {parent} is not a directory. Choose another path.')
    except OSError as error:
        raise ConfigurationError(f'{label}: cannot inspect {path}: {error}. Check path permissions.') from error


def load_settings(*, config: str | None = None, database: str | None = None,
                  model_directory: str | None = None,
                  environment: Mapping[str, str] | None = None,
                  cwd: Path | None = None) -> Settings:
    environment = os.environ if environment is None else environment
    cwd = Path.cwd() if cwd is None else cwd
    home = Path(environment['HOME']) if environment.get('HOME') else Path.home()

    def xdg(name: str, fallback: Path) -> Path:
        value = environment.get(name, '')
        return Path(value) if value and Path(value).is_absolute() else fallback

    config_path = (_path(config, cwd, '--config') if config is not None else
                   xdg('XDG_CONFIG_HOME', home / '.config') / 'music-analyzer/config.toml')
    data_home = xdg('XDG_DATA_HOME', home / '.local/share') / 'music-analyzer'
    values = {}
    loaded = False
    try:
        with config_path.open('rb') as stream:
            values = tomllib.load(stream)
        loaded = True
    except FileNotFoundError as error:
        if config is not None:
            raise ConfigurationError(f'{config_path}: configuration not found. Supply an existing --config file or omit --config for defaults.') from error
    except (OSError, ValueError) as error:
        raise ConfigurationError(f'{config_path}: cannot read TOML configuration: {error}. Fix the file or select another --config.') from error
    unknown = values.keys() - {'database', 'model_directory'}
    if unknown:
        raise ConfigurationError(f'{config_path}: unknown settings: {", ".join(sorted(unknown))}. Use only database and model_directory.')
    # Validate supplied config even when overridden, so typos are never hidden.
    configured = {key: _path(value, config_path.parent, f'{config_path}: {key}')
                  for key, value in values.items()}
    db = (_path(database, cwd, '--database') if database is not None else
          configured.get('database', data_home / 'analysis.sqlite'))
    models = (_path(model_directory, cwd, '--model-directory') if model_directory is not None else
              configured.get('model_directory', data_home / 'models'))
    _validate_target(db, directory=False, label='database (--database)')
    _validate_target(models, directory=True, label='model_directory (--model-directory)')
    return Settings(str(config_path), loaded, str(db), str(models))
