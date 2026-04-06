"""Weather analysis and tire recommendation engine."""

import logging

from backend.models.route import RouteWeather, TireRecommendation, WeatherPoint

logger = logging.getLogger(__name__)


def build_tire_recommendation(weather_points: list[WeatherPoint]) -> TireRecommendation:
    """Analyze weather points and produce a tire recommendation.

    Thresholds:
    - 7°C: Below this, summer tire rubber hardens and loses grip
    - 3°C: Significant grip loss, road frost likely
    - 0°C: Freezing — any moisture becomes ice

    Verdicts:
    - summer_ok: All temps > 7°C, no snow/ice
    - winter_advisory: Any temp 3-7°C, or precipitation below 5°C
    - winter_recommended: Any temp < 3°C, or snow forecast
    - winter_required: Temp < 0°C with precipitation, or heavy snow, or freezing rain
    """
    if not weather_points:
        return TireRecommendation(
            verdict="summer_ok",
            title="No weather data",
            message="Unable to determine conditions. Drive carefully.",
            icon="❓",
        )

    min_temp = min(wp.temperature_c for wp in weather_points)
    max_temp = max(wp.temperature_c for wp in weather_points)
    total_snow = sum(wp.snowfall_cm for wp in weather_points)
    has_snow = any(wp.snowfall_cm > 0 for wp in weather_points)
    has_freezing_rain = any(
        wp.weather_code in (66, 67, 56, 57) for wp in weather_points
    )
    has_precipitation = any(wp.precipitation_mm > 0 for wp in weather_points)
    cold_and_wet = any(
        wp.temperature_c < 0 and wp.precipitation_mm > 0 for wp in weather_points
    )

    # Determine verdict
    if has_freezing_rain or cold_and_wet or total_snow > 2:
        verdict = "winter_required"
        title = "Winter Tires Required"
        icon = "🔴"

        reasons = []
        if has_freezing_rain:
            reasons.append("freezing rain expected")
        if total_snow > 2:
            reasons.append(f"{total_snow:.1f}cm of snow forecast")
        if cold_and_wet and not has_freezing_rain:
            reasons.append("sub-zero temperatures with precipitation")

        coldest = min(weather_points, key=lambda wp: wp.temperature_c)
        reasons.append(
            f"lowest temperature {min_temp:.0f}°C at {coldest.distance_km:.0f}km "
            f"(elevation {coldest.elevation_m:.0f}m)"
        )

        message = (
            f"Winter tires are essential for this route. "
            f"Conditions include: {'; '.join(reasons)}."
        )

    elif has_snow or min_temp < 3:
        verdict = "winter_recommended"
        title = "Winter Tires Recommended"
        icon = "🟠"

        reasons = []
        if has_snow:
            reasons.append("snowfall forecast along the route")
        if min_temp < 3:
            coldest = min(weather_points, key=lambda wp: wp.temperature_c)
            reasons.append(
                f"temperatures as low as {min_temp:.0f}°C near {coldest.distance_km:.0f}km "
                f"(elevation {coldest.elevation_m:.0f}m)"
            )

        message = (
            f"Winter tires are strongly recommended. "
            f"{'; '.join(r.capitalize() for r in reasons)}. "
            f"Road conditions may be slippery."
        )

    elif min_temp < 7 or (has_precipitation and min_temp < 5):
        verdict = "winter_advisory"
        title = "Winter Tires Advisory"
        icon = "⚠️"

        message = (
            f"Temperatures along the route drop to {min_temp:.0f}°C. "
            f"Summer tires lose grip below 7°C. Consider winter tires for better safety, "
            f"especially if conditions change."
        )

    else:
        verdict = "summer_ok"
        title = "Summer Tires OK"
        icon = "✅"

        message = (
            f"Conditions are suitable for summer tires. "
            f"Temperatures range from {min_temp:.0f}°C to {max_temp:.0f}°C with "
            f"{'some rain' if has_precipitation else 'no significant precipitation'}."
        )

    logger.info(
        "Tire recommendation: %s (min_temp=%.1f°C, snow=%.1fcm, freezing_rain=%s)",
        verdict,
        min_temp,
        total_snow,
        has_freezing_rain,
    )

    return TireRecommendation(verdict=verdict, title=title, message=message, icon=icon)


def analyze_weather(
    weather_points: list[WeatherPoint],
    departure_time_str: str,
    tire_recommendation: TireRecommendation,
) -> RouteWeather:
    """Build the complete RouteWeather summary.

    Args:
        weather_points: List of WeatherPoint with full weather data.
        departure_time_str: ISO 8601 departure time string.
        tire_recommendation: Pre-computed tire recommendation.

    Returns:
        RouteWeather instance with all summary fields populated.
    """
    if not weather_points:
        logger.warning("No weather points available for analysis")
        return RouteWeather(
            departure_time=departure_time_str,
            weather_points=[],
            tire_recommendation=tire_recommendation,
        )

    temps = [wp.temperature_c for wp in weather_points]

    route_weather = RouteWeather(
        departure_time=departure_time_str,
        weather_points=weather_points,
        tire_recommendation=tire_recommendation,
        min_temperature_c=round(min(temps), 1),
        max_temperature_c=round(max(temps), 1),
        has_snow=any(wp.snowfall_cm > 0 for wp in weather_points),
        has_rain=any(
            wp.precipitation_mm > 0 and wp.snowfall_cm == 0 for wp in weather_points
        ),
        has_freezing_conditions=any(wp.temperature_c <= 0 for wp in weather_points),
    )

    logger.info(
        "Weather analysis complete: %.1f°C to %.1f°C, snow=%s, rain=%s, freezing=%s",
        route_weather.min_temperature_c,
        route_weather.max_temperature_c,
        route_weather.has_snow,
        route_weather.has_rain,
        route_weather.has_freezing_conditions,
    )

    return route_weather
