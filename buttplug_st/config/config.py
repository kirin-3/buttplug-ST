"""Runtime settings assembled from layered sources.

Precedence (highest first): CLI flags -> BUTTPLUG_* environment variables ->
user config file (--config) -> packaged default.toml. Each layer only fills
values the higher layers did not set.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

ENV_PREFIX = "BUTTPLUG_"
DEFAULT_CONFIG_PATH = Path(__file__).parent / "default.toml"

_TRUTHY = {"true", "1", "yes"}
_FALSY = {"false", "0", "no"}


class SettingsError(Exception):
    """A settings source is missing, unparsable, or contains an invalid value."""


def _parse_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSY:
        return False
    raise ValueError(f"expected one of {sorted(_TRUTHY | _FALSY)}")


def _parse_int(raw: str) -> int:
    return int(raw.strip())


def _parse_float(raw: str) -> float:
    return float(raw.strip())


_ENV_PARSERS: dict[type, Any] = {
    bool: _parse_bool,
    int: _parse_int,
    float: _parse_float,
    str: str,
}


class ServerConfig(BaseModel):
    """HTTP server settings."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="localhost", description="HTTP host to bind")
    port: int = Field(default=3069, ge=1, le=65535, description="HTTP port to bind")
    debug: bool = Field(default=False, description="Quart debug mode")


class WebsocketConfig(BaseModel):
    """Intiface Central connection settings."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        default="ws://127.0.0.1:12345",
        description="Intiface Central websocket URL",
    )
    scan_timeout: float = Field(
        default=2.0,
        gt=0,
        description="Seconds to wait for a device scan to finish",
    )


class DeviceConfig(BaseModel):
    """Default device command parameters."""

    model_config = ConfigDict(extra="forbid")

    default_speed: float = Field(default=0.5, ge=0.0, le=1.0, description="Default vibration speed")
    default_position: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Default position for devices that support position",
    )
    default_duration: float = Field(
        default=0.0,
        ge=0.0,
        description="Default auto-stop duration in seconds (0 = until stopped)",
    )


class Settings(BaseModel):
    """Effective runtime settings."""

    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = Field(default_factory=ServerConfig)
    websocket: WebsocketConfig = Field(default_factory=WebsocketConfig)
    device: DeviceConfig = Field(default_factory=DeviceConfig)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Settings:
        """Build settings from packaged defaults, an optional user file, and the environment.

        A user-supplied ``config_path`` that is missing or unparsable raises
        :class:`SettingsError` naming the file; defaults are never silently
        substituted for an explicitly requested file.
        """
        if config_path is None:
            data = _load_toml(DEFAULT_CONFIG_PATH)
        else:
            path = Path(config_path)
            if not path.is_file():
                raise SettingsError(f"config file not found: {path}")
            data = _load_toml(path)
        try:
            settings = cls.model_validate(data)
        except PydanticValidationError as exc:
            raise SettingsError(f"invalid settings in config file {path}: {exc}") from exc
        _apply_env_overrides(settings)
        return settings

    def apply_updates(self, updates: dict[str, dict[str, Any]]) -> None:
        """Apply the highest-precedence layer, ``{section: {field: value}}``."""
        for section_name, fields in updates.items():
            section = getattr(self, section_name, None)
            if section is None or not isinstance(section, BaseModel):
                raise SettingsError(f"unknown settings section: {section_name}")
            for key, value in fields.items():
                if key not in type(section).model_fields:
                    raise SettingsError(f"unknown settings key: {section_name}.{key}")
                setattr(section, key, value)


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError as exc:
        raise SettingsError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"config file is not valid TOML: {path} ({exc})") from exc


def _apply_env_overrides(settings: Settings) -> None:
    for section_name in type(settings).model_fields:
        section = getattr(settings, section_name)
        for field_name in type(section).model_fields:
            var = f"{ENV_PREFIX}{section_name.upper()}_{field_name.upper()}"
            raw = os.environ.get(var)
            if raw is None:
                continue
            annotation = type(section).model_fields[field_name].annotation
            setattr(section, field_name, _coerce_env_value(var, raw, annotation))


def _coerce_env_value(var: str, raw: str, annotation: Any) -> Any:
    parser = _ENV_PARSERS.get(annotation)
    if parser is None:
        raise SettingsError(f"{var}: unsupported field type {annotation!r}")
    try:
        return parser(raw)
    except ValueError as exc:
        raise SettingsError(
            f"{var}: invalid value {raw!r} for type {getattr(annotation, '__name__', annotation)}"
        ) from exc
