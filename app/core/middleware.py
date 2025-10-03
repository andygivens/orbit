"""
HTTP middleware for the Orbit application.
Extracted from main.py to improve modularity and separation of concerns.
"""

import time

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from .logging import logger


def add_cors_middleware(app):
    """Add CORS middleware to the FastAPI app"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


async def log_requests_middleware(request: Request, call_next):
    """Log all HTTP requests with detailed information"""
    start_time = time.time()

    # Capture request details
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    auth_header = request.headers.get("authorization", "none")
    content_type = request.headers.get("content-type", "none")

    # Log the incoming request with all details
    logger.info("HTTP request",
               method=request.method,
               path=request.url.path,
               client_ip=client_ip,
               user_agent=user_agent,
                auth_header_type=(
                    auth_header.split(" ")[0]
                    if auth_header != "none"
                    else "none"
                ),
               content_type=content_type,
               timestamp=time.time())

    response = await call_next(request)

    # Log the response
    process_time = time.time() - start_time
    logger.info("HTTP response",
               method=request.method,
               path=request.url.path,
               status_code=response.status_code,
               process_time_ms=round(process_time * 1000, 2))

    return response


def add_request_logging_middleware(app):
    """Add request logging middleware to the FastAPI app"""
    app.middleware("http")(log_requests_middleware)
