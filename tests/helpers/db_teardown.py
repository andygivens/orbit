"""Test helpers for database lifecycle.

Provides an explicit ordered teardown to avoid SQLAlchemy warnings about
cyclic foreign key dependencies (e.g. Secret <-> SecretVersion).
"""
import warnings

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SAWarning

from app.domain.models import Base


def drop_all_ordered(engine: Engine):
    """Drop tables in dependency order to silence cycle warnings.

    We introspect foreign key dependencies and perform a naive multi-pass
    drop attempting to remove leaves first. For the small schema this is
    sufficient and avoids SQLAlchemy emitting FK cycle drop warnings during
    in-memory test teardown.
    """
    inspector = inspect(engine)
    remaining = set(inspector.get_table_names())
    # Fallback: if anything remains after max passes, call metadata.drop_all
    with engine.begin() as conn:
        for _ in range(len(remaining) + 2):
            progressed = False
            for table in list(remaining):
                fks = inspector.get_foreign_keys(table)
                # Drop if all referenced tables already gone
                if all(fk['referred_table'] not in remaining for fk in fks):
                    conn.execute(text(f'DROP TABLE IF EXISTS {table}'))
                    remaining.remove(table)
                    progressed = True
            if not remaining or not progressed:
                break
    if remaining:
        # Safety net; suppress cycle warning which is documented
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Can't sort tables for DROP; an unresolvable foreign key dependency exists",
                category=SAWarning,
            )
            Base.metadata.drop_all(bind=engine)
