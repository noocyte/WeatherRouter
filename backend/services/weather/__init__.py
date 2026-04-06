"""Weather analysis service for routes."""

from backend.services.weather.analyzer import analyze_weather, build_tire_recommendation
from backend.services.weather.open_meteo import OpenMeteoClient
from backend.services.weather.sampler import sample_route


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

    # 2. Fetch weather for all sample points from Open-Meteo
    client = OpenMeteoClient()
    weather_points = await client.get_weather_for_points(sample_points)

    # 3. Analyze and produce tire recommendation
    recommendation = build_tire_recommendation(weather_points)
    weather_summary = analyze_weather(
        weather_points, departure_time_str, recommendation
    )

    return weather_summary
