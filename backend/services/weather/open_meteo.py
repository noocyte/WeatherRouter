"""Open-Meteo API client for weather forecasts."""

import logging
from datetime import datetime
from typing import Any

import httpx

from backend.models.route import Coordinate, WeatherPoint
from backend.services.weather.sampler import SamplePoint

logger = logging.getLogger(__name__)

# WMO Weather Code mapping to descriptions and symbols
WMO_CODES = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    56: ("Light freezing drizzle", "🌧️❄️"),
    57: ("Dense freezing drizzle", "🌧️❄️"),
    61: ("Slight rain", "🌦️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "🧊"),
    67: ("Heavy freezing rain", "🧊"),
    71: ("Slight snow", "🌨️"),
    73: ("Moderate snow", "❄️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"),
    80: ("Slight rain showers", "🌦️"),
    81: ("Moderate rain showers", "🌧️"),
    82: ("Violent rain showers", "⛈️"),
    85: ("Slight snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm with slight hail", "⛈️"),
    99: ("Thunderstorm with heavy hail", "⛈️"),
}


class OpenMeteoClient:
    """Client for the Open-Meteo weather forecast API (free, no API key)."""

    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    HEADERS = {"User-Agent": "WeatherRouter/1.0"}
    TIMEOUT = 30.0

    async def get_weather_for_points(
        self, sample_points: list[SamplePoint]
    ) -> list[WeatherPoint]:
        """Fetch weather forecasts for all sample points in a batched request.

        Open-Meteo supports multiple latitude/longitude values in a single request,
        returning an array of results. We then pick the hour closest to each point's
        estimated arrival time.

        Args:
            sample_points: List of SamplePoint with lat, lng, and arrival_time

        Returns:
            List of WeatherPoint with full weather data
        """
        if not sample_points:
            return []

        # Collect unique dates needed for the forecast
        dates: set[str] = set()
        for sp in sample_points:
            dates.add(sp.arrival_time.strftime("%Y-%m-%d"))

        start_date = min(dates)
        end_date = max(dates)

        # Build the request - Open-Meteo supports comma-separated lat/lng arrays
        lats = ",".join(str(round(sp.lat, 4)) for sp in sample_points)
        lngs = ",".join(str(round(sp.lng, 4)) for sp in sample_points)

        params = {
            "latitude": lats,
            "longitude": lngs,
            "hourly": "temperature_2m,apparent_temperature,precipitation,snowfall,weathercode,windspeed_10m",
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "auto",
        }

        logger.info(
            "Fetching Open-Meteo weather for %d points (%s to %s)",
            len(sample_points),
            start_date,
            end_date,
        )

        async with httpx.AsyncClient(
            timeout=self.TIMEOUT, headers=self.HEADERS
        ) as client:
            try:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
            except httpx.TimeoutException:
                logger.error("Open-Meteo request timed out")
                return self._fallback_weather_points(sample_points)
            except httpx.RequestError as exc:
                logger.error("Open-Meteo request failed: %s", exc)
                return self._fallback_weather_points(sample_points)
            except httpx.HTTPStatusError as exc:
                logger.error("Open-Meteo HTTP error %d", exc.response.status_code)
                return self._fallback_weather_points(sample_points)

        data = response.json()
        return self._parse_response(data, sample_points)

    def _parse_response(
        self, data: Any, sample_points: list[SamplePoint]
    ) -> list[WeatherPoint]:
        """Parse the Open-Meteo API response into WeatherPoint objects."""
        weather_points: list[WeatherPoint] = []

        # Open-Meteo returns different structures for single vs multiple locations:
        # Single: data is a dict with "hourly", "elevation", etc.
        # Multiple: data is a list of dicts, one per location
        if isinstance(data, list):
            # Multiple locations
            locations = data
        elif isinstance(data, dict) and "hourly" in data:
            # Single location - wrap in list
            locations = [data]
        else:
            logger.warning(
                "Unexpected Open-Meteo response format: %s", type(data).__name__
            )
            return self._fallback_weather_points(sample_points)

        for i, sp in enumerate(sample_points):
            if i >= len(locations):
                # Fallback if we got fewer locations than expected
                logger.warning(
                    "Open-Meteo returned %d locations but expected %d",
                    len(locations),
                    len(sample_points),
                )
                weather_points.append(self._make_fallback_point(sp))
                continue

            loc_data = locations[i]
            elevation = loc_data.get("elevation", 0) or 0
            hourly = loc_data.get("hourly", {})

            # Find the hour closest to the arrival time
            times = hourly.get("time", [])
            if not times:
                logger.warning(
                    "No hourly time data for point %d (%.4f, %.4f)", i, sp.lat, sp.lng
                )
                weather_points.append(self._make_fallback_point(sp))
                continue

            hour_idx = self._find_closest_hour(times, sp.arrival_time)

            # Extract weather values for this hour
            temp = self._get_hourly_val(hourly, "temperature_2m", hour_idx)
            feels = self._get_hourly_val(hourly, "apparent_temperature", hour_idx)
            precip = self._get_hourly_val(hourly, "precipitation", hour_idx)
            snow = self._get_hourly_val(hourly, "snowfall", hour_idx)
            code = int(self._get_hourly_val(hourly, "weathercode", hour_idx))
            wind = self._get_hourly_val(hourly, "windspeed_10m", hour_idx)

            description, symbol = WMO_CODES.get(code, ("Unknown", "❓"))

            weather_points.append(
                WeatherPoint(
                    location=Coordinate(lat=sp.lat, lng=sp.lng),
                    distance_km=sp.distance_km,
                    elevation_m=round(elevation, 0),
                    arrival_time=sp.arrival_time.isoformat(),
                    temperature_c=round(temp, 1) if temp is not None else 0,
                    feels_like_c=round(feels, 1) if feels is not None else None,
                    precipitation_mm=round(precip, 1) if precip is not None else 0,
                    snowfall_cm=round(snow, 1) if snow is not None else 0,
                    weather_code=code,
                    weather_description=description,
                    weather_symbol=symbol,
                    wind_speed_kmh=round(wind, 1) if wind is not None else 0,
                )
            )

        logger.info("Parsed weather data for %d points", len(weather_points))
        return weather_points

    def _find_closest_hour(self, times: list[str], target: datetime) -> int:
        """Find the index of the hourly time closest to the target datetime."""
        best_idx = 0
        best_diff = float("inf")
        for idx, t in enumerate(times):
            try:
                t_dt = datetime.fromisoformat(t)
                # Compare without timezone info since Open-Meteo returns local times
                diff = abs((t_dt - target.replace(tzinfo=None)).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_idx = idx
            except (ValueError, TypeError):
                continue

        return best_idx

    @staticmethod
    def _get_hourly_val(hourly: dict, key: str, idx: int) -> float:
        """Safely get a value from an hourly data array."""
        values = hourly.get(key, [])
        if idx < len(values) and values[idx] is not None:
            return float(values[idx])
        return 0.0

    def _fallback_weather_points(
        self, sample_points: list[SamplePoint]
    ) -> list[WeatherPoint]:
        """Return minimal weather points when the API fails."""
        logger.warning(
            "Using fallback weather data for %d points (API unavailable)",
            len(sample_points),
        )
        return [self._make_fallback_point(sp) for sp in sample_points]

    @staticmethod
    def _make_fallback_point(sp: SamplePoint) -> WeatherPoint:
        """Create a fallback WeatherPoint with no data."""
        return WeatherPoint(
            location=Coordinate(lat=sp.lat, lng=sp.lng),
            distance_km=sp.distance_km,
            elevation_m=0,
            arrival_time=sp.arrival_time.isoformat(),
            temperature_c=0,
            precipitation_mm=0,
            snowfall_cm=0,
            weather_code=-1,
            weather_description="Weather data unavailable",
            weather_symbol="❓",
            wind_speed_kmh=0,
        )
