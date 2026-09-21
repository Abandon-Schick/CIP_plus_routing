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


def test_navigation_base_url_defaults_to_local_api_and_is_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_no_dotenv(monkeypatch)
    monkeypatch.delenv("NAVIGATION_BASE_URL", raising=False)
    assert get_settings().navigation_base_url == "http://localhost:8000/navigate/"

    monkeypatch.setenv("NAVIGATION_BASE_URL", "https://app.example.org/navigate/")
    assert get_settings().navigation_base_url == "https://app.example.org/navigate/"


def test_static_routes_dir_defaults_and_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_no_dotenv(monkeypatch)
    monkeypatch.delenv("STATIC_ROUTES_DIR", raising=False)
    assert get_settings().static_routes_dir == "data/routes"

    monkeypatch.setenv("STATIC_ROUTES_DIR", "/tmp/routes")
    assert get_settings().static_routes_dir == "/tmp/routes"
