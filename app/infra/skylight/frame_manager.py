# Frame discovery and management for Skylight API
from typing import List, Optional

from ...core.logging import logger


class FrameManager:
    """Manages Skylight frame discovery and category lookups"""

    def __init__(self, api_client):
        self.api_client = api_client
        # Set by adapter via provider config overrides (frame_name/category_name)
        self.frame_name = None
        self.category_name = None
        self.frame_id: Optional[str] = None
        self.category_id: Optional[str] = None
        self.logger = logger.bind(component="skylight_frame")

    async def ensure_frame_and_category(self):
        """Ensure we have frame ID and category ID"""
        if not self.frame_name:
            raise ValueError(
                "Skylight frame name is not configured. Update the provider "
                "settings."
            )
        if not self.frame_id:
            await self.get_frame_id()
        if not self.category_name:
            raise ValueError(
                "Skylight category name is not configured. Update the "
                "provider settings."
            )
        if not self.category_id:
            await self.get_category_id()

    async def get_frame_id(self):
        """Get the frame ID by name from the frames list"""
        self.logger.info("Getting frame ID", frame_name=self.frame_name)

        try:
            response = await self.api_client.make_request_without_auth_check(
                "GET", "/api/frames"
            )
            data = response.json()

            frames = data.get("data", [])
            for frame in frames:
                attrs = frame.get("attributes", {})
                frame_label = attrs.get("label") or attrs.get("name")
                if frame_label == self.frame_name:
                    self.frame_id = frame.get("id")
                    self.logger.info(
                        "Found frame", frame_id=self.frame_id, name=self.frame_name
                    )
                    return

            # If not found, list available frames
            available_frames = []
            for frame in frames:
                attrs = frame.get("attributes", {})
                name = attrs.get("label") or attrs.get("name") or "Unknown"
                available_frames.append(name)
            self.logger.error(
                "Frame not found", target=self.frame_name, available=available_frames
            )
            raise ValueError(
                (
                    f"Frame '{self.frame_name}' not found. Available frames: "
                    f"{available_frames}"
                )
            )

        except Exception as e:
            self.logger.error("Failed to get frame ID", error=str(e))
            raise

    async def get_category_id(self):
        """Get the category ID by name within the frame"""
        self.logger.info("Getting category ID",
                        frame_id=self.frame_id,
                        category_name=self.category_name)

        try:
            response = await self.api_client.make_request_without_auth_check(
                "GET", f"/api/frames/{self.frame_id}/categories"
            )
            data = response.json()

            categories = data.get("data", [])
            for category in categories:
                attrs = category.get("attributes", {})
                cat_label = attrs.get("label") or attrs.get("name")
                if cat_label == self.category_name:
                    self.category_id = category.get("id")
                    self.logger.info("Found category",
                                   category_id=self.category_id,
                                   name=self.category_name)
                    return

            # If not found, list available categories
            available_categories = []
            for category in categories:
                attrs = category.get("attributes", {})
                name = attrs.get("label") or attrs.get("name") or "Unknown"
                available_categories.append(name)
            self.logger.warning(
                "Category not found, will create events without specific category",
                target=self.category_name,
                available=available_categories,
            )

            # Use first available category as fallback
            if categories:
                self.category_id = categories[0].get("id")
                fallback_name = categories[0].get("attributes", {}).get(
                    "name", "Unknown"
                )
                self.logger.info("Using fallback category",
                               category_id=self.category_id,
                               name=fallback_name)
            else:
                self.category_id = None

        except Exception as e:
            self.logger.warning(
                "Failed to get category ID, will create events without category",
                error=str(e),
            )
            self.category_id = None

    async def get_category_id_by_name(self, category_name: str) -> Optional[str]:
        """Look up a specific category ID by name"""
        self.logger.info("Looking up category ID", category_name=category_name)
        try:
            await self.ensure_frame_and_category()
            response = await self.api_client.make_request_without_auth_check(
                "GET", f"/api/frames/{self.frame_id}/categories"
            )
            data = response.json()
            categories = data.get("data", [])

            for category in categories:
                attrs = category.get("attributes", {})
                cat_label = attrs.get("label") or attrs.get("name")
                if cat_label and cat_label.lower() == category_name.lower():
                    category_id = category.get("id")
                    self.logger.info(
                        "Found category", category_id=category_id, name=category_name
                    )
                    return category_id

            available_categories = []
            for category in categories:
                attrs = category.get("attributes", {})
                name = attrs.get("label") or attrs.get("name") or "Unknown"
                available_categories.append(name)
            self.logger.warning(
                "Category not found",
                target=category_name,
                available=available_categories,
            )
            return None
        except Exception as e:
            self.logger.error(
                "Failed to lookup category ID",
                error=str(e),
                category_name=category_name,
            )
            return None

    async def get_category_ids_by_names(self, category_names: List[str]) -> List[str]:
        """Resolve multiple category names to IDs in a single API call"""
        self.logger.info(
            "Looking up multiple category IDs", category_names=category_names
        )
        try:
            await self.ensure_frame_and_category()
            response = await self.api_client.make_request_without_auth_check(
                "GET", f"/api/frames/{self.frame_id}/categories"
            )
            data = response.json()
            categories = data.get("data", [])

            # Build lookup map
            category_map = {}
            for category in categories:
                attrs = category.get("attributes", {})
                cat_label = attrs.get("label") or attrs.get("name")
                if cat_label:
                    category_map[cat_label.lower()] = str(category.get("id"))

            # Resolve requested categories
            resolved_ids = []
            found_categories = []
            for name in category_names:
                category_id = category_map.get(name.lower())
                if category_id:
                    resolved_ids.append(category_id)
                    found_categories.append(name)
                else:
                    self.logger.warning(
                        "Category not found",
                        target=name,
                        available=list(category_map.keys()),
                    )

            self.logger.info(
                "Resolved categories",
                requested=category_names,
                found=found_categories,
                ids=resolved_ids,
            )
            return resolved_ids
        except Exception as e:
            self.logger.error(
                "Failed to lookup category IDs",
                error=str(e),
                category_names=category_names,
            )
            return []
