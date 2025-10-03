"""Security utilities for password hashing and verification."""

from __future__ import annotations

import bcrypt


def get_password_hash(password: str) -> str:
    """Create a bcrypt hash for the supplied password."""
    if not isinstance(password, str):  # Defensive guard for unexpected input types
        raise TypeError("password must be a string")
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify the password using bcrypt's constant-time comparison."""
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (AttributeError, ValueError, TypeError):
        # Hash not recognized or inputs invalid
        return False
