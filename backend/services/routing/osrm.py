"""OSRM routing provider.

Uses the public OSRM HTTP API to compute driving routes between two coordinates.
Documentation: https://project-osrm.org/docs/v5.24.0/api/
"""

from typing import Any

import httpx

from backend.config import settings
from backend.models.route import Coordinate, Route, RouteStep
from backend.services.routing.base import RoutingProvider


class OSRMProvider(RoutingProvider):
    """Routing provider that uses the OSRM public API.

    OSRM (Open Source Routing Machine) provides free routing based on
    OpenStreetMap data. No API key is required.

    Important: OSRM uses ``longitude,latitude`` order in URL parameters,
    which is the opposite of the common ``latitude,longitude`` convention.
    """

    HEADERS = {"User-Agent": "WeatherRouter/1.0"}
    TIMEOUT = 30.0  # seconds

    @property
    def name(self) -> str:
        """Return the human-readable provider name."""
        return "osrm"

    def is_available(self) -> bool:
        """OSRM is always available — no API key required."""
        return True

    async def get_routes(self, start: Coordinate, end: Coordinate) -> list[Route]:
        """Fetch driving route alternatives from the OSRM API.

        Args:
            start: Origin coordinate (lat/lng).
            end: Destination coordinate (lat/lng).

        Returns:
            A list of :class:`Route` objects (typically 1–3 alternatives).

        Raises:
            RuntimeError: If the OSRM API returns an error or is unreachable.
        """
        # OSRM expects longitude,latitude order
        url = (
            f"{settings.OSRM_BASE_URL}/route/v1/driving/"
            f"{start.lng},{start.lat};{end.lng},{end.lat}"
        )
        params = {
            "overview": "full",
            "alternatives": "true",
            "geometries": "geojson",
            "steps": "true",
        }

        async with httpx.AsyncClient(
            headers=self.HEADERS, timeout=self.TIMEOUT
        ) as client:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    "OSRM request timed out. Please try again later."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"OSRM returned HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except httpx.RequestError as exc:
                raise RuntimeError(f"Failed to connect to OSRM service: {exc}") from exc

        data = response.json()

        if data.get("code") != "Ok":
            message = data.get("message", "Unknown OSRM error")
            raise RuntimeError(f"OSRM error: {message}")

        routes: list[Route] = []
        for osrm_route in data.get("routes", []):
            route = self._parse_route(osrm_route)
            routes.append(route)

        return routes

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_route(self, osrm_route: dict[str, Any]) -> Route:
        """Convert a single OSRM route object into our Route model.

        Args:
            osrm_route: A route dict straight from the OSRM JSON response.

        Returns:
            A populated :class:`Route` instance.
        """
        geometry = osrm_route.get("geometry", {})
        distance_km = round(osrm_route.get("distance", 0) / 1000, 2)
        duration_minutes = round(osrm_route.get("duration", 0) / 60, 2)

        steps: list[RouteStep] = []
        for leg in osrm_route.get("legs", []):
            for osrm_step in leg.get("steps", []):
                step = self._parse_step(osrm_step)
                if step is not None:
                    steps.append(step)

        route_summary = self._build_summary(osrm_route)

        return Route(
            geometry=geometry,
            distance_km=distance_km,
            duration_minutes=duration_minutes,
            summary=route_summary,
            steps=steps,
            color=None,
        )

    def _parse_step(self, osrm_step: dict[str, Any]) -> RouteStep | None:
        """Convert a single OSRM step into a :class:`RouteStep`.

        Args:
            osrm_step: A step dict from an OSRM leg.

        Returns:
            A :class:`RouteStep`, or ``None`` for empty/degenerate steps.
        """
        maneuver = osrm_step.get("maneuver", {})
        location = maneuver.get("location", [0, 0])  # [lng, lat]

        # Build a human-readable instruction from maneuver metadata
        instruction = self._build_instruction(osrm_step)

        distance_km = round(osrm_step.get("distance", 0) / 1000, 3)
        duration_minutes = round(osrm_step.get("duration", 0) / 60, 2)

        # Determine start and end locations
        step_geometry = osrm_step.get("geometry", {})
        coords = step_geometry.get("coordinates", [])

        if coords:
            # GeoJSON coordinates are [lng, lat]
            start_loc = Coordinate(lat=coords[0][1], lng=coords[0][0])
            end_loc = Coordinate(lat=coords[-1][1], lng=coords[-1][0])
        else:
            # Fall back to maneuver location for both
            start_loc = Coordinate(lat=location[1], lng=location[0])
            end_loc = Coordinate(lat=location[1], lng=location[0])

        return RouteStep(
            instruction=instruction,
            distance_km=distance_km,
            duration_minutes=duration_minutes,
            start_location=start_loc,
            end_location=end_loc,
        )

    @staticmethod
    def _build_instruction(osrm_step: dict[str, Any]) -> str:
        """Derive a human-readable instruction string from an OSRM step.

        Args:
            osrm_step: A step dict from an OSRM leg.

        Returns:
            A short instruction such as ``"Turn right onto E6"`` or
            ``"Continue on Storgata"``.
        """
        maneuver = osrm_step.get("maneuver", {})
        step_type = maneuver.get("type", "")
        modifier = maneuver.get("modifier", "")
        road_name = osrm_step.get("name", "")

        # Map OSRM maneuver types to friendly phrases
        type_phrases = {
            "depart": "Depart",
            "arrive": "Arrive at destination",
            "turn": f"Turn {modifier}" if modifier else "Turn",
            "continue": "Continue",
            "merge": f"Merge {modifier}" if modifier else "Merge",
            "on ramp": "Take the on-ramp",
            "off ramp": "Take the off-ramp",
            "fork": f"Keep {modifier}" if modifier else "Fork",
            "end of road": f"Turn {modifier}" if modifier else "End of road",
            "new name": "Continue",
            "roundabout": "Enter the roundabout",
            "exit roundabout": "Exit the roundabout",
            "rotary": "Enter the rotary",
            "exit rotary": "Exit the rotary",
            "notification": "Notification",
        }

        phrase = type_phrases.get(step_type, step_type.replace("_", " ").capitalize())

        if road_name and step_type not in ("arrive",):
            phrase = f"{phrase} onto {road_name}"

        return phrase or "Continue on route"

    @staticmethod
    def _build_summary(osrm_route: dict[str, Any]) -> str:
        """Build a route summary string from OSRM leg summaries.

        Args:
            osrm_route: A route dict from the OSRM JSON response.

        Returns:
            A summary like ``"E6, E18"`` or ``"Route via OSRM"``.
        """
        parts: list[str] = []
        for leg in osrm_route.get("legs", []):
            leg_summary = leg.get("summary", "")
            if leg_summary:
                parts.append(leg_summary)

        return ", ".join(parts) if parts else "Route via OSRM"
