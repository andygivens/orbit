# Refactored Skylight API client - orchestrates modular components
from typing import Any, Dict, List, Optional

from ..core.logging import logger
from .skylight.api_client import SkylightAPIClient
from .skylight.event_operations import EventOperations
from .skylight.frame_manager import FrameManager


class SkylightClient:
    """Main Skylight client that orchestrates API operations through focused modules"""

    def __init__(
        self,
        *,
        email: Optional[str] = None,
        password: Optional[str] = None,
        base_url: Optional[str] = None,
        api_client: Optional[SkylightAPIClient] = None,
        frame_manager: Optional[FrameManager] = None,
        event_ops: Optional[EventOperations] = None,
    ):
        self.logger = logger.bind(component="skylight")

        # Initialize modular components, allowing tests to inject fakes/mocks.
        self.api_client = api_client or SkylightAPIClient(
            base_url=base_url,
            email=email,
            password=password,
        )
        self.frame_manager = frame_manager or FrameManager(self.api_client)
        self.event_ops = event_ops or EventOperations(
            self.api_client,
            self.frame_manager,
        )

    # === Authentication & Setup Methods ===
    async def _ensure_authenticated(self):
        """Ensure authentication and frame/category discovery"""
        await self.api_client.ensure_authenticated()
        await self.frame_manager.ensure_frame_and_category()

    # === Frame & Category Management ===
    @property
    def frame_id(self) -> Optional[str]:
        """Get current frame ID"""
        return self.frame_manager.frame_id

    @property
    def category_id(self) -> Optional[str]:
        """Get current category ID"""
        return self.frame_manager.category_id

    async def get_category_id_by_name(self, category_name: str) -> Optional[str]:
        """Look up a specific category ID by name"""
        return await self.frame_manager.get_category_id_by_name(category_name)

    async def get_category_ids_by_names(self, category_names: List[str]) -> List[str]:
        """Resolve multiple category names to IDs in a single API call"""
        return await self.frame_manager.get_category_ids_by_names(category_names)

    # === Event Operations ===
    async def list_events(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """List events in date range, filtered by configured category"""
        return await self.event_ops.list_events(start_date, end_date)

    async def list_events_dt(self, start, end) -> List[Dict[str, Any]]:
        """Convenience wrapper: accepts datetime objects"""
        return await self.event_ops.list_events_dt(start, end)

    async def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new event"""
        return await self.event_ops.create_event(event_data)

    async def update_event(
        self, event_id: str, event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update an existing event"""
        return await self.event_ops.update_event(event_id, event_data)

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event"""
        return await self.event_ops.delete_event(event_id)

    # === Legacy Compatibility Methods ===
    async def get_events(
        self, start_date: str = None, end_date: str = None
    ) -> List[Dict[str, Any]]:
        """Legacy method for backward compatibility"""
        return await self.event_ops.get_events(start_date, end_date)
