"""Abstract base class for routing providers."""

from abc import ABC, abstractmethod

from backend.models.route import Coordinate, Route


class RoutingProvider(ABC):
    """Base class that all routing providers must implement.

    Each provider encapsulates the logic for communicating with a specific
    routing engine (e.g. OSRM, Google Directions API) and transforming the
    response into a common set of ``Route`` objects.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the human-readable name of this routing provider."""
        ...

    @abstractmethod
    async def get_routes(self, start: Coordinate, end: Coordinate) -> list[Route]:
        """Fetch one or more route alternatives between *start* and *end*.

        Args:
            start: The origin coordinate (latitude, longitude).
            end: The destination coordinate (latitude, longitude).

        Returns:
            A list of ``Route`` objects. The list may contain a single route
            or multiple alternatives, depending on the provider's capabilities.

        Raises:
            RuntimeError: If the provider fails to compute a route.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether this provider is ready to serve requests.

        Returns:
            ``True`` if the provider can be used (e.g. required API keys are
            configured), ``False`` otherwise.
        """
        ...
