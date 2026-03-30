from __future__ import annotations

import pytest

from gis_route_app.config import Settings, get_settings


def _patch_no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gis_route_app.config.load_dotenv", lambda *_a, **_k: None)


def test_proximity_buffer_m_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_dotenv(monkeypatch)
    monkeypatch.delenv("PROXIMITY_BUFFER_M", raising=False)
    assert get_settings().proximity_buffer_m == 50.0


def test_proximity_buffer_m_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_dotenv(monkeypatch)
    monkeypatch.setenv("PROXIMITY_BUFFER_M", "40.5")
    assert get_settings().proximity_buffer_m == 40.5


def test_proximity_buffer_m_negative_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_dotenv(monkeypatch)
    monkeypatch.setenv("PROXIMITY_BUFFER_M", "-10")
    assert get_settings().proximity_buffer_m == 0.0


def test_settings_dataclass_includes_proximity_buffer() -> None:
    s = Settings()
    assert s.proximity_buffer_m == 50.0
