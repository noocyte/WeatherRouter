"""Pydantic models for route planning and geocoding."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    """A geographic coordinate with latitude and longitude."""

    lat: float = Field(..., description="Latitude in decimal degrees")
    lng: float = Field(..., description="Longitude in decimal degrees")


class RouteRequest(BaseModel):
    """Request body for computing routes between two points."""

    start: Coordinate = Field(..., description="Starting coordinate")
    end: Coordinate = Field(..., description="Ending coordinate")
    provider: Optional[str] = Field(
        default=None,
        description="Routing provider to use (e.g. 'osrm', 'google'). Falls back to the configured default.",
    )
    departure_time: Optional[str] = Field(
        default=None,
        description="Departure time in ISO 8601 format. Defaults to current time if not provided.",
    )


class RouteStep(BaseModel):
    """A single manoeuvre / instruction along a route."""

    instruction: str = Field(..., description="Human-readable turn instruction")
    distance_km: float = Field(..., description="Distance for this step in kilometres")
    duration_minutes: float = Field(
        ..., description="Estimated duration for this step in minutes"
    )
    start_location: Coordinate = Field(
        ..., description="Coordinate where this step begins"
    )
    end_location: Coordinate = Field(..., description="Coordinate where this step ends")


class RouteWarning(BaseModel):
    """A warning about a potential issue along a route."""

    type: str = Field(..., description="Warning type (e.g. 'mountain_pass')")
    severity: str = Field(..., description="Severity level: 'high', 'medium', or 'low'")
    title: str = Field(..., description="Short warning title")
    message: str = Field(..., description="Detailed warning message")
    road_reference: str = Field(default="", description="Road reference (e.g. 'FV450')")
    geometry: Optional[dict[str, Any]] = Field(
        default=None, description="GeoJSON geometry of affected area"
    )


class WeatherPoint(BaseModel):
    """Weather conditions at a specific point along the route."""

    location: Coordinate = Field(
        ..., description="Geographic location of this weather sample"
    )
    distance_km: float = Field(..., description="Distance from route start in km")
    elevation_m: float = Field(0, description="Elevation in meters above sea level")
    arrival_time: str = Field(..., description="Estimated arrival time (ISO 8601)")
    temperature_c: float = Field(..., description="Temperature in Celsius")
    feels_like_c: Optional[float] = Field(
        None, description="Apparent/feels-like temperature"
    )
    precipitation_mm: float = Field(0, description="Precipitation in mm")
    snowfall_cm: float = Field(0, description="Snowfall in cm")
    snow_depth_m: float = Field(0, description="Snow depth on the ground in meters")
    weather_code: int = Field(0, description="WMO weather code")
    weather_description: str = Field(
        "", description="Human-readable weather description"
    )
    weather_symbol: str = Field("", description="Weather emoji symbol")
    wind_speed_kmh: float = Field(0, description="Wind speed in km/h")
    is_peak: bool = Field(
        False, description="Whether this is a mountain pass peak point"
    )


class TireRecommendation(BaseModel):
    """Overall tire recommendation for the route."""

    verdict: str = Field(
        ...,
        description="summer_ok | winter_advisory | winter_recommended | winter_required",
    )
    title: str = Field(..., description="Short recommendation title")
    message: str = Field(..., description="Detailed explanation")
    icon: str = Field("", description="Emoji icon for the recommendation")


class SunglassesAdvisory(BaseModel):
    """Advisory on whether sunglasses are recommended for the drive."""

    needed: bool = Field(False, description="Whether sunglasses are recommended")
    title: str = Field("", description="Short advisory title")
    message: str = Field("", description="Detailed explanation")
    icon: str = Field("☀️", description="Emoji icon for the advisory")


class RouteWeather(BaseModel):
    """Complete weather analysis for a route."""

    departure_time: str = Field(..., description="Departure time (ISO 8601)")
    weather_provider: str = Field(
        "", description="Name of the weather provider that produced this data"
    )
    weather_points: list[WeatherPoint] = Field(default_factory=list)
    tire_recommendation: TireRecommendation
    sunglasses_advisory: Optional[SunglassesAdvisory] = Field(
        default=None,
        description="Sunglasses / glare advisory (populated when weather is available)",
    )
    min_temperature_c: float = Field(0)
    max_temperature_c: float = Field(0)
    has_snow: bool = Field(False)
    has_rain: bool = Field(False)
    has_freezing_conditions: bool = Field(False)


class Route(BaseModel):
    """A single route alternative returned by a routing provider."""

    geometry: dict[str, Any] = Field(
        ...,
        description="GeoJSON LineString representing the route geometry",
    )
    distance_km: float = Field(..., description="Total route distance in kilometres")
    duration_minutes: float = Field(
        ..., description="Estimated total duration in minutes"
    )
    summary: str = Field(..., description="Short human-readable summary of the route")
    steps: list[RouteStep] = Field(
        default_factory=list, description="Turn-by-turn steps"
    )
    color: Optional[str] = Field(
        default=None,
        description="Hex colour code for rendering this route on a map (e.g. '#2196F3')",
    )
    warnings: list[RouteWarning] = Field(
        default_factory=list,
        description="Warnings about potential issues along this route",
    )
    weather: Optional[RouteWeather] = Field(
        default=None,
        description="Weather analysis along the route (when departure_time is provided)",
    )


class RoutesResponse(BaseModel):
    """Response containing one or more route alternatives."""

    routes: list[Route] = Field(..., description="List of route alternatives")
    provider: str = Field(
        ..., description="Name of the routing provider that produced these routes"
    )


class GeocodingResult(BaseModel):
    """A single geocoding match."""

    name: str = Field(..., description="Display name of the location")
    lat: float = Field(..., description="Latitude in decimal degrees")
    lng: float = Field(..., description="Longitude in decimal degrees")


class GeocodingResponse(BaseModel):
    """Response containing geocoding search results."""

    results: list[GeocodingResult] = Field(
        default_factory=list,
        description="List of matching locations",
    )
