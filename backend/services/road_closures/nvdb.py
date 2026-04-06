"""Client for fetching mountain pass (Kolonnestrekning) data from Vegvesen's NVDB API v3.

This module provides an async client that fetches, parses, and caches data about
Norwegian mountain passes / convoy stretches from the National Road Database (NVDB).
Geometry is parsed from WKT without any external geometry libraries.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MountainPass:
    """Represents a single Kolonnestrekning (mountain pass / convoy stretch)."""

    nvdb_id: int
    name: str  # e.g. "Suleskarvegen" or road ref if no name found
    road_reference: str  # e.g. "FV450"
    geometry_coords: list[list[tuple[float, float]]] = field(default_factory=list)
    typical_closed_from: str = "November"
    typical_closed_to: str = "May"


def parse_wkt_geometry(wkt: str) -> list[list[tuple[float, float]]]:
    """Parse WKT LINESTRING Z or MULTILINESTRING Z into lists of (lng, lat) tuples.

    Handles:
      - LINESTRING Z (lng lat z, lng lat z, ...)
      - MULTILINESTRING Z ((lng lat z, lng lat z, ...), (lng lat z, ...))
      - Variants without the Z qualifier
      - MULTILINESTRING ZM / LINESTRING ZM (with measure value)

    Args:
        wkt: A WKT geometry string in WGS84 (longitude first).

    Returns:
        A list of linestrings, where each linestring is a list of (lng, lat) tuples.
    """
    if not wkt or not isinstance(wkt, str):
        return []

    wkt = wkt.strip()

    # Determine the geometry type (case-insensitive)
    upper = wkt.upper()

    try:
        if upper.startswith("MULTILINESTRING"):
            return _parse_multi_linestring(wkt)
        elif upper.startswith("LINESTRING"):
            coords = _parse_single_linestring(wkt)
            return [coords] if coords else []
        else:
            logger.warning("Unsupported WKT geometry type: %.60s...", wkt)
            return []
    except Exception:
        logger.exception("Failed to parse WKT geometry: %.120s...", wkt)
        return []


def _extract_coord_pairs(text: str) -> list[tuple[float, float]]:
    """Extract (lng, lat) pairs from a string of space-separated coordinate groups.

    NVDB with srid=4326 returns coordinates in **(lat, lng, [z])** order
    (following the EPSG:4326 axis convention), so we swap them here to
    produce the **(lng, lat)** order used by GeoJSON and the rest of the app.
    """
    coords: list[tuple[float, float]] = []
    # Split on commas to get individual coordinate groups
    groups = text.split(",")
    for group in groups:
        parts = group.strip().split()
        if len(parts) >= 2:
            try:
                # NVDB srid=4326 gives (lat, lng, [z]) — swap to (lng, lat)
                lat = float(parts[0])
                lng = float(parts[1])
                coords.append((lng, lat))
            except (ValueError, IndexError):
                continue
    return coords


def _parse_single_linestring(wkt: str) -> list[tuple[float, float]]:
    """Parse a LINESTRING [Z[M]] (...) WKT string."""
    # Find the content inside the outermost parentheses
    match = re.search(r"\(\s*(.+?)\s*\)", wkt, re.DOTALL)
    if not match:
        return []
    return _extract_coord_pairs(match.group(1))


def _parse_multi_linestring(wkt: str) -> list[list[tuple[float, float]]]:
    """Parse a MULTILINESTRING [Z[M]] ((...), (...)) WKT string."""
    linestrings: list[list[tuple[float, float]]] = []

    # Find the outermost parenthesised block after the type name
    outer_match = re.search(
        r"MULTILINESTRING\s*Z?M?\s*\((.+)\)", wkt, re.IGNORECASE | re.DOTALL
    )
    if not outer_match:
        return []

    inner = outer_match.group(1)

    # Find each individual (...) block inside the outer parentheses
    for ring_match in re.finditer(r"\(([^()]+)\)", inner):
        coords = _extract_coord_pairs(ring_match.group(1))
        if coords:
            linestrings.append(coords)

    return linestrings


class NVDBClient:
    """Client for fetching mountain pass data from Vegvesen's NVDB API v3.

    Data is fetched once and cached in-memory for 24 hours. Subsequent calls
    within the TTL window return the cached result immediately.
    """

    NVDB_BASE_URL = "https://nvdbapiles-v3.atlas.vegvesen.no"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 WeatherRouter/1.0 route-planner-app",
        "Accept": "application/json",
    }
    KOLONNESTREKNING_TYPE_ID = 319

    # In-memory cache (class-level so it persists across instances)
    _cache: list[MountainPass] | None = None
    _cache_time: float = 0
    CACHE_TTL: float = 86400  # 24 hours in seconds

    async def get_mountain_passes(self) -> list[MountainPass]:
        """Fetch all Kolonnestrekning objects from NVDB, using cache when possible.

        Returns:
            A list of MountainPass objects representing all known mountain passes.
        """
        now = time.monotonic()

        if (
            NVDBClient._cache is not None
            and (now - NVDBClient._cache_time) < NVDBClient.CACHE_TTL
        ):
            logger.debug(
                "NVDB cache hit: %d mountain passes (age %.0fs)",
                len(NVDBClient._cache),
                now - NVDBClient._cache_time,
            )
            return NVDBClient._cache

        logger.info("NVDB cache miss — fetching Kolonnestrekning data from NVDB API")

        passes = await self._fetch_all_passes()

        NVDBClient._cache = passes
        NVDBClient._cache_time = time.monotonic()

        logger.info("NVDB: cached %d mountain passes", len(passes))
        return passes

    async def _fetch_all_passes(self) -> list[MountainPass]:
        """Fetch all Kolonnestrekning objects from the NVDB API, handling pagination."""
        all_passes: list[MountainPass] = []
        url = f"{self.NVDB_BASE_URL}/vegobjekter/{self.KOLONNESTREKNING_TYPE_ID}"
        params = {
            "inkluder": "egenskaper,lokasjon,geometri",
            "antall": 100,
            "srid": 4326,
        }

        page_size = params.get("antall", 100)

        async with httpx.AsyncClient(timeout=60.0, headers=self.HEADERS) as client:
            while url:
                logger.debug("NVDB API request: %s params=%s", url, params)
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "NVDB API HTTP error %d: %s",
                        exc.response.status_code,
                        exc.response.text[:200],
                    )
                    break
                except httpx.RequestError as exc:
                    logger.error("NVDB API request failed: %s", exc)
                    break

                data = response.json()
                objects = data.get("objekter", [])
                logger.debug("NVDB API returned %d objects in this page", len(objects))

                for obj in objects:
                    mountain_pass = self._parse_object(obj)
                    if mountain_pass is not None:
                        all_passes.append(mountain_pass)

                # Stop pagination when we got fewer objects than the page
                # size — that means we've reached the last page.  The NVDB
                # API always returns a 'neste' link, even on the last page,
                # so we must NOT rely on its absence to detect the end.
                returnert = data.get("metadata", {}).get("returnert", len(objects))
                if returnert < page_size or len(objects) == 0:
                    break

                # Follow the pagination link for the next page
                neste = data.get("metadata", {}).get("neste", {})
                next_href = neste.get("href") if isinstance(neste, dict) else None
                if not next_href:
                    break

                url = next_href
                params = {}  # params are embedded in the 'neste' URL

        return all_passes

    def _parse_object(self, obj: dict[str, Any]) -> MountainPass | None:
        """Parse a single NVDB vegobjekt into a MountainPass.

        Args:
            obj: A dict representing one vegobjekt from the NVDB API response.

        Returns:
            A MountainPass instance, or None if essential data is missing.
        """
        nvdb_id = obj.get("id")
        if nvdb_id is None:
            return None

        # --- Extract name from egenskaper ---
        name = ""
        egenskaper = obj.get("egenskaper", [])
        for egenskap in egenskaper:
            if isinstance(egenskap, dict) and egenskap.get("navn") == "Navn":
                name = str(egenskap.get("verdi", "")).strip()
                break

        # --- Extract road reference from lokasjon ---
        road_reference = ""
        lokasjon = obj.get("lokasjon", {})
        vegsystemreferanser = lokasjon.get("vegsystemreferanser", [])
        if vegsystemreferanser and isinstance(vegsystemreferanser, list):
            first_ref = vegsystemreferanser[0]
            if isinstance(first_ref, dict):
                # Try the 'kortform' field first (e.g. "FV450 S1D1 m0-12345")
                kortform = first_ref.get("kortform", "")
                if kortform:
                    # Extract just the road part (e.g. "FV450")
                    road_match = re.match(r"([A-Z]+\d+)", str(kortform).upper())
                    if road_match:
                        road_reference = road_match.group(1)

                # Fallback: build from vegsystem dict
                if not road_reference:
                    vegsystem = first_ref.get("vegsystem", {})
                    if isinstance(vegsystem, dict):
                        vegkategori = vegsystem.get("vegkategori", "")
                        nummer = vegsystem.get("nummer", "")
                        if vegkategori and nummer:
                            road_reference = f"{vegkategori}{nummer}".upper()

        # Provide a fallback name if none found
        if not name:
            name = road_reference if road_reference else f"Kolonnestrekning {nvdb_id}"

        # --- Extract geometry from geometri.wkt ---
        geometry_coords: list[list[tuple[float, float]]] = []
        geometri = obj.get("geometri", {})
        if isinstance(geometri, dict):
            wkt = geometri.get("wkt", "")
            if wkt:
                geometry_coords = parse_wkt_geometry(wkt)

        if not geometry_coords:
            logger.debug(
                "NVDB object %d (%s) has no usable geometry, skipping", nvdb_id, name
            )
            return None

        return MountainPass(
            nvdb_id=nvdb_id,
            name=name,
            road_reference=road_reference,
            geometry_coords=geometry_coords,
            typical_closed_from="November",
            typical_closed_to="May",
        )
