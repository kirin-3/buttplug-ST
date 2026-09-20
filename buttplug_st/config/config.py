"""Runtime settings assembled from layered sources.

Precedence (highest first): CLI flags -> BUTTPLUG_* environment variables ->
user config file (--config) -> packaged default.toml. Each layer only fills
values the higher layers did not set.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

ENV_PREFIX = "BUTTPLUG_"
DEFAULT_CONFIG_PATH = Path(__file__).parent / "default.toml"

_TRUTHY = {"true", "1", "yes"}
_FALSY = {"false", "0", "no"}

StrParser = Callable[[str], object]


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


#: Per-section string parsers for BUTTPLUG_* environment variables. Every
#: settings field must appear here (guarded by a test).
ENV_FIELD_PARSERS: dict[str, dict[str, StrParser]] = {
    "server": {"host": str, "port": _parse_int, "debug": _parse_bool},
    "websocket": {"url": str, "scan_timeout": _parse_float},
    "device": {
        "default_speed": _parse_float,
        "default_position": _parse_float,
        "default_duration": _parse_float,
    },
}


class ServerConfig(BaseModel):
    """HTTP server settings."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", validate_assignment=True)

    host: str = Field(default="localhost", description="HTTP host to bind")
    port: int = Field(default=3069, ge=1, le=65535, description="HTTP port to bind")
    debug: bool = Field(default=False, description="Quart debug mode")


class WebsocketConfig(BaseModel):
    """Intiface Central connection settings."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", validate_assignment=True)

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

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", validate_assignment=True)

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

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", validate_assignment=True)

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
        path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
        if config_path is not None and not path.is_file():
            raise SettingsError(f"config file not found: {path}")
        data = _load_toml(path)
        try:
            settings = cls.model_validate(data)
        except PydanticValidationError as exc:
            raise SettingsError(f"invalid settings in config file {path}: {exc}") from exc
        _apply_env_overrides(settings)
        return settings

    def apply_updates(self, updates: dict[str, dict[str, object]]) -> None:
        """Apply the highest-precedence layer, ``{section: {field: value}}``."""
        sections: dict[str, BaseModel] = {
            "server": self.server,
            "websocket": self.websocket,
            "device": self.device,
        }
        for section_name, fields in updates.items():
            section = sections.get(section_name)
            if section is None:
                raise SettingsError(f"unknown settings section: {section_name}")
            for key, value in fields.items():
                if key not in type(section).model_fields:
                    raise SettingsError(f"unknown settings key: {section_name}.{key}")
                try:
                    setattr(section, key, value)
                except PydanticValidationError as exc:
                    detail = _describe_validation_error(exc)
                    raise SettingsError(
                        f"invalid value for {section_name}.{key}: {detail}"
                    ) from exc


def _load_toml(path: Path) -> dict[str, object]:
    try:
        with open(path, "rb") as fh:
            loaded: dict[str, object] = tomllib.load(fh)
            return loaded
    except FileNotFoundError as exc:
        raise SettingsError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"config file is not valid TOML: {path} ({exc})") from exc


def _apply_env_overrides(settings: Settings) -> None:
    sections: dict[str, BaseModel] = {
        "server": settings.server,
        "websocket": settings.websocket,
        "device": settings.device,
    }
    for section_name, field_parsers in ENV_FIELD_PARSERS.items():
        section = sections[section_name]
        for field_name, parser in field_parsers.items():
            var = f"{ENV_PREFIX}{section_name.upper()}_{field_name.upper()}"
            raw = os.environ.get(var)
            if raw is None:
                continue
            try:
                value = parser(raw)
            except ValueError as exc:
                raise SettingsError(f"{var}: invalid value {raw!r} ({exc})") from exc
            try:
                setattr(section, field_name, value)
            except PydanticValidationError as exc:
                raise SettingsError(f"{var}: {_describe_validation_error(exc)}") from exc


def _describe_validation_error(exc: PydanticValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "value"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
