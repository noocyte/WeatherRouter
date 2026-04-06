"""Sun position calculation and sunglasses advisory for driving routes.

Uses simplified NOAA solar equations to compute sun altitude and azimuth,
then evaluates glare risk from low sun angle and snow reflection along the
route to produce a sunglasses advisory.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from backend.models.route import SunglassesAdvisory, WeatherPoint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sun position (NOAA simplified solar equations)
# ---------------------------------------------------------------------------


def _julian_day(dt: datetime) -> float:
    """Return the Julian Day Number for a UTC datetime."""
    y = dt.year
    m = dt.month
    d = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0

    if m <= 2:
        y -= 1
        m += 12

    A = int(y / 100)
    B = 2 - A + int(A / 4)

    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5


def sun_position(lat: float, lng: float, dt: datetime) -> tuple[float, float]:
    """Calculate sun altitude and azimuth for a given location and UTC time.

    Uses the simplified NOAA solar equations.

    Args:
        lat: Latitude in decimal degrees (positive north).
        lng: Longitude in decimal degrees (positive east).
        dt: A datetime in UTC.

    Returns:
        A tuple of (altitude_deg, azimuth_deg) where altitude is degrees
        above the horizon (-90 to 90) and azimuth is degrees clockwise
        from north (0 to 360).
    """
    jd = _julian_day(dt)

    # Julian century from J2000.0
    jc = (jd - 2451545.0) / 36525.0

    # Geometric mean longitude of the sun (degrees)
    L0 = (280.46646 + jc * (36000.76983 + 0.0003032 * jc)) % 360.0

    # Geometric mean anomaly of the sun (degrees)
    M = (357.52911 + jc * (35999.05029 - 0.0001537 * jc)) % 360.0
    M_rad = math.radians(M)

    # Eccentricity of Earth's orbit
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)

    # Sun equation of center (degrees)
    C = (
        math.sin(M_rad) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + math.sin(2.0 * M_rad) * (0.019993 - 0.000101 * jc)
        + math.sin(3.0 * M_rad) * 0.000289
    )

    # Sun true longitude and true anomaly (degrees)
    sun_lon = L0 + C
    sun_anomaly = M + C

    # Sun radius vector (AU) — not strictly needed but part of the standard calc
    sun_anomaly_rad = math.radians(sun_anomaly)
    _radius = (1.000001018 * (1.0 - e * e)) / (1.0 + e * math.cos(sun_anomaly_rad))

    # Apparent longitude of the sun (degrees)
    omega = 125.04 - 1934.136 * jc
    omega_rad = math.radians(omega)
    apparent_lon = sun_lon - 0.00569 - 0.00478 * math.sin(omega_rad)

    # Mean obliquity of the ecliptic (degrees)
    obliquity_mean = (
        23.0
        + (26.0 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60.0)
        / 60.0
    )

    # Corrected obliquity (degrees)
    obliquity = obliquity_mean + 0.00256 * math.cos(omega_rad)
    obliquity_rad = math.radians(obliquity)

    # Solar declination (radians)
    apparent_lon_rad = math.radians(apparent_lon)
    sin_dec = math.sin(obliquity_rad) * math.sin(apparent_lon_rad)
    declination = math.asin(sin_dec)

    # Equation of time (minutes)
    y_eot = math.tan(obliquity_rad / 2.0) ** 2
    L0_rad = math.radians(L0)
    eqtime = 4.0 * math.degrees(
        y_eot * math.sin(2.0 * L0_rad)
        - 2.0 * e * math.sin(M_rad)
        + 4.0 * e * y_eot * math.sin(M_rad) * math.cos(2.0 * L0_rad)
        - 0.5 * y_eot * y_eot * math.sin(4.0 * L0_rad)
        - 1.25 * e * e * math.sin(2.0 * M_rad)
    )

    # True solar time (minutes)
    time_offset = eqtime + 4.0 * lng  # minutes
    day_minutes = dt.hour * 60.0 + dt.minute + dt.second / 60.0
    true_solar_time = (day_minutes + time_offset) % 1440.0

    # Hour angle (degrees)
    hour_angle = true_solar_time / 4.0 - 180.0

    # Solar altitude (elevation angle)
    lat_rad = math.radians(lat)
    ha_rad = math.radians(hour_angle)

    sin_alt = math.sin(lat_rad) * math.sin(declination) + math.cos(lat_rad) * math.cos(
        declination
    ) * math.cos(ha_rad)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude = math.degrees(math.asin(sin_alt))

    # Solar azimuth (from north, clockwise)
    cos_alt = math.cos(math.radians(altitude))
    if cos_alt == 0.0:
        azimuth = 0.0
    else:
        cos_az = (math.sin(declination) - math.sin(lat_rad) * sin_alt) / (
            math.cos(lat_rad) * cos_alt
        )
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth = math.degrees(math.acos(cos_az))

        if hour_angle > 0.0:
            azimuth = 360.0 - azimuth

    return altitude, azimuth


# ---------------------------------------------------------------------------
# Route bearing helpers
# ---------------------------------------------------------------------------


def _haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in metres between two points."""
    R = 6_371_000.0  # Earth radius in metres
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2.0) ** 2
    )
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _forward_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the initial bearing in degrees (0-360) from point 1 to point 2."""
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlng_r = math.radians(lng2 - lng1)

    x = math.sin(dlng_r) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(
        lat2_r
    ) * math.cos(dlng_r)
    bearing = math.degrees(math.atan2(x, y))
    return bearing % 360.0


def bearing_at_point(
    route_geometry: dict[str, Any],
    weather_point: WeatherPoint,
) -> float:
    """Find the driving bearing at the route segment closest to a weather point.

    Args:
        route_geometry: GeoJSON LineString dict with ``coordinates`` in
            ``[lng, lat]`` order.
        weather_point: A :class:`WeatherPoint` whose ``.location`` is used
            to find the nearest segment.

    Returns:
        Forward bearing in degrees (0-360) of the closest route segment.
    """
    coords = route_geometry.get("coordinates", [])
    if len(coords) < 2:
        return 0.0

    pt_lat = weather_point.location.lat
    pt_lng = weather_point.location.lng

    best_dist = float("inf")
    best_idx = 0

    for i in range(len(coords) - 1):
        # GeoJSON coordinates are [lng, lat]
        mid_lng = (coords[i][0] + coords[i + 1][0]) / 2.0
        mid_lat = (coords[i][1] + coords[i + 1][1]) / 2.0
        dist = _haversine_distance(pt_lat, pt_lng, mid_lat, mid_lng)
        if dist < best_dist:
            best_dist = dist
            best_idx = i

    seg_start = coords[best_idx]
    seg_end = coords[best_idx + 1]

    return _forward_bearing(seg_start[1], seg_start[0], seg_end[1], seg_end[0])


# ---------------------------------------------------------------------------
# Angular difference (handles wraparound)
# ---------------------------------------------------------------------------


def _angular_difference(a: float, b: float) -> float:
    """Return the smallest angular difference in degrees between two bearings.

    Correctly handles wraparound (e.g. 350° vs 10° → 20°).
    """
    diff = abs(a - b) % 360.0
    if diff > 180.0:
        diff = 360.0 - diff
    return diff


# ---------------------------------------------------------------------------
# Sunglasses advisory builder
# ---------------------------------------------------------------------------


def build_sunglasses_advisory(
    weather_points: list[WeatherPoint],
    route_geometry: dict[str, Any],
) -> SunglassesAdvisory:
    """Produce a sunglasses / glare advisory for a driving route.

    Evaluates each weather point for three glare conditions:

    * **Low sun glare** — sun altitude 2°–25° and driving roughly into the
      sun (azimuth difference < 40°).  This is the most dangerous.
    * **Snow glare** — clear/partly-cloudy sky with ground snow cover or
      fresh snowfall at cold temperatures, sun altitude > 5°.
    * **Bright sun** — clear sky with sun altitude > 15°.  Mild on its own
      but noted if other conditions also apply.

    Args:
        weather_points: Sampled weather points along the route.
        route_geometry: GeoJSON LineString dict for the route.

    Returns:
        A :class:`SunglassesAdvisory` with ``needed``, ``title``,
        ``message``, and ``icon`` populated.
    """
    if not weather_points:
        return SunglassesAdvisory(
            needed=False,
            title="No glare expected",
            message="No weather data available to assess glare.",
            icon="☀️",
        )

    low_sun_hits: list[dict[str, Any]] = []
    snow_glare_hits: list[dict[str, Any]] = []
    bright_sun_hits: list[dict[str, Any]] = []

    for wp in weather_points:
        # Parse arrival time
        try:
            arrival_str = wp.arrival_time.replace("Z", "+00:00")
            dt = datetime.fromisoformat(arrival_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            logger.warning(
                "Could not parse arrival_time '%s', skipping point", wp.arrival_time
            )
            continue

        altitude, azimuth = sun_position(wp.location.lat, wp.location.lng, dt)

        # Skip if sun is below the horizon
        if altitude <= 0.0:
            continue

        # Skip if overcast, fog, or precipitation (weather_code >= 3)
        if wp.weather_code >= 3:
            continue

        bearing = bearing_at_point(route_geometry, wp)
        az_diff = _angular_difference(azimuth, bearing)

        point_info: dict[str, Any] = {
            "wp": wp,
            "dt": dt,
            "altitude": altitude,
            "azimuth": azimuth,
            "bearing": bearing,
            "az_diff": az_diff,
        }

        # --- Low sun glare ---
        if 2.0 <= altitude <= 25.0 and az_diff < 40.0:
            low_sun_hits.append(point_info)

        # --- Snow glare ---
        has_snow_cover = wp.snow_depth_m > 0.01
        fresh_cold_snow = wp.snowfall_cm > 0.0 and wp.temperature_c <= 2.0
        if (has_snow_cover or fresh_cold_snow) and altitude > 5.0:
            snow_glare_hits.append(point_info)

        # --- Bright sun ---
        if wp.weather_code <= 1 and altitude > 15.0:
            bright_sun_hits.append(point_info)

    # Determine if sunglasses are needed
    needed = bool(low_sun_hits or snow_glare_hits)

    if not needed:
        logger.info("Sunglasses advisory: no glare conditions detected")
        return SunglassesAdvisory(
            needed=False,
            title="No glare expected",
            message="No significant glare expected along the route.",
            icon="☀️",
        )

    # Build descriptive message listing reasons
    reasons: list[str] = []

    if low_sun_hits:
        # Pick the worst (lowest altitude = most blinding)
        worst = min(low_sun_hits, key=lambda h: h["altitude"])
        dt_local = worst["dt"]
        time_str = dt_local.strftime("%H:%M")
        km = worst["wp"].distance_km

        # Approximate compass direction from bearing
        direction = _compass_label(worst["bearing"])
        reasons.append(
            f"Low sun expected around {time_str} UTC, "
            f"heading {direction} near km {km:.0f}"
        )

    if snow_glare_hits:
        if low_sun_hits:
            reasons.append("snow glare expected along parts of the route")
        else:
            reasons.append("Bright sun reflecting off snow cover along the route")

    if bright_sun_hits and not low_sun_hits and not snow_glare_hits:
        # This branch shouldn't trigger because needed would be False,
        # but kept for completeness.
        reasons.append("Bright sunshine expected along the route")

    message = ". ".join(reasons) + "."
    # Capitalise first letter in case the first reason starts lowercase
    message = message[0].upper() + message[1:]

    logger.info(
        "Sunglasses advisory: needed=True, low_sun=%d, snow_glare=%d, bright=%d",
        len(low_sun_hits),
        len(snow_glare_hits),
        len(bright_sun_hits),
    )

    return SunglassesAdvisory(
        needed=True,
        title="Sunglasses recommended",
        message=message,
        icon="🕶️",
    )


def _compass_label(bearing: float) -> str:
    """Convert a bearing in degrees to a human-readable compass direction."""
    directions = [
        "north",
        "north-northeast",
        "northeast",
        "east-northeast",
        "east",
        "east-southeast",
        "southeast",
        "south-southeast",
        "south",
        "south-southwest",
        "southwest",
        "west-southwest",
        "west",
        "west-northwest",
        "northwest",
        "north-northwest",
    ]
    idx = round(bearing / 22.5) % 16
    return directions[idx]
