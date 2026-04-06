"""Weather analysis service for routes."""

import logging

from backend.config import settings
from backend.services.weather.analyzer import analyze_weather, build_tire_recommendation
from backend.services.weather.base import WeatherClient
from backend.services.weather.sampler import sample_route
from backend.services.weather.sun import build_sunglasses_advisory

logger = logging.getLogger(__name__)


def get_weather_client() -> WeatherClient:
    """Create a weather client based on the configured provider.

    Returns:
        A WeatherClient instance (OpenMeteoClient or YrClient).

    Raises:
        ValueError: If the configured provider is unknown.
    """
    provider = settings.WEATHER_PROVIDER.lower().strip()

    if provider == "open_meteo":
        from backend.services.weather.open_meteo import OpenMeteoClient

        return OpenMeteoClient()

    elif provider == "yr":
        from backend.services.weather.yr import YrClient

        return YrClient(contact_info=settings.YR_CONTACT_INFO or "")

    else:
        raise ValueError(
            f"Unknown weather provider: '{provider}'. "
            f"Supported providers: 'open_meteo', 'yr'."
        )


async def get_route_weather(
    route_geometry, distance_km, duration_minutes, departure_time_str, warnings=None
):
    """Get complete weather analysis for a route.

    Args:
        route_geometry: GeoJSON LineString dict
        distance_km: Total route distance
        duration_minutes: Total route duration
        departure_time_str: ISO 8601 departure time string
        warnings: Optional list of RouteWarning (for mountain pass peak sampling)

    Returns:
        RouteWeather instance
    """
    # 1. Sample points along the route
    sample_points = sample_route(
        route_geometry, distance_km, duration_minutes, departure_time_str, warnings
    )

    # 2. Fetch weather using the configured provider
    client = get_weather_client()
    logger.info("Using weather provider: %s", client.name)
    weather_points = await client.get_weather_for_points(sample_points)

    # 3. Analyze and produce tire recommendation
    recommendation = build_tire_recommendation(weather_points)
    weather_summary = analyze_weather(
        weather_points, departure_time_str, recommendation
    )

    # 4. Sunglasses / glare advisory
    weather_summary.sunglasses_advisory = build_sunglasses_advisory(
        weather_points, route_geometry
    )

    weather_summary.weather_provider = client.name

    return weather_summary
