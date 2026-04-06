"""Application configuration loaded from environment variables / .env file."""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """WeatherRouter application settings.

    Values are loaded from environment variables or a `.env` file located
    in the project root.  Every field has a sensible default so the app can
    start without any configuration for local development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    ROUTING_PROVIDER: str = "osrm"
    """Which routing provider to use by default ("osrm" or "google")."""

    GOOGLE_MAPS_API_KEY: Optional[str] = None
    """Google Maps Directions API key (required only for the google provider)."""

    OSRM_BASE_URL: str = "https://router.project-osrm.org"
    """Base URL for the OSRM routing backend."""

    NOMINATIM_BASE_URL: str = "https://nominatim.openstreetmap.org"
    """Base URL for the Nominatim geocoding service."""

    OPEN_METEO_BASE_URL: str = "https://api.open-meteo.com"
    """Base URL for the Open-Meteo weather API."""

    HOST: str = "0.0.0.0"
    """Host address the server binds to."""

    PORT: int = 8000
    """Port the server listens on."""


settings = Settings()
