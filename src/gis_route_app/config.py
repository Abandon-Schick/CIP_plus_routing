"""Application configuration handling."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    routing_provider: str = "mock"
    openrouteservice_api_key: str | None = None
    openrouteservice_base_url: str = "https://api.openrouteservice.org"
    request_timeout_seconds: int = 15


def get_settings() -> Settings:
    """Load settings from environment variables with sensible defaults."""
    load_dotenv()
    return Settings(
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        routing_provider=os.getenv("ROUTING_PROVIDER", "mock").strip().lower(),
        openrouteservice_api_key=os.getenv("OPENROUTESERVICE_API_KEY") or None,
        openrouteservice_base_url=os.getenv(
            "OPENROUTESERVICE_BASE_URL", "https://api.openrouteservice.org"
        ).rstrip("/"),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "15")),
    )
