class ProviderError(Exception):
    """Base adapter error for all provider/adapter issues."""


class ProviderAuthError(ProviderError):
    """Authentication / authorization failure talking to provider."""
    pass


class ProviderRateLimitError(ProviderError):
    """Provider throttling or quota exceeded."""
    pass


class ProviderNotFoundError(ProviderError):
    """Referenced provider resource not found remotely."""
    pass


class ProviderConflictError(ProviderError):
    """Conflict (version / ETag / state) while mutating provider resource."""
    pass


class ProviderUnavailableError(ProviderError):
    """Transient upstream outage / connectivity problem."""
    pass


# Backwards compatibility aliases (older simplified names expected by SDK).
# Expose as variables rather than class definitions to satisfy N818.
ProviderNotFound = ProviderNotFoundError  # pragma: no cover - alias
ProviderConflict = ProviderConflictError  # pragma: no cover - alias
ProviderUnavailable = ProviderUnavailableError  # pragma: no cover - alias
