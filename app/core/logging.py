# Structured logging configuration
import logging
import sys

import structlog

from .settings import settings

LEVEL_WIDTH = 9  # Ensures component column alignment


def _render_event(_, __, event_dict: dict) -> str:
    level = event_dict.pop("level", "INFO").upper()
    level_label = f"{level}:"
    padded_level = f"{level_label:<{LEVEL_WIDTH}}"

    component = event_dict.pop("component", event_dict.pop("service", "APP")).upper()
    message = event_dict.pop("event", "")

    extras = " ".join(f"{key}={value}" for key, value in event_dict.items())
    if extras:
        return f"{padded_level}[{component}] {message} {extras}".rstrip()
    return f"{padded_level}[{component}] {message}".rstrip()


def configure_logging():
    """Configure structured logging for the application."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, settings.log_level.upper()))
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(processor=_render_event, fmt="%(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    verbose_loggers = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "uvicorn.asgi",
        "apscheduler",
    )

    for name in verbose_loggers:
        extra_logger = logging.getLogger(name)
        extra_logger.handlers = []
        extra_logger.propagate = True


# Configure on import so early loggers use the proper formatter
configure_logging()

# Global logger instance
logger = structlog.get_logger("app").bind(component="APP")
