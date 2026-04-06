"""Abstract base class for weather provider clients."""

from abc import ABC, abstractmethod

from backend.models.route import WeatherPoint
from backend.services.weather.sampler import SamplePoint


class WeatherClient(ABC):
    """Abstract interface for weather data providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    @abstractmethod
    async def get_weather_for_points(
        self, sample_points: list[SamplePoint]
    ) -> list[WeatherPoint]:
        """Fetch weather forecasts for a list of sample points along a route.

        Args:
            sample_points: List of SamplePoint with lat, lng, and arrival_time.

        Returns:
            List of WeatherPoint with full weather data, one per sample point.
        """
        ...
