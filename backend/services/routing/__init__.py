"""Routing services package.

Provides a factory function to instantiate the appropriate routing provider
based on configuration or an explicit provider name.
"""

from backend.services.routing.osrm import OSRMProvider

from backend.config import settings
from backend.services.routing.base import RoutingProvider
from backend.services.routing.google import GoogleProvider

_PROVIDERS: dict[str, type[RoutingProvider]] = {
    "osrm": OSRMProvider,
    "google": GoogleProvider,
}


def get_routing_provider(provider_name: str | None = None) -> RoutingProvider:
    """Return an instantiated routing provider ready for use.

    Args:
        provider_name: Name of the desired provider (e.g. ``"osrm"`` or
            ``"google"``).  When *None*, the value of
            ``settings.ROUTING_PROVIDER`` is used as the default.

    Returns:
        A concrete :class:`RoutingProvider` instance.

    Raises:
        ValueError: If the requested provider is unknown or not currently
            available (e.g. missing API key).
    """
    name = (provider_name or settings.ROUTING_PROVIDER).lower().strip()

    provider_cls = _PROVIDERS.get(name)
    if provider_cls is None:
        available = ", ".join(sorted(_PROVIDERS.keys()))
        raise ValueError(
            f"Unknown routing provider '{name}'. Available providers: {available}"
        )

    provider = provider_cls()

    if not provider.is_available():
        raise ValueError(
            f"Routing provider '{name}' is not available. "
            "Please check its configuration (e.g. API keys)."
        )

    return provider
