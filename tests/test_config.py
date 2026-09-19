"""Settings resolution: packaged defaults, user config file, environment, CLI precedence."""

from __future__ import annotations

import pytest

from buttplug_st.app import load_settings
from buttplug_st.config import Settings, SettingsError


def test_defaults_load_with_no_input():
    settings = Settings.load()
    assert settings.server.host == "localhost"
    assert settings.server.port == 3069
    assert settings.server.debug is False
    assert settings.websocket.url == "ws://127.0.0.1:12345"
    assert settings.websocket.scan_timeout == 2.0
    assert settings.device.default_speed == 0.5
    assert settings.device.default_position == 0.5
    assert settings.device.default_duration == 0.0


def test_user_config_file_overrides_defaults(tmp_path):
    cfg = tmp_path / "user.toml"
    cfg.write_text(
        '[server]\nport = 4000\n[websocket]\nurl = "ws://127.0.0.1:9999"\n',
        encoding="utf-8",
    )
    settings = Settings.load(cfg)
    assert settings.server.port == 4000
    assert settings.websocket.url == "ws://127.0.0.1:9999"
    assert settings.server.debug is False  # untouched default survives


def test_missing_config_file_aborts_naming_file(tmp_path):
    missing = tmp_path / "nonexistent.toml"
    with pytest.raises(SettingsError, match="nonexistent"):
        Settings.load(missing)


def test_unparsable_config_file_aborts_naming_file(tmp_path):
    cfg = tmp_path / "broken.toml"
    cfg.write_text("[server]\nport = 4000\n[unknown_section]\nx = 1\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="broken"):
        Settings.load(cfg)


def test_boolean_env_false_disables_debug(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUTTPLUG_SERVER_DEBUG", "false")
    assert Settings.load().server.debug is False


def test_boolean_env_numeric_zero_disables_debug(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUTTPLUG_SERVER_DEBUG", "0")
    assert Settings.load().server.debug is False


def test_boolean_env_yes_enables_debug(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUTTPLUG_SERVER_DEBUG", "yes")
    assert Settings.load().server.debug is True


def test_boolean_env_garbage_rejected_naming_variable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUTTPLUG_SERVER_DEBUG", "banana")
    with pytest.raises(SettingsError, match="BUTTPLUG_SERVER_DEBUG"):
        Settings.load()


def test_int_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUTTPLUG_SERVER_PORT", "3123")
    assert Settings.load().server.port == 3123


def test_int_env_garbage_rejected_naming_variable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUTTPLUG_SERVER_PORT", "3.5")
    with pytest.raises(SettingsError, match="BUTTPLUG_SERVER_PORT"):
        Settings.load()


def test_float_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUTTPLUG_DEVICE_DEFAULT_SPEED", "0.9")
    assert Settings.load().device.default_speed == 0.9


def test_env_beats_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path):
    cfg = tmp_path / "user.toml"
    cfg.write_text("[server]\nport = 4000\n", encoding="utf-8")
    monkeypatch.setenv("BUTTPLUG_SERVER_PORT", "3123")
    assert Settings.load(cfg).server.port == 3123


def test_cli_flag_beats_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUTTPLUG_SERVER_PORT", "3123")
    settings = load_settings(["--port", "4000"])
    assert settings.server.port == 4000


def test_cli_beats_env_beats_file(monkeypatch: pytest.MonkeyPatch, tmp_path):
    cfg = tmp_path / "user.toml"
    cfg.write_text('[server]\nport = 4000\nhost = "0.0.0.0"\n', encoding="utf-8")
    monkeypatch.setenv("BUTTPLUG_SERVER_PORT", "3123")

    settings = load_settings(["--config", str(cfg), "--port", "4000"])
    assert settings.server.port == 4000  # CLI wins
    assert settings.server.host == "0.0.0.0"  # file value fills what CLI left unset
