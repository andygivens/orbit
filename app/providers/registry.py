"""Central registry for provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Callable, Dict

from ..domain.models import ProviderTypeEnum
from .base import ProviderAdapter


def _parse_locator(locator: str) -> tuple[str, str]:
    module_path, sep, attr = locator.partition(":")
    if not sep:
        module_path, attr = module_path.rsplit(".", 1)
    return module_path, attr


@dataclass
class ProviderRegistry:
    factories: Dict[str, Callable[[str, dict], ProviderAdapter]]
    locators: Dict[str, str] = field(default_factory=dict)

    def register(self, type_id: str, factory: Callable[[str, dict], ProviderAdapter]) -> None:
        """Register a provider adapter factory directly."""
        self.factories[type_id] = factory

    def register_locator(self, type_id: str, locator: str) -> None:
        """Register a locator (module:Class) for lazy adapter import."""
        self.locators[type_id] = locator

    def create(self, type_id: str, provider_id: str, config: dict) -> ProviderAdapter:
        factory = self.factories.get(type_id)
        if factory is None:
            locator = self.locators.get(type_id)
            if locator:
                factory = self._load_factory(locator)
                self.factories[type_id] = factory
        if factory is None:
            raise KeyError(f"No adapter registered for provider type '{type_id}'")
        return factory(provider_id, config)

    @staticmethod
    def _load_factory(locator: str) -> Callable[[str, dict], ProviderAdapter]:
        module_path, attr = _parse_locator(locator)
        module = import_module(module_path)
        factory = getattr(module, attr)
        if not callable(factory):
            raise TypeError(f"Adapter factory '{locator}' is not callable")
        return factory


provider_registry = ProviderRegistry(factories={})

provider_registry.register_locator(
    ProviderTypeEnum.APPLE_CALDAV.value,
    "app.providers.apple_caldav:AppleCalDAVAdapter",
)
provider_registry.register_locator(
    ProviderTypeEnum.SKYLIGHT.value,
    "app.providers.skylight:SkylightAdapter",
)
provider_registry.register_locator(
    ProviderTypeEnum.PUBLIC_CALDAV.value,
    "app.providers.apple_caldav:AppleCalDAVAdapter",
)
