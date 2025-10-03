# Database configuration and session management
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.settings import settings
from ..domain.models import Base

# Create database engine
engine = create_engine(
    settings.database_url,
    connect_args=(
        {"check_same_thread": False}
        if "sqlite" in settings.database_url
        else {}
    ),
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_tables():
    """Create all database tables"""
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.error("Failed to create database tables", error=str(e))


@contextmanager
def get_db_session() -> Session:
    """Get a database session with automatic cleanup"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """Dependency for FastAPI to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
