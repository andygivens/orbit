"""Unit coverage for the current OAuthService implementation."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.domain.models import Base, OAuthClient, OAuthToken
from app.services.oauth_service import OAuthService
from tests.helpers.db_teardown import drop_all_ordered


@pytest.fixture(name="session")
def _session_fixture():
    """Provide an isolated in-memory database session for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    session: Session = session_local()
    try:
        yield session
    finally:
        session.close()
        # Use ordered drop to silence FK cycle warnings
        drop_all_ordered(engine)
        engine.dispose()


@pytest.fixture(name="service")
def _service(session: Session) -> OAuthService:
    return OAuthService(session)


def test_create_client_persists_and_returns_credentials(
    service: OAuthService,
    session: Session,
):
    payload = {
        "name": "Test App",
        "description": "Sample integration",
        "scopes": "read:events,write:events",
    }

    result = service.create_client(**payload)

    assert set(result.keys()) >= {"client_id", "client_secret", "name", "scopes"}
    assert result["name"] == payload["name"]
    assert result["scopes"] == payload["scopes"]

    stored = (
        session.query(OAuthClient)
        .filter_by(client_id=result["client_id"])
        .first()
    )
    assert stored is not None
    assert stored.name == payload["name"]
    # Secret is stored hashed
    assert stored.client_secret != result["client_secret"]


def test_authenticate_client_with_valid_secret(service: OAuthService, session: Session):
    record = service.create_client(name="Chat Integration")
    secret = record["client_secret"]

    client = service.authenticate_client(record["client_id"], secret)

    assert client is not None
    assert client.client_id == record["client_id"]


def test_authenticate_client_invalid_secret(service: OAuthService, session: Session):
    record = service.create_client(name="Automation Bot")

    assert service.authenticate_client(record["client_id"], "wrong-secret") is None


def test_create_access_token_records_token(service: OAuthService, session: Session):
    record = service.create_client(name="CLI")
    client = service.authenticate_client(record["client_id"], record["client_secret"])

    result = service.create_access_token(
        client,
        scopes="read:events",
        expires_in=3600,
        include_refresh=False,
    )

    assert result["token_type"] == "Bearer"
    assert result["scope"] == "read:events"
    token_row = (
        session.query(OAuthToken)
        .filter_by(access_token=result["access_token"])
        .first()
    )
    assert token_row is not None
    assert token_row.client_id == client.client_id


def test_create_access_token_coerces_subject_to_string(service: OAuthService, session: Session):
    record = service.create_client(name="CLI")
    client = service.authenticate_client(record["client_id"], record["client_secret"])

    result = service.create_access_token(
        client,
        scopes="read:events",
        expires_in=3600,
        include_refresh=False,
        subject=42,
    )

    assert result["subject"] == "42"
    stored = (
        session.query(OAuthToken)
        .filter_by(access_token=result["access_token"])
        .first()
    )
    assert stored is not None
    assert stored.subject == "42"


def test_refresh_access_token_rotates_tokens(service: OAuthService, session: Session):
    record = service.create_client(name="Desktop")
    client = service.authenticate_client(record["client_id"], record["client_secret"])
    initial = service.create_access_token(client, include_refresh=True)

    refreshed = service.refresh_access_token(initial["refresh_token"])

    assert refreshed is not None
    assert refreshed["access_token"] != initial["access_token"]
    # Database reflects rotation
    stored = (
        session.query(OAuthToken)
        .filter_by(access_token=refreshed["access_token"])
        .first()
    )
    assert stored is not None
    assert stored.refresh_token == refreshed["refresh_token"]


def test_revoke_token_marks_revoked(service: OAuthService, session: Session):
    record = service.create_client(name="Mobile")
    client = service.authenticate_client(record["client_id"], record["client_secret"])
    token = service.create_access_token(client)

    ok = service.revoke_token(token["access_token"])

    assert ok is True
    stored = (
        session.query(OAuthToken)
        .filter_by(access_token=token["access_token"])
        .first()
    )
    assert stored is None  # Token removed on revoke


def test_list_clients_returns_serialisable_dicts(
    service: OAuthService,
    session: Session,
):
    service.create_client(name="One")
    service.create_client(name="Two")

    clients = service.list_clients()

    assert isinstance(clients, list)
    assert len(clients) == 2
    assert {"client_id", "name", "scopes"} <= clients[0].keys()


def test_deactivate_client_disables_and_revokes_tokens(
    service: OAuthService,
    session: Session,
):
    record = service.create_client(name="Admin Portal")
    client = service.authenticate_client(record["client_id"], record["client_secret"])
    token = service.create_access_token(client)

    assert service.deactivate_client(record["client_id"]) is True

    session.refresh(client)
    assert client.is_active is False
    # Tokens for the client removed during deactivation
    remaining = (
        session.query(OAuthToken)
        .filter_by(access_token=token["access_token"])
        .count()
    )
    assert remaining == 0


def test_refresh_access_token_rejects_expired(service: OAuthService, session: Session):
    record = service.create_client(name="Integration")
    client = service.authenticate_client(record["client_id"], record["client_secret"])
    issued = service.create_access_token(client, include_refresh=True)

    token_row = (
        session.query(OAuthToken)
        .filter_by(access_token=issued["access_token"])
        .first()
    )
    assert token_row is not None
    token_row.refresh_expires_at = datetime.utcnow() - timedelta(seconds=1)
    session.commit()

    assert service.refresh_access_token(issued["refresh_token"]) is None
