# Core HTTP client for Skylight API
import asyncio
import base64
import time
from typing import Optional

import httpx

from ...core.logging import logger


class SkylightAPIClient:
    """Core HTTP client for Skylight API with authentication and retry logic"""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ):
        configured_base_url = base_url or "https://app.ourskylight.com"
        self.base_url = configured_base_url.rstrip("/")
        self.email = email
        self.password = password
        self.session_id: Optional[str] = None
        self.token: Optional[str] = None
        self.auth_header: Optional[str] = None
        self.last_login: float = 0
        self.logger = logger.bind(component="skylight_api")

    async def ensure_authenticated(self):
        """Ensure we have a valid authentication token"""
        if not self.auth_header or time.time() - self.last_login > 43200:  # 12 hours
            await self.login()

    async def login(self):
        """Authenticate with Skylight API"""
        self.logger.info("Logging in to Skylight")

        login_payload = {
            "email": self.email,
            "password": self.password,
            "name": "",
            "phone": "",
            "resettingPassword": False,
            "textMeTheApp": True,
            "agreedToMarketing": True
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/sessions",
                    json=login_payload
                )
                response.raise_for_status()

                data = response.json()
                session_data = data.get("data", {})
                self.session_id = session_data.get("id")
                attributes = session_data.get("attributes", {})
                self.token = attributes.get("token")

                if not self.session_id or not self.token:
                    raise ValueError("Missing session_id or token in response")

                # Build auth header
                auth_string = f"{self.session_id}:{self.token}"
                b64_auth = base64.b64encode(auth_string.encode()).decode("ascii")
                self.auth_header = f"Basic {b64_auth}"
                self.last_login = time.time()

                self.logger.info(
                    "Skylight login successful",
                    session_id=self.session_id,
                )

            except httpx.HTTPStatusError as e:
                self.logger.error("Skylight login failed",
                                status_code=e.response.status_code,
                                response=e.response.text)
                raise
            except Exception as e:
                self.logger.error("Skylight login error", error=str(e))
                raise

    async def make_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make authenticated request with retry logic"""
        await self.ensure_authenticated()

        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": self.auth_header,
            "Content-Type": "application/json"
        })

        url = f"{self.base_url}{path}"

        # Basic retry policy for transient server errors
        max_retries = 3
        backoff = 1.0

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        **kwargs,
                    )

                    # Retry once on auth failure
                    if response.status_code in [401, 403]:
                        self.logger.warning("Auth failed, retrying with fresh token")
                        await self.login()
                        headers["Authorization"] = self.auth_header
                        response = await client.request(
                            method,
                            url,
                            headers=headers,
                            **kwargs,
                        )

                    # Exponential backoff on rate limiting
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        self.logger.warning(
                            "Rate limited, waiting",
                            retry_after=retry_after,
                        )
                        await asyncio.sleep(min(retry_after, 300))  # Cap at 5 minutes
                        response = await client.request(
                            method,
                            url,
                            headers=headers,
                            **kwargs,
                        )

                    # Handle transient 5xx errors with retries
                    if (
                        response.status_code >= 500
                        and response.status_code < 600
                        and attempt < max_retries
                    ):
                        self.logger.warning(
                            "Skylight 5xx, retrying",
                            status=response.status_code,
                            attempt=attempt,
                        )
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue

                    response.raise_for_status()
                    return response

                except httpx.HTTPStatusError as e:
                    # Log request context for debugging (avoid secrets)
                    req_json = None
                    try:
                        req_json = kwargs.get("json")
                    except Exception:
                        pass
                    self.logger.error(
                        "Skylight API error",
                        method=method,
                        path=path,
                        status_code=e.response.status_code,
                        response=e.response.text[:2000],
                        request_body=req_json,
                    )
                    # Retry on final 5xx if attempts remain
                    if 500 <= e.response.status_code < 600 and attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    raise
                except Exception as e:
                    self.logger.error("Skylight request failed",
                                    method=method, path=path, error=str(e))
                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    raise

    async def make_request_without_auth_check(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """Make authenticated request without frame-ID requirements."""
        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": self.auth_header,
            "Content-Type": "application/json"
        })

        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(method, url, headers=headers, **kwargs)

                # Retry once on auth failure
                if response.status_code in [401, 403]:
                    self.logger.warning("Auth failed, retrying with fresh token")
                    await self.login()
                    headers["Authorization"] = self.auth_header
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        **kwargs,
                    )

                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as e:
                self.logger.error("Skylight API error",
                                method=method, path=path,
                                status_code=e.response.status_code,
                                response=e.response.text)
                raise
            except Exception as e:
                self.logger.error("Skylight request failed",
                                method=method, path=path, error=str(e))
                raise
