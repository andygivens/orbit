from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import Base, Provider, ProviderType, ProviderTypeEnum
from app.providers.base import ProviderAdapter
from app.providers.registry import provider_registry
from app.services.provider_service import (
    ProviderService,
    ProviderValidationError,
)


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory_local = sessionmaker(bind=engine)

    @contextmanager
    def factory():
        session = session_factory_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return factory


def _seed_provider_type(session):
    pt = ProviderType(
        id=ProviderTypeEnum.APPLE_CALDAV.value,
        label="Apple CalDAV",
        description="Test Apple CalDAV",
        adapter_version="1.0.0",
        config_schema={
            "fields": [
                {"name": "username", "type": "string"},
                {"name": "password", "type": "secret", "secret": True},
            ]
        },
    )
    session.add(pt)
    session.flush()
    return pt


def _seed_json_schema_provider_type(session):
    pt = ProviderType(
        id=ProviderTypeEnum.PUBLIC_CALDAV.value,
        label="JSON Schema Type",
        description="Provider type defined with JSON Schema",
        adapter_version="2.0.0",
        config_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "username": {"type": "string", "title": "Operator"},
                "password": {"type": "string", "writeOnly": True},
                "enabled": {"type": "boolean"},
            },
            "required": ["username", "password"],
            "additionalProperties": False,
        },
    )
    session.add(pt)
    session.flush()
    return pt


def _fingerprint(config: dict) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def test_create_provider_stores_fingerprint_and_masks_secret():
    session_factory = _make_session_factory()
    with session_factory() as session:
        _seed_provider_type(session)
        service = ProviderService(session)

        result = service.create_provider(
            type_id=ProviderTypeEnum.APPLE_CALDAV.value,
            name="Primary Apple",
            config={"username": "alice", "password": "s3cr3t"},
        )

        # Response should mask secret
        assert result["config"]["password"] == "********"

        provider = session.query(Provider).filter(Provider.id == result["id"]).one()
        assert provider.config_fingerprint, "Fingerprint not stored"
        assert provider.config_schema_version == "1.0.0"

        expected_fp = _fingerprint({"username": "alice", "password": "s3cr3t"})
        assert provider.config_fingerprint == expected_fp


def test_create_provider_rejects_unknown_field():
    session_factory = _make_session_factory()
    with session_factory() as session:
        _seed_provider_type(session)
        service = ProviderService(session)

        with pytest.raises(ProviderValidationError):
            service.create_provider(
                type_id=ProviderTypeEnum.APPLE_CALDAV.value,
                name="Bad Provider",
                config={"username": "alice", "password": "pw", "extra": "nope"},
            )


def test_update_provider_masked_secret_preserves_value_and_fingerprint():
    session_factory = _make_session_factory()
    with session_factory() as session:
        _seed_provider_type(session)
        service = ProviderService(session)
        created = service.create_provider(
            type_id=ProviderTypeEnum.APPLE_CALDAV.value,
            name="Apple One",
            config={"username": "alice", "password": "pw1"},
        )
        provider_id = created["id"]

        provider = session.query(Provider).filter(Provider.id == provider_id).one()
        original_fp = provider.config_fingerprint

        # Update with masked password only
        updated = service.update_provider(
            provider_id,
            config={"username": "alice", "password": "********"},
        )
        provider = session.query(Provider).filter(Provider.id == provider_id).one()
        assert provider.config["password"] == "pw1"  # unchanged
        assert provider.config_fingerprint == original_fp
        assert updated["config"]["password"] == "********"


def test_update_provider_changed_secret_changes_fingerprint():
    session_factory = _make_session_factory()
    with session_factory() as session:
        _seed_provider_type(session)
        service = ProviderService(session)
        created = service.create_provider(
            type_id=ProviderTypeEnum.APPLE_CALDAV.value,
            name="Apple Two",
            config={"username": "alice", "password": "pw1"},
        )
        provider_id = created["id"]
        provider = session.query(Provider).filter(Provider.id == provider_id).one()
        original_fp = provider.config_fingerprint

        service.update_provider(
            provider_id,
            config={"username": "alice", "password": "pw2"},
        )
        provider = session.query(Provider).filter(Provider.id == provider_id).one()
        assert provider.config["password"] == "pw2"
        assert provider.config_fingerprint != original_fp


def test_json_schema_provider_masks_secret_and_validates():
    session_factory = _make_session_factory()
    with session_factory() as session:
        json_schema_type = _seed_json_schema_provider_type(session)
        service = ProviderService(session)

        created = service.create_provider(
            type_id=json_schema_type.id,
            name="Schema Provider",
            config={"username": "alice", "password": "pw", "enabled": True},
        )

        assert created["config"]["password"] == "********"

        # Updating with an unknown field should fail.
        with pytest.raises(ProviderValidationError):
            service.update_provider(
                created["id"],
                config={"username": "alice", "password": "********", "extra": "nope"},
            )

        # Toggle boolean and change secret to ensure type coercion preserved.
        updated = service.update_provider(
            created["id"],
            config={"username": "alice", "password": "pw2", "enabled": False},
        )

        assert updated["config"]["password"] == "********"
        provider = session.query(Provider).filter(Provider.id == created["id"]).one()
        assert provider.config["enabled"] is False
        assert provider.config["password"] == "pw2"


class _TimeoutAdapter(ProviderAdapter):
    async def initialize(self) -> None:  # pragma: no cover - intentional timeout simulation
        raise asyncio.TimeoutError()

    async def list_events(self, start: str, end: str):  # pragma: no cover - stubbed
        return []

    async def create_event(self, payload):  # pragma: no cover - stubbed
        return {}

    async def update_event(self, provider_uid: str, payload):  # pragma: no cover - stubbed
        return {}

    async def delete_event(self, provider_uid: str) -> None:  # pragma: no cover - stubbed
        return None


@pytest.mark.asyncio
async def test_test_provider_connection_includes_timeout_details():
    session_factory = _make_session_factory()
    with session_factory() as session:
        _seed_provider_type(session)
        service = ProviderService(session)
        created = service.create_provider(
            type_id=ProviderTypeEnum.APPLE_CALDAV.value,
            name="Timeout Adapter",
            config={"username": "alice", "password": "pw"},
        )

        provider_id = created["id"]

        provider_registry.register(
            ProviderTypeEnum.APPLE_CALDAV.value,
            lambda provider_id, config: _TimeoutAdapter(provider_id, config),
        )
        try:
            result = await service.test_provider_connection(provider_id)
        finally:
            provider_registry.factories.pop(ProviderTypeEnum.APPLE_CALDAV.value, None)

        assert result["status"] == "error"
        detail = result.get("status_detail") or ""
        assert detail.startswith("Connection failed:"), detail
        assert "TimeoutError" in detail
