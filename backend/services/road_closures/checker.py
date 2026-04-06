"""Route closure checker for mountain passes and seasonal road closures.

Cross-references route geometries against known mountain pass / Kolonnestrekning
data from NVDB to produce warnings for the user.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from backend.models.route import RouteWarning
from backend.services.road_closures.nvdb import MountainPass, NVDBClient

logger = logging.getLogger(__name__)


def _bounding_box(
    coords: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Return (min_lng, min_lat, max_lng, max_lat) for a list of (lng, lat) points."""
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lngs), min(lats), max(lngs), max(lats))


def _boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    """Check whether two bounding boxes overlap, with an optional margin."""
    return not (
        a[2] + margin < b[0] - margin
        or b[2] + margin < a[0] - margin
        or a[3] + margin < b[1] - margin
        or b[3] + margin < a[1] - margin
    )


def _build_grid_cells(
    coords: list[tuple[float, float]], cell_size: float
) -> set[tuple[int, int]]:
    """Convert a list of (lng, lat) points into a set of grid cell keys.

    Each point is placed into a grid cell of *cell_size* degrees.  For
    polylines we also rasterise the segments between consecutive vertices
    so that long straight segments aren't missed.
    """
    cells: set[tuple[int, int]] = set()
    for i, (lng, lat) in enumerate(coords):
        cx = int(math.floor(lng / cell_size))
        cy = int(math.floor(lat / cell_size))
        # Add the cell and all 8 neighbours (acts as a ~1-cell buffer)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cells.add((cx + dx, cy + dy))

        # Rasterise segment to the next vertex so long edges don't skip cells
        if i + 1 < len(coords):
            nlng, nlat = coords[i + 1]
            dist = max(abs(nlng - lng), abs(nlat - lat))
            steps = int(dist / cell_size) + 1
            if steps > 1:
                for s in range(1, steps):
                    t = s / steps
                    mlng = lng + t * (nlng - lng)
                    mlat = lat + t * (nlat - lat)
                    mcx = int(math.floor(mlng / cell_size))
                    mcy = int(math.floor(mlat / cell_size))
                    for ddx in (-1, 0, 1):
                        for ddy in (-1, 0, 1):
                            cells.add((mcx + ddx, mcy + ddy))
    return cells


def _route_near_pass(
    route_coords: list[list[float]],
    pass_geometry: list[list[tuple[float, float]]],
    threshold: float,
) -> bool:
    """Check whether a route comes within *threshold* degrees of a mountain pass.

    Uses a **grid-based spatial index** for O(N+M) performance instead of the
    naive O(N×M) point-to-segment approach.  Both the mountain pass and the
    route are rasterised into grid cells of *threshold* size.  If any cell is
    occupied by both, the route is considered to traverse the pass.
    """
    cell_size = threshold  # each cell is threshold × threshold degrees

    # 1. Build grid from mountain pass geometry
    pass_cells: set[tuple[int, int]] = set()
    for linestring in pass_geometry:
        if len(linestring) < 2:
            continue
        pass_cells |= _build_grid_cells(linestring, cell_size)

    if not pass_cells:
        return False

    # 2. Walk the route and check for overlap — subsample for extra speed
    n = len(route_coords)
    step = max(1, n // 2000)  # check up to ~2000 vertices

    for idx in range(0, n, step):
        coord = route_coords[idx]
        cx = int(math.floor(coord[0] / cell_size))
        cy = int(math.floor(coord[1] / cell_size))
        if (cx, cy) in pass_cells:
            return True

    return False


def _pass_to_geojson(mountain_pass: MountainPass) -> dict[str, Any] | None:
    """Convert a MountainPass geometry into a GeoJSON object for map display."""
    if not mountain_pass.geometry_coords:
        return None

    if len(mountain_pass.geometry_coords) == 1:
        return {
            "type": "LineString",
            "coordinates": [list(pt) for pt in mountain_pass.geometry_coords[0]],
        }

    return {
        "type": "MultiLineString",
        "coordinates": [
            [list(pt) for pt in ls] for ls in mountain_pass.geometry_coords
        ],
    }


def _get_severity_and_message(
    mountain_pass: MountainPass,
) -> tuple[str, str]:
    """Determine severity and message based on the current month."""
    month = datetime.now(timezone.utc).month

    base = (
        f"This route passes through {mountain_pass.name} ({mountain_pass.road_reference}), "
        f"a Norwegian mountain pass / convoy stretch (kolonnestrekning)."
    )

    if month in (11, 12, 1, 2, 3, 4):
        severity = "high"
        message = (
            f"{base} This road is typically closed from "
            f"{mountain_pass.typical_closed_from} to {mountain_pass.typical_closed_to}. "
            f"Check current status before travelling."
        )
    elif month in (5, 10):
        severity = "medium"
        message = (
            f"{base} This is a shoulder season — the road may be closed. "
            f"Check current conditions before travelling."
        )
    else:
        severity = "low"
        message = (
            f"{base} The road is normally open in summer but may be "
            f"subject to temporary closures for maintenance or weather. "
            f"Check conditions if in doubt."
        )

    return severity, message


class RouteClosureChecker:
    """Checks if routes pass through known mountain passes / seasonal closure areas."""

    PROXIMITY_THRESHOLD_DEG = 0.003  # ~300m at 60°N latitude

    def __init__(self, nvdb_client: NVDBClient | None = None) -> None:
        self._nvdb_client = nvdb_client or NVDBClient()

    async def check_route(self, route_geometry: dict[str, Any]) -> list[RouteWarning]:
        """Check a route GeoJSON geometry against known mountain passes.

        Args:
            route_geometry: A GeoJSON geometry dict (expected ``LineString``).

        Returns:
            A list of :class:`RouteWarning` instances for any mountain passes
            the route appears to traverse.
        """
        warnings: list[RouteWarning] = []

        # Extract coordinates from the route geometry
        route_coords: list[list[float]] = route_geometry.get("coordinates", [])
        if not route_coords:
            logger.debug("Route geometry has no coordinates, skipping closure check")
            return warnings

        geom_type = route_geometry.get("type", "")
        if geom_type != "LineString":
            logger.warning(
                "Unexpected route geometry type '%s', expected 'LineString'", geom_type
            )
            # Still try — coordinates might be usable

        # Build route bounding box
        route_points = [(c[0], c[1]) for c in route_coords]
        route_bbox = _bounding_box(route_points)

        # Fetch mountain passes
        try:
            passes = await self._nvdb_client.get_mountain_passes()
        except Exception:
            logger.exception("Failed to fetch mountain passes from NVDB")
            return warnings

        logger.debug(
            "Checking route (%d vertices) against %d mountain passes",
            len(route_coords),
            len(passes),
        )

        for mp in passes:
            if not mp.geometry_coords:
                continue

            # Flatten all linestring coords for bounding-box calculation
            all_pass_points: list[tuple[float, float]] = []
            for ls in mp.geometry_coords:
                all_pass_points.extend(ls)

            if not all_pass_points:
                continue

            pass_bbox = _bounding_box(all_pass_points)

            # Quick bounding-box rejection
            if not _boxes_overlap(
                route_bbox, pass_bbox, margin=self.PROXIMITY_THRESHOLD_DEG
            ):
                continue

            # Finer proximity check
            if _route_near_pass(
                route_coords, mp.geometry_coords, self.PROXIMITY_THRESHOLD_DEG
            ):
                severity, message = _get_severity_and_message(mp)
                warnings.append(
                    RouteWarning(
                        type="mountain_pass",
                        severity=severity,
                        title=f"Mountain Pass: {mp.name}",
                        message=message,
                        road_reference=mp.road_reference,
                        geometry=_pass_to_geojson(mp),
                    )
                )
                logger.info(
                    "Route intersects mountain pass '%s' (%s) — severity=%s",
                    mp.name,
                    mp.road_reference,
                    severity,
                )

        return warnings
