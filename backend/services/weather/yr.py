"""MET Norway (Yr.no) Locationforecast 2.0 client.

Implements the WeatherClient interface for the free MET Norway weather API.
Complies with MET API Terms of Service:
  - Identifies via User-Agent header
  - Respects Expires header for caching
  - Uses If-Modified-Since conditional requests
  - Limits concurrent requests via semaphore
  - Truncates coordinates to 4 decimal places
  - Uses HTTPS only

Reference: https://api.met.no/weatherapi/locationforecast/2.0/documentation
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import httpx

from backend.models.route import Coordinate, WeatherPoint
from backend.services.weather.base import WeatherClient
from backend.services.weather.sampler import SamplePoint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Yr symbol_code → (WMO code, description, emoji)
# ---------------------------------------------------------------------------
# Symbols with _day / _night / _polartwilight suffixes are stripped before
# lookup, so only the base form is needed here.
# ---------------------------------------------------------------------------
YR_SYMBOL_MAP: dict[str, tuple[int, str, str]] = {
    # Clear / fair
    "clearsky": (0, "Clear sky", "☀️"),
    "fair": (1, "Mainly clear", "🌤️"),
    "partlycloudy": (2, "Partly cloudy", "⛅"),
    "cloudy": (3, "Overcast", "☁️"),
    # Fog
    "fog": (45, "Fog", "🌫️"),
    # Rain (steady)
    "lightrain": (61, "Slight rain", "🌦️"),
    "rain": (63, "Moderate rain", "🌧️"),
    "heavyrain": (65, "Heavy rain", "🌧️"),
    # Rain showers
    "lightrainshowers": (80, "Slight rain showers", "🌦️"),
    "rainshowers": (81, "Moderate rain showers", "🌧️"),
    "heavyrainshowers": (82, "Violent rain showers", "⛈️"),
    # Sleet (steady) — mapped to WMO freezing codes for analyzer compatibility
    "lightsleet": (56, "Light freezing drizzle", "🌧️❄️"),
    "sleet": (66, "Light freezing rain", "🧊"),
    "heavysleet": (67, "Heavy freezing rain", "🧊"),
    # Sleet showers
    "lightsleetshowers": (56, "Light sleet showers", "🌧️❄️"),
    "sleetshowers": (66, "Sleet showers", "🧊"),
    "heavysleetshowers": (67, "Heavy sleet showers", "🧊"),
    # Snow (steady)
    "lightsnow": (71, "Slight snow", "🌨️"),
    "snow": (73, "Moderate snow", "❄️"),
    "heavysnow": (75, "Heavy snow", "❄️"),
    # Snow showers
    "lightsnowshowers": (85, "Slight snow showers", "🌨️"),
    "snowshowers": (85, "Snow showers", "❄️"),
    "heavysnowshowers": (86, "Heavy snow showers", "❄️"),
    # Thunderstorm variants
    "rainandthunder": (95, "Thunderstorm with rain", "⛈️"),
    "heavyrainandthunder": (95, "Heavy thunderstorm", "⛈️"),
    "lightrainandthunder": (95, "Thunderstorm with light rain", "⛈️"),
    "snowandthunder": (95, "Thunderstorm with snow", "⛈️"),
    "heavysnowandthunder": (95, "Heavy thunderstorm with snow", "⛈️"),
    "lightsnowandthunder": (95, "Thunderstorm with light snow", "⛈️"),
    "sleetandthunder": (96, "Thunderstorm with sleet", "⛈️"),
    "heavysleetandthunder": (96, "Heavy thunderstorm with sleet", "⛈️"),
    "lightsleetandthunder": (96, "Thunderstorm with light sleet", "⛈️"),
    "rainshowersandthunder": (95, "Rain showers and thunder", "⛈️"),
    "heavyrainshowersandthunder": (95, "Heavy rain showers and thunder", "⛈️"),
    "lightrainshowersandthunder": (95, "Light rain showers and thunder", "⛈️"),
    "snowshowersandthunder": (95, "Snow showers and thunder", "⛈️"),
    "heavysnowshowersandthunder": (95, "Heavy snow showers and thunder", "⛈️"),
    "lightsnowshowersandthunder": (95, "Light snow showers and thunder", "⛈️"),
    "sleetshowersandthunder": (96, "Sleet showers and thunder", "⛈️"),
    "heavysleetshowersandthunder": (96, "Heavy sleet showers and thunder", "⛈️"),
    "lightsleetshowersandthunder": (96, "Light sleet showers and thunder", "⛈️"),
}


def _strip_symbol_suffix(symbol_code: str) -> str:
    """Remove _day / _night / _polartwilight suffix from a Yr symbol code."""
    for suffix in ("_day", "_night", "_polartwilight"):
        if symbol_code.endswith(suffix):
            return symbol_code[: -len(suffix)]
    return symbol_code


def _lookup_symbol(symbol_code: str) -> tuple[int, str, str]:
    """Return (wmo_code, description, emoji) for a Yr symbol code.

    Falls back to a generic thunderstorm entry for unknown ``*andthunder*``
    variants, then to a generic unknown entry.
    """
    base = _strip_symbol_suffix(symbol_code)

    if base in YR_SYMBOL_MAP:
        return YR_SYMBOL_MAP[base]

    # Fallback: any thunder variant we didn't list explicitly
    if "thunder" in base:
        return (95, "Thunderstorm", "⛈️")

    logger.debug("Unknown Yr symbol code: %s (base=%s)", symbol_code, base)
    return (0, symbol_code.replace("_", " ").title(), "❓")


# ---------------------------------------------------------------------------
# In-memory response cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    """Cached API response for a single coordinate pair."""

    data: dict[str, Any]  # parsed JSON response body
    expires: float  # time.monotonic() value when this entry expires
    last_modified: str = ""  # Last-Modified header for conditional requests


class YrClient(WeatherClient):
    """Client for MET Norway Locationforecast 2.0 API (free, requires identification).

    Parameters
    ----------
    contact_info:
        Contact information (email or URL) appended to the User-Agent header
        as required by the MET Norway Terms of Service.
    """

    BASE_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
    TIMEOUT = 30.0
    MAX_CONCURRENT = 10  # asyncio.Semaphore limit — keeps us well under 20 req/s

    # Class-level response cache shared across instances
    # Key: (lat rounded to 4 decimals, lon rounded to 4 decimals)
    _cache: dict[tuple[float, float], _CacheEntry] = {}

    def __init__(self, contact_info: str = "") -> None:
        self._contact_info = contact_info
        if not contact_info:
            logger.warning(
                "YrClient created without contact_info. MET Norway TOS requires "
                "identification via User-Agent. Set YR_CONTACT_INFO in your .env file."
            )
        self._user_agent = f"WeatherRouter/2.0 {contact_info}".strip()
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)

    # ------------------------------------------------------------------
    # WeatherClient interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        """Human-readable provider name."""
        return "MET Norway (Yr.no)"

    async def get_weather_for_points(
        self, sample_points: list[SamplePoint]
    ) -> list[WeatherPoint]:
        """Fetch weather forecasts for a list of sample points along a route.

        Args:
            sample_points: List of SamplePoint with lat, lng, and arrival_time.

        Returns:
            List of WeatherPoint with full weather data, one per sample point.
        """
        if not sample_points:
            return []

        logger.info(
            "Fetching Yr.no weather for %d points (provider=%s)",
            len(sample_points),
            self.name,
        )

        async with httpx.AsyncClient(
            timeout=self.TIMEOUT,
            headers={
                "User-Agent": self._user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
        ) as client:
            tasks = [self._fetch_one(client, sp) for sp in sample_points]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        weather_points: list[WeatherPoint] = []
        errors = 0
        cache_hits = 0

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Failed to fetch weather for point %d (%.4f, %.4f): %s",
                    i,
                    sample_points[i].lat,
                    sample_points[i].lng,
                    result,
                )
                weather_points.append(self._make_fallback_point(sample_points[i]))
                errors += 1
            else:
                weather_points.append(result)

        # Count how many entries we served from cache (rough heuristic)
        now = time.monotonic()
        for sp in sample_points:
            key = _truncate_key(sp.lat, sp.lng)
            entry = self._cache.get(key)
            if entry is not None and entry.expires > now:
                cache_hits += 1

        logger.info(
            "Yr.no weather complete: %d points, %d cache hits, %d errors",
            len(weather_points),
            cache_hits,
            errors,
        )
        return weather_points

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_one(
        self, client: httpx.AsyncClient, sp: SamplePoint
    ) -> WeatherPoint:
        """Fetch weather for a single sample point, using cache when possible."""
        # 1. Truncate coordinates to 4 decimal places (TOS requirement)
        key = _truncate_key(sp.lat, sp.lng)
        lat4, lon4 = key

        # 2. Check in-memory cache
        now_mono = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached.expires > now_mono:
            # Cache hit — no request needed
            return self._weather_from_response(cached.data, sp)

        # 3. Build request headers (conditional request if we have a stale entry)
        headers: dict[str, str] = {}
        if cached is not None and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

        # 4. Make the HTTP request through the semaphore
        url = f"{self.BASE_URL}?lat={lat4}&lon={lon4}"

        async with self._semaphore:
            try:
                response = await client.get(url, headers=headers)
            except httpx.TimeoutException:
                logger.warning("Yr.no request timed out for (%.4f, %.4f)", lat4, lon4)
                if cached is not None:
                    return self._weather_from_response(cached.data, sp)
                raise
            except httpx.RequestError as exc:
                logger.warning(
                    "Yr.no request error for (%.4f, %.4f): %s", lat4, lon4, exc
                )
                if cached is not None:
                    return self._weather_from_response(cached.data, sp)
                raise
            finally:
                # Small sleep to smooth out request rate (stay well under 20 req/s)
                await asyncio.sleep(0.05)

        # 5. Handle 304 Not Modified — return cached data
        if response.status_code == 304 and cached is not None:
            # Refresh the expiry from the new Expires header
            cached.expires = _parse_expires(response.headers, now_mono)
            return self._weather_from_response(cached.data, sp)

        # 6. Handle error status codes
        if response.status_code != 200:
            logger.warning(
                "Yr.no HTTP %d for (%.4f, %.4f): %s",
                response.status_code,
                lat4,
                lon4,
                response.text[:200],
            )
            if cached is not None:
                return self._weather_from_response(cached.data, sp)
            return self._make_fallback_point(sp)

        # 7. Parse response and update cache
        data = response.json()
        expires = _parse_expires(response.headers, now_mono)
        last_modified = response.headers.get("Last-Modified", "")

        self._cache[key] = _CacheEntry(
            data=data,
            expires=expires,
            last_modified=last_modified,
        )

        return self._weather_from_response(data, sp)

    def _weather_from_response(
        self, data: dict[str, Any], sp: SamplePoint
    ) -> WeatherPoint:
        """Extract a WeatherPoint from a cached/fresh Yr.no API response."""
        try:
            # Elevation from GeoJSON geometry
            geometry = data.get("geometry", {})
            coords = geometry.get("coordinates", [])
            elevation = float(coords[2]) if len(coords) >= 3 else 0.0

            # Timeseries
            properties = data.get("properties", {})
            timeseries = properties.get("timeseries", [])
            if not timeseries:
                logger.warning(
                    "Yr.no response has no timeseries for (%.4f, %.4f)",
                    sp.lat,
                    sp.lng,
                )
                return self._make_fallback_point(sp)

            timestep = self._find_closest_timestep(timeseries, sp.arrival_time)
            return self._parse_timestep(timestep, sp, elevation)

        except Exception:
            logger.exception(
                "Failed to parse Yr.no response for (%.4f, %.4f)", sp.lat, sp.lng
            )
            return self._make_fallback_point(sp)

    # ------------------------------------------------------------------
    # Timeseries helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_closest_timestep(
        timeseries: list[dict[str, Any]], target: datetime
    ) -> dict[str, Any]:
        """Return the timeseries entry whose ``time`` is closest to *target*."""
        best: dict[str, Any] = timeseries[0]
        best_diff = float("inf")

        for entry in timeseries:
            try:
                ts_str = entry["time"]
                ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                # Ensure target is timezone-aware for comparison
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                diff = abs((ts_dt - target).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best = entry
            except (KeyError, ValueError, TypeError):
                continue

        return best

    def _parse_timestep(
        self,
        timestep: dict[str, Any],
        sp: SamplePoint,
        elevation: float,
    ) -> WeatherPoint:
        """Convert a single Yr timeseries entry into a WeatherPoint."""
        data_block = timestep.get("data", {})
        instant = data_block.get("instant", {}).get("details", {})

        # --- Core instant values ---
        temp_c = float(instant.get("air_temperature", 0))
        wind_speed_ms = float(instant.get("wind_speed", 0))
        wind_dir = float(instant.get("wind_from_direction", 0))  # noqa: F841
        humidity = float(instant.get("relative_humidity", 0))  # noqa: F841

        wind_speed_kmh = round(wind_speed_ms * 3.6, 1)

        # --- Precipitation (prefer next_1_hours, fall back to next_6_hours) ---
        precip_mm = 0.0
        symbol_code = "cloudy"  # sensible default

        for period in ("next_1_hours", "next_6_hours"):
            period_data = data_block.get(period)
            if period_data is not None:
                summary = period_data.get("summary", {})
                symbol_code = summary.get("symbol_code", symbol_code)
                details = period_data.get("details", {})
                precip_mm = float(details.get("precipitation_amount", 0))
                break  # use the shortest available period

        # --- Symbol mapping ---
        wmo_code, description, emoji = _lookup_symbol(symbol_code)

        # --- Snowfall estimate ---
        base_symbol = _strip_symbol_suffix(symbol_code)
        is_snow_or_sleet = "snow" in base_symbol or "sleet" in base_symbol
        snowfall_cm = round(precip_mm * 1.0, 1) if is_snow_or_sleet else 0.0

        # --- Feels-like / wind chill ---
        feels_like_c: Optional[float] = None
        if temp_c <= 10.0 and wind_speed_kmh > 4.8:
            feels_like_c = round(self._calculate_wind_chill(temp_c, wind_speed_kmh), 1)
        else:
            feels_like_c = round(temp_c, 1)

        return WeatherPoint(
            location=Coordinate(lat=sp.lat, lng=sp.lng),
            distance_km=sp.distance_km,
            elevation_m=round(elevation, 0),
            arrival_time=sp.arrival_time.isoformat(),
            temperature_c=round(temp_c, 1),
            feels_like_c=feels_like_c,
            precipitation_mm=round(precip_mm, 1),
            snowfall_cm=snowfall_cm,
            weather_code=wmo_code,
            weather_description=description,
            weather_symbol=emoji,
            wind_speed_kmh=wind_speed_kmh,
            is_peak=sp.is_peak,
        )

    # ------------------------------------------------------------------
    # Static utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_wind_chill(temp_c: float, wind_kmh: float) -> float:
        """Standard North American wind chill index.

        Formula valid for temp ≤ 10 °C and wind > 4.8 km/h.

            WCI = 13.12 + 0.6215·T − 11.37·V^0.16 + 0.3965·T·V^0.16

        where T is air temperature in °C and V is wind speed in km/h.
        """
        v016 = wind_kmh**0.16
        return 13.12 + 0.6215 * temp_c - 11.37 * v016 + 0.3965 * temp_c * v016

    @staticmethod
    def _make_fallback_point(sp: SamplePoint) -> WeatherPoint:
        """Return a minimal WeatherPoint when real data is unavailable."""
        return WeatherPoint(
            location=Coordinate(lat=sp.lat, lng=sp.lng),
            distance_km=sp.distance_km,
            elevation_m=0,
            arrival_time=sp.arrival_time.isoformat(),
            temperature_c=0,
            feels_like_c=None,
            precipitation_mm=0,
            snowfall_cm=0,
            weather_code=-1,
            weather_description="Weather data unavailable",
            weather_symbol="❓",
            wind_speed_kmh=0,
            is_peak=sp.is_peak,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _truncate_key(lat: float, lng: float) -> tuple[float, float]:
    """Truncate coordinates to 4 decimal places and return a cache key."""
    return (round(lat, 4), round(lng, 4))


def _parse_expires(headers: httpx.Headers, now_mono: float) -> float:
    """Parse an HTTP ``Expires`` header into a ``time.monotonic()`` deadline.

    Falls back to a 60-second TTL when the header is missing or unparseable.
    """
    expires_str = headers.get("Expires")
    if not expires_str:
        return now_mono + 60.0

    try:
        expires_dt = parsedate_to_datetime(expires_str)
        # Convert wall-clock expiry to monotonic offset
        delta = (expires_dt - datetime.now(timezone.utc)).total_seconds()
        # Clamp: at least 10 s, at most 3 h
        delta = max(10.0, min(delta, 10800.0))
        return now_mono + delta
    except Exception:
        logger.debug("Failed to parse Expires header: %s", expires_str)
        return now_mono + 60.0
