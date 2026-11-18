"""TOML-backed application settings with environment variable overrides."""

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when application configuration cannot be read or validated."""


def _normalize_log_level(value: object, source: str) -> str:
    if not isinstance(value, str) or value.upper() not in logging.getLevelNamesMapping():
        raise ConfigurationError(f"{source}: expected a valid logging level name.")
    return value.upper()


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings shared by application modules."""

    log_level: str = "INFO"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "log_level",
            _normalize_log_level(self.log_level, "Settings.log_level"),
        )


def load_settings(path: str | Path | None = None) -> Settings:
    """Load defaults, TOML settings, then DYNALOOP_* environment overrides.

    The optional TOML file uses a ``[dynaloop]`` table. An explicitly supplied
    file must be readable; read and parse errors are reported to the caller.
    """
    log_level = "INFO"

    if path is not None:
        config_path = Path(path)
        try:
            with config_path.open("rb") as config_file:
                data = tomllib.load(config_file)
        except OSError as exc:
            raise ConfigurationError(f"Unable to read configuration file '{config_path}': {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"Invalid TOML in '{config_path}': {exc}") from exc

        unknown_sections = set(data) - {"dynaloop"}
        if unknown_sections:
            names = ", ".join(sorted(unknown_sections))
            raise ConfigurationError(
                f"Configuration file '{config_path}': unknown top-level section(s): {names}"
            )

        section = data.get("dynaloop", {})
        if not isinstance(section, dict):
            raise ConfigurationError(
                f"Configuration file '{config_path}': [dynaloop] must be a TOML table."
            )

        unknown_keys = set(section) - {"log_level"}
        if unknown_keys:
            names = ", ".join(sorted(unknown_keys))
            raise ConfigurationError(
                f"Configuration file '{config_path}': unknown [dynaloop] setting(s): {names}"
            )

        if "log_level" in section:
            log_level = _normalize_log_level(
                section["log_level"],
                f"Configuration file '{config_path}', [dynaloop].log_level",
            )

    env_log_level = os.environ.get("DYNALOOP_LOG_LEVEL")
    if env_log_level is not None:
        log_level = _normalize_log_level(env_log_level, "Environment variable DYNALOOP_LOG_LEVEL")

    return Settings(log_level=log_level)
