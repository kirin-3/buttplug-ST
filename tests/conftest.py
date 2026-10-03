"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def clean_buttplug_env(monkeypatch: pytest.MonkeyPatch):
    """Strip BUTTPLUG_* variables so the outer shell cannot leak into tests."""
    for name in list(os.environ):
        if name.startswith("BUTTPLUG_"):
            monkeypatch.delenv(name)
