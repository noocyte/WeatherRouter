"""API routes for WeatherRouter.

Provides endpoints for route calculation, geocoding, and provider management.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from backend.config import settings
from backend.models.route import (
    GeocodingResponse,
    GeocodingResult,
    RouteRequest,
    RoutesResponse,
)
from backend.services.routing import get_routing_provider
from backend.services.weather import get_route_weather

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Color palette for distinguishing route alternatives on the map
ROUTE_COLORS = [
    "#2196F3",  # Blue
    "#FF5722",  # Deep Orange
    "#4CAF50",  # Green
    "#9C27B0",  # Purple
    "#FF9800",  # Orange
]


@router.post("/routes", response_model=RoutesResponse)
async def calculate_routes(request: RouteRequest) -> RoutesResponse:
    """Calculate driving routes between two coordinates.

    Accepts a start and end coordinate, optionally specifying a routing provider.
    Returns one or more route alternatives with geometry, distance, duration,
    and step-by-step instructions. Each alternative is assigned a distinct color
    for map display.

    Args:
        request: The route request containing start/end coordinates and optional provider.

    Returns:
        RoutesResponse with a list of routes and the provider name used.

    Raises:
        HTTPException 400: If the requested provider is not found or unavailable.
        HTTPException 502: If the upstream routing service returns an error.
        HTTPException 500: For unexpected internal errors.
    """
    try:
        provider = get_routing_provider(request.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        routes = await provider.get_routes(request.start, request.end)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Routing service returned an error: {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach routing service: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while calculating routes: {exc}",
        )

    # Assign distinct colors to each route alternative
    for index, route in enumerate(routes):
        route.color = ROUTE_COLORS[index % len(ROUTE_COLORS)]

    # Check each route for mountain pass / closure warnings
    from backend.services.road_closures.checker import RouteClosureChecker

    checker = RouteClosureChecker()
    for route in routes:
        try:
            route.warnings = await checker.check_route(route.geometry)
        except Exception:
            logger.exception("Failed to check route for road closures")

    # Fetch weather for each route when departure_time is provided
    departure_time_str = request.departure_time
    if departure_time_str:
        for route in routes:
            try:
                route.weather = await get_route_weather(
                    route_geometry=route.geometry,
                    distance_km=route.distance_km,
                    duration_minutes=route.duration_minutes,
                    departure_time_str=departure_time_str,
                    warnings=route.warnings,
                )
            except Exception:
                logger.exception(
                    "Failed to fetch weather for route (%.0f km). "
                    "Route will be returned without weather data.",
                    route.distance_km,
                )
    else:
        logger.debug("No departure_time provided — skipping weather analysis")

    return RoutesResponse(routes=routes, provider=provider.name)


@router.get("/geocode", response_model=GeocodingResponse)
async def geocode(
    q: str = Query(..., min_length=1, description="Search query for place name"),
) -> GeocodingResponse:
    """Geocode a place name using the Nominatim API.

    Searches for places matching the query string, focused on Nordic countries
    (Norway, Sweden, Denmark, Finland, Iceland).

    Args:
        q: The search query string (place name, address, etc.).

    Returns:
        GeocodingResponse with a list of matching results.

    Raises:
        HTTPException 502: If the Nominatim service is unreachable or returns an error.
        HTTPException 500: For unexpected internal errors.
    """
    nominatim_url = f"{settings.NOMINATIM_BASE_URL}/search"
    params = {
        "q": q,
        "format": "json",
        "limit": 5,
        "countrycodes": "no,se,dk,fi,is",
    }
    headers = {
        "User-Agent": "WeatherRouter/1.0",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(nominatim_url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Nominatim service returned an error: {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Nominatim service: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred during geocoding: {exc}",
        )

    results = [
        GeocodingResult(
            name=item.get("display_name", "Unknown"),
            lat=float(item["lat"]),
            lng=float(item["lon"]),
        )
        for item in data
        if "lat" in item and "lon" in item
    ]

    return GeocodingResponse(results=results)


@router.get("/providers")
async def list_providers() -> list[dict[str, Any]]:
    """List all registered routing providers and their availability status.

    Returns a list of dictionaries, each containing the provider name and
    whether it is currently available for use (e.g., has required API keys).

    Returns:
        A list of provider info dicts with 'name' and 'available' keys.
    """
    from backend.services.routing.google import GoogleProvider
    from backend.services.routing.osrm import OSRMProvider

    providers = [OSRMProvider(), GoogleProvider()]

    return [
        {
            "name": provider.name,
            "available": provider.is_available(),
        }
        for provider in providers
    ]
