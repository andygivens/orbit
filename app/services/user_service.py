"""User management and authentication service."""

import secrets
from typing import Optional

from sqlalchemy.orm import Session

from ..core.logging import logger
from ..core.security import get_password_hash, verify_password
from ..domain.models import User


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.logger = logger.bind(component="users")

    def get_by_username(self, username: str) -> Optional[User]:
        return self.db.query(User).filter(User.username == username).first()

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self.get_by_username(username)
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def create_user(
        self,
        username: str,
        password: str,
        *,
        full_name: Optional[str] = None,
        is_superuser: bool = False
    ) -> User:
        if self.get_by_username(username):
            raise ValueError("User already exists")
        user = User(
            username=username,
            hashed_password=get_password_hash(password),
            full_name=full_name,
            is_superuser=is_superuser,
            is_active=True
        )
        self.db.add(user)
        self.db.flush()
        self.logger.info("Created user", username=username, superuser=is_superuser)
        return user

    def set_password(self, user: User, password: str) -> None:
        user.hashed_password = get_password_hash(password)
        self.db.add(user)
        self.logger.info("Updated user password", username=user.username)

    @staticmethod
    def generate_password(length: int = 16) -> str:
        return secrets.token_urlsafe(length)
