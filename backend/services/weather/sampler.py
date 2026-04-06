"""Route sampling - selects geographic points along a route for weather queries."""

import math
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SamplePoint:
    """A sampled point along the route for weather querying."""

    lat: float
    lng: float
    distance_km: float  # from route start
    arrival_time: datetime  # estimated arrival time
    is_peak: bool = False  # whether this is a mountain pass peak


def haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def sample_route(route_geometry, distance_km, duration_minutes, departure_time_str, warnings=None):
    """Sample points along a route at regular intervals.

    Args:
        route_geometry: GeoJSON LineString dict with coordinates in [lng, lat] order
        distance_km: Total route distance in km
        duration_minutes: Total estimated duration in minutes
        departure_time_str: ISO 8601 departure time
        warnings: Optional list of RouteWarning objects (for mountain pass peak points)

    Returns:
        List of SamplePoint objects sorted by distance
    """
    coords = route_geometry.get("coordinates", [])
    if not coords or distance_km <= 0:
        return []

    # Parse departure time
    try:
        departure = datetime.fromisoformat(departure_time_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        departure = datetime.now(timezone.utc)

    # Determine number of samples (~15-20 points, min 25km apart)
    num_samples = max(5, min(20, int(distance_km / 30)))
    interval_km = distance_km / num_samples

    # Build a cumulative distance table for the route coordinates
    # coords are [lng, lat] in GeoJSON order
    cum_dist = [0.0]  # cumulative distance at each coordinate index
    for i in range(1, len(coords)):
        d = haversine_km(coords[i - 1][1], coords[i - 1][0], coords[i][1], coords[i][0])
        cum_dist.append(cum_dist[-1] + d)

    total_measured = cum_dist[-1] if cum_dist[-1] > 0 else distance_km

    # Sample at regular intervals
    samples = []
    targets = [i * interval_km for i in range(num_samples + 1)]
    # Ensure start and end are included
    if targets[0] != 0:
        targets.insert(0, 0)
    if abs(targets[-1] - distance_km) > 1:
        targets.append(distance_km)

    for target_dist in targets:
        # Scale target_dist to our measured total (in case of slight differences)
        scaled_dist = target_dist * (total_measured / distance_km) if distance_km > 0 else 0

        # Find the route segment where this distance falls
        lat, lng = _interpolate_along_route(coords, cum_dist, scaled_dist)

        # Estimate arrival time (linear interpolation based on distance fraction)
        fraction = min(1.0, target_dist / distance_km) if distance_km > 0 else 0
        arrival = departure + timedelta(minutes=duration_minutes * fraction)

        samples.append(
            SamplePoint(
                lat=lat,
                lng=lng,
                distance_km=round(target_dist, 1),
                arrival_time=arrival,
            )
        )

    # Add mountain pass peak points (midpoint of pass geometry) if available
    if warnings:
        for w in warnings:
            if w.type == "mountain_pass" and w.geometry:
                peak_point = _get_peak_from_warning(
                    w, coords, cum_dist, distance_km, duration_minutes, departure
                )
                if peak_point and not _has_nearby_sample(samples, peak_point, min_gap_km=10):
                    samples.append(peak_point)

    # Sort by distance
    samples.sort(key=lambda s: s.distance_km)

    logger.info("Sampled %d weather points along %.0fkm route", len(samples), distance_km)
    return samples


def _interpolate_along_route(coords, cum_dist, target_dist):
    """Find the (lat, lng) at a given cumulative distance along the route."""
    if target_dist <= 0:
        return coords[0][1], coords[0][0]
    if target_dist >= cum_dist[-1]:
        return coords[-1][1], coords[-1][0]

    # Binary search for the segment
    lo, hi = 0, len(cum_dist) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum_dist[mid] <= target_dist:
            lo = mid
        else:
            hi = mid

    # Interpolate within the segment [lo, hi]
    seg_len = cum_dist[hi] - cum_dist[lo]
    if seg_len <= 0:
        return coords[lo][1], coords[lo][0]

    t = (target_dist - cum_dist[lo]) / seg_len
    lng = coords[lo][0] + t * (coords[hi][0] - coords[lo][0])
    lat = coords[lo][1] + t * (coords[hi][1] - coords[lo][1])
    return lat, lng


def _get_peak_from_warning(warning, coords, cum_dist, distance_km, duration_minutes, departure):
    """Extract a sample point from a mountain pass warning geometry (midpoint of the pass)."""
    try:
        geom = warning.geometry
        if not geom:
            return None

        # Get coordinates from the warning geometry
        if geom.get("type") == "MultiLineString":
            all_coords = [pt for ls in geom.get("coordinates", []) for pt in ls]
        elif geom.get("type") == "LineString":
            all_coords = geom.get("coordinates", [])
        else:
            return None

        if not all_coords:
            return None

        # Use the midpoint of the pass geometry
        mid_idx = len(all_coords) // 2
        peak_lng, peak_lat = all_coords[mid_idx][0], all_coords[mid_idx][1]

        # Find the closest point on the route and estimate arrival time
        min_dist_sq = float("inf")
        closest_idx = 0
        for i, c in enumerate(coords):
            dsq = (c[0] - peak_lng) ** 2 + (c[1] - peak_lat) ** 2
            if dsq < min_dist_sq:
                min_dist_sq = dsq
                closest_idx = i

        peak_km = cum_dist[closest_idx] * (distance_km / cum_dist[-1]) if cum_dist[-1] > 0 else 0
        fraction = min(1.0, peak_km / distance_km) if distance_km > 0 else 0
        arrival = departure + timedelta(minutes=duration_minutes * fraction)

        return SamplePoint(
            lat=peak_lat,
            lng=peak_lng,
            distance_km=round(peak_km, 1),
            arrival_time=arrival,
            is_peak=True,
        )
    except Exception:
        logger.exception("Failed to extract peak point from mountain pass warning")
        return None


def _has_nearby_sample(samples, point, min_gap_km=10):
    """Check if there is already a sample point within min_gap_km of the given point."""
    for s in samples:
        if abs(s.distance_km - point.distance_km) < min_gap_km:
            return True
    return False
