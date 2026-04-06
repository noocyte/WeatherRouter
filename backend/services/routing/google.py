"""Google Maps Directions API routing provider.

Unlike OSRM (which relies on static OpenStreetMap data), the Google Directions
API already accounts for **real-time road closures, live traffic conditions, and
seasonal restrictions**.  This makes it particularly well-suited for the
WeatherRouter application where route safety depends on up-to-date road status.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from backend.config import settings
from backend.models.route import Coordinate, Route, RouteStep
from backend.services.routing.base import RoutingProvider


class GoogleProvider(RoutingProvider):
    """Routing provider backed by the Google Maps Directions API.

    Requires a valid ``GOOGLE_MAPS_API_KEY`` to be set in the environment or
    ``.env`` file.

    The Google Directions API inherently considers real-time traffic, road
    closures, and seasonal restrictions — making it a stronger choice than
    static-data providers (like OSRM) for weather-aware route planning.
    """

    BASE_URL = "https://maps.googleapis.com/maps/api/directions/json"
    HEADERS = {"User-Agent": "WeatherRouter/1.0"}
    TIMEOUT = 30.0  # seconds

    @property
    def name(self) -> str:
        """Return the human-readable provider name."""
        return "google"

    def is_available(self) -> bool:
        """Check whether a Google Maps API key has been configured."""
        return settings.GOOGLE_MAPS_API_KEY is not None

    async def get_routes(self, start: Coordinate, end: Coordinate) -> list[Route]:
        """Fetch driving route alternatives from the Google Directions API.

        Args:
            start: Origin coordinate (lat/lng).
            end: Destination coordinate (lat/lng).

        Returns:
            A list of :class:`Route` objects (typically 1–3 alternatives).

        Raises:
            RuntimeError: If the Google API returns an error or is unreachable.
        """
        if not self.is_available():
            raise RuntimeError(
                "Google Maps API key is not configured. "
                "Set GOOGLE_MAPS_API_KEY in your environment or .env file."
            )

        params = {
            "origin": f"{start.lat},{start.lng}",
            "destination": f"{end.lat},{end.lng}",
            "alternatives": "true",
            "mode": "driving",
            "key": settings.GOOGLE_MAPS_API_KEY,
        }

        async with httpx.AsyncClient(
            headers=self.HEADERS, timeout=self.TIMEOUT
        ) as client:
            try:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    "Google Directions API request timed out. Please try again later."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Google Directions API returned HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except httpx.RequestError as exc:
                raise RuntimeError(
                    f"Failed to connect to Google Directions API: {exc}"
                ) from exc

        data = response.json()
        status = data.get("status", "UNKNOWN")

        if status != "OK":
            error_message = data.get("error_message", "")
            status_messages = {
                "NOT_FOUND": "One or both of the specified locations could not be found.",
                "ZERO_RESULTS": "No route could be found between the specified locations.",
                "REQUEST_DENIED": (
                    f"The Google Directions API request was denied. "
                    f"Check your API key. {error_message}"
                ),
                "OVER_DAILY_LIMIT": (
                    "Google Directions API daily quota exceeded. "
                    "Please try again tomorrow or check billing."
                ),
                "OVER_QUERY_LIMIT": (
                    "Google Directions API rate limit exceeded. "
                    "Please try again shortly."
                ),
                "MAX_WAYPOINTS_EXCEEDED": "Too many waypoints were provided.",
                "INVALID_REQUEST": (
                    f"Invalid request to Google Directions API. {error_message}"
                ),
                "UNKNOWN_ERROR": (
                    "A server error occurred on Google's side. Please try again later."
                ),
            }
            message = status_messages.get(
                status,
                f"Google Directions API error ({status}): {error_message}",
            )
            raise RuntimeError(message)

        routes: list[Route] = []
        for google_route in data.get("routes", []):
            route = self._parse_route(google_route)
            routes.append(route)

        return routes

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_route(self, google_route: dict[str, Any]) -> Route:
        """Convert a single Google Directions route object into our Route model.

        Args:
            google_route: A route dict from the Google Directions JSON response.

        Returns:
            A populated :class:`Route` instance.
        """
        # Decode the overview polyline into GeoJSON coordinates
        encoded_polyline = google_route.get("overview_polyline", {}).get("points", "")
        coordinates = self._decode_polyline(encoded_polyline)
        geometry: dict[str, Any] = {
            "type": "LineString",
            "coordinates": coordinates,
        }

        # Aggregate distance and duration across all legs
        total_distance_m = 0
        total_duration_s = 0
        steps: list[RouteStep] = []

        for leg in google_route.get("legs", []):
            total_distance_m += leg.get("distance", {}).get("value", 0)
            total_duration_s += leg.get("duration", {}).get("value", 0)

            for google_step in leg.get("steps", []):
                step = self._parse_step(google_step)
                steps.append(step)

        distance_km = round(total_distance_m / 1000, 2)
        duration_minutes = round(total_duration_s / 60, 2)

        summary = google_route.get("summary", "") or "Route via Google Maps"

        return Route(
            geometry=geometry,
            distance_km=distance_km,
            duration_minutes=duration_minutes,
            summary=summary,
            steps=steps,
            color=None,
        )

    def _parse_step(self, google_step: dict[str, Any]) -> RouteStep:
        """Convert a single Google Directions step into a :class:`RouteStep`.

        Args:
            google_step: A step dict from a Google Directions leg.

        Returns:
            A :class:`RouteStep` instance.
        """
        instruction = self._strip_html(google_step.get("html_instructions", "Continue"))

        distance_km = round(google_step.get("distance", {}).get("value", 0) / 1000, 3)
        duration_minutes = round(
            google_step.get("duration", {}).get("value", 0) / 60, 2
        )

        start_loc_data = google_step.get("start_location", {})
        end_loc_data = google_step.get("end_location", {})

        start_location = Coordinate(
            lat=start_loc_data.get("lat", 0.0),
            lng=start_loc_data.get("lng", 0.0),
        )
        end_location = Coordinate(
            lat=end_loc_data.get("lat", 0.0),
            lng=end_loc_data.get("lng", 0.0),
        )

        return RouteStep(
            instruction=instruction,
            distance_km=distance_km,
            duration_minutes=duration_minutes,
            start_location=start_location,
            end_location=end_location,
        )

    @staticmethod
    def _decode_polyline(encoded: str) -> list[list[float]]:
        """Decode a Google encoded polyline string into a list of coordinates.

        Implements the `Encoded Polyline Algorithm Format
        <https://developers.google.com/maps/documentation/utilities/polylinealgorithm>`_.

        Args:
            encoded: The encoded polyline string from the Google API.

        Returns:
            A list of ``[lng, lat]`` pairs (GeoJSON coordinate order).
        """
        coordinates: list[list[float]] = []
        index = 0
        length = len(encoded)
        lat = 0
        lng = 0

        while index < length:
            # Decode latitude delta
            shift = 0
            result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            if result & 1:
                lat += ~(result >> 1)
            else:
                lat += result >> 1

            # Decode longitude delta
            shift = 0
            result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            if result & 1:
                lng += ~(result >> 1)
            else:
                lng += result >> 1

            # Convert from 1e5-scaled integers to floats, GeoJSON order [lng, lat]
            coordinates.append([lng / 1e5, lat / 1e5])

        return coordinates

    @staticmethod
    def _strip_html(html: str) -> str:
        """Remove HTML tags from a string.

        Google Directions API returns instructions with inline HTML
        (e.g. ``Turn <b>right</b> onto <b>E18</b>``). This helper strips
        all tags, returning plain text.

        Args:
            html: A string potentially containing HTML tags.

        Returns:
            The input string with all HTML tags removed.
        """
        return re.sub(r"<[^>]+>", "", html)
