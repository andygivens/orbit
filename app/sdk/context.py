from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ProviderContext:
    """Lightweight context for early internal use.

    Extend gradually (logger, metrics, http, etc.) as additional adapters need them.
    """
    request_id: str = "local"
    idempotency_key: Optional[str] = None
    logger: Any = None  # injected externally if desired

    def log(self, level: str, message: str, **fields):  # minimal helper
        if self.logger:
            self.logger.log(level, message, **fields)  # structlog style
        else:
            print(f"[{level}] {message} {fields if fields else ''}")
