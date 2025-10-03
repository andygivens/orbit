# Domain models for events, tasks, and provider mapping
import enum
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import ulid
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship, validates

Base = declarative_base()
# NOTE: SQLAlchemy 2.x declarative_base imported from sqlalchemy.orm.
# The Secret <-> SecretVersion relationship creates a FK cycle
# (latest_version_id -> secret_versions.id and secret_versions.secret_id ->
# secrets.id). This may trigger drop order warnings in tests when using
# metadata.drop_all(). If needed we can refactor by removing latest_version FK
# or adding use_alter=True on one side; for now we document and tolerate the
# warning.
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_ulid() -> str:
    return ulid.new().str


def serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    iso = value.isoformat()
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    return iso


class ProviderEnum(enum.Enum):
    APPLE = "apple"
    SKYLIGHT = "skylight"


class ProviderTypeEnum(enum.Enum):
    APPLE_CALDAV = "apple_caldav"
    SKYLIGHT = "skylight"
    PUBLIC_CALDAV = "public_caldav"
    MINIMAL = "minimal"  # dynamic adapter (lean phase)


class ProviderStatusEnum(enum.Enum):
    UNKNOWN = "unknown"
    ACTIVE = "active"
    DEGRADED = "degraded"
    ERROR = "error"
    DISABLED = "disabled"


class SyncDirectionEnum(enum.Enum):
    BIDIRECTIONAL = "bidirectional"
    ONE_WAY = "one_way"


class SyncEndpointRoleEnum(enum.Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    OUTBOUND_ONLY = "outbound_only"


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=_generate_ulid)
    title = Column(String, nullable=False)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    location = Column(Text)
    notes = Column(Text)
    content_hash = Column(String, nullable=False)
    tombstoned = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    provider_mappings = relationship(
        "ProviderMapping",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_events_start_at", "start_at"),
        Index("ix_events_updated_at", "updated_at"),
        Index("ix_events_content_hash", "content_hash"),
    )

    def update_content_hash(self) -> None:
        """Update the content hash based on event data."""
        try:
            content = "|".join(
                [
                    self.title or "",
                    self.start_at.isoformat() if self.start_at else "",
                    self.end_at.isoformat() if self.end_at else "",
                    self.location or "",
                    self.notes or "",
                ]
            )
            self.content_hash = hashlib.md5(content.encode()).hexdigest()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to generate content hash", error=str(exc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "start_at": serialize_datetime(self.start_at),
            "end_at": serialize_datetime(self.end_at),
            "location": self.location,
            "notes": self.notes,
            "tombstoned": self.tombstoned,
            "created_at": serialize_datetime(self.created_at),
            "updated_at": serialize_datetime(self.updated_at),
        }


class ProviderMapping(Base):
    __tablename__ = "provider_event_mappings"

    id = Column(String, primary_key=True, default=_generate_ulid)
    orbit_event_id = Column(String, ForeignKey("events.id"), nullable=False)
    provider_id = Column(String, ForeignKey("providers.id"), nullable=False)
    provider_type = Column(Enum(ProviderTypeEnum), nullable=False)
    provider_uid = Column(String, nullable=False)
    etag_or_version = Column(String)
    alternate_uids = Column(JSON, nullable=True, default=list)
    tombstoned = Column(Boolean, default=False)
    last_seen_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    event = relationship("Event", back_populates="provider_mappings")
    provider = relationship("Provider", back_populates="event_mappings")

    __table_args__ = (
        UniqueConstraint("provider_id", "provider_uid", name="uq_provider_uid"),
        Index("ix_provider_event_mappings_orbit_event_id", "orbit_event_id"),
        Index("ix_provider_event_mappings_last_seen_at", "last_seen_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "orbit_event_id": self.orbit_event_id,
            "provider_id": self.provider_id,
            "provider_type": self.provider_type.value if self.provider_type else None,
            "provider_uid": self.provider_uid,
            "etag_or_version": self.etag_or_version,
            "alternate_uids": list(self.alternate_uids or []),
            "last_seen_at": serialize_datetime(self.last_seen_at),
            "tombstoned": self.tombstoned,
            "created_at": serialize_datetime(self.created_at),
            "updated_at": serialize_datetime(self.updated_at),
        }


class ConfigItem(Base):
    __tablename__ = "config"

    key = Column(String, primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncCursor(Base):
    __tablename__ = "sync_cursors"

    provider = Column(Enum(ProviderEnum), primary_key=True)
    cursor_type = Column(String, primary_key=True)  # e.g., "last_sync", "etag"
    cursor_value = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Future multi-provider support
    provider_id = Column(String, ForeignKey("providers.id"))


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id = Column(String, primary_key=True, default=_generate_ulid)
    sync_id = Column(String, ForeignKey("syncs.id"))
    direction = Column(String, nullable=False)
    status = Column(String, nullable=False, default="running")
    started_at = Column(DateTime(timezone=True), default=_utcnow)
    completed_at = Column(DateTime(timezone=True))

    events_processed = Column(Integer, default=0)
    events_created = Column(Integer, default=0)
    events_updated = Column(Integer, default=0)
    events_deleted = Column(Integer, default=0)
    errors = Column(Integer, default=0)

    error_message = Column(Text)
    details = Column(JSON)

    sync = relationship("Sync", back_populates="runs", foreign_keys=[sync_id])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sync_id": self.sync_id,
            "direction": self.direction,
            "status": self.status,
            "started_at": serialize_datetime(self.started_at),
            "completed_at": serialize_datetime(self.completed_at),
            "events_processed": self.events_processed,
            "events_created": self.events_created,
            "events_updated": self.events_updated,
            "events_deleted": self.events_deleted,
            "errors": self.errors,
            "error_message": self.error_message,
            "details": self.details or {},
        }


class SyncEventFlow(Base):
    __tablename__ = "sync_event_flows"

    id = Column(String, primary_key=True, default=_generate_ulid)
    sync_id = Column(String, ForeignKey("syncs.id"), nullable=False)
    sync_run_id = Column(String, ForeignKey("sync_runs.id"), nullable=False)
    orbit_event_id = Column(String, ForeignKey("events.id"), nullable=False)
    source_provider_id = Column(String, nullable=True)
    target_provider_id = Column(String, nullable=True)
    direction = Column(String, nullable=True)
    occurred_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_sync_event_flows_sync_id", "sync_id"),
        Index("ix_sync_event_flows_orbit_event_id", "orbit_event_id"),
        Index("ix_sync_event_flows_occurred_at", "occurred_at"),
    )


class OperationRecord(Base):
    __tablename__ = "operations"

    id = Column(String, primary_key=True, default=_generate_ulid)
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")
    resource_type = Column(String)
    resource_id = Column(String)
    payload = Column(JSON)
    result = Column(JSON)
    error = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "payload": self.payload or {},
            "result": self.result or {},
            "error": self.error or {},
            "created_at": serialize_datetime(self.created_at),
            "started_at": serialize_datetime(self.started_at),
            "finished_at": serialize_datetime(self.finished_at),
        }



class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    client_id = Column(String, primary_key=True)
    client_secret = Column(String, nullable=False)
    name = Column(String, nullable=False)  # "ChatGPT", "Claude", "Mobile App", etc.
    description = Column(Text)
    scopes = Column(
        String,
        default="read:events,write:events",
    )  # Comma-separated scopes
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Relationships
    tokens = relationship(
        "OAuthToken",
        back_populates="client",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        """Convert client to dictionary representation"""
        return {
            "client_id": self.client_id,
            "name": self.name,
            "description": self.description,
            "scopes": self.scopes,  # Keep as string for API compatibility
            "created_at": serialize_datetime(self.created_at),
            "is_active": self.is_active
        }


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    access_token = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("oauth_clients.client_id"), nullable=False)
    subject = Column(String)  # Optional user id or external subject
    token_type = Column(String, default="Bearer")
    scopes = Column(String)  # Comma-separated scopes for this token
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime)

    # Refresh token support for MCP clients
    refresh_token = Column(String)  # Refresh token for long-lived sessions
    refresh_expires_at = Column(DateTime)  # Refresh token expiration
    # Track if refresh token was rotated
    refresh_token_rotated = Column(Boolean, default=False)

    # Relationships
    client = relationship("OAuthClient", back_populates="tokens")

    def has_scope(self, scope: str) -> bool:
        """Return True if the token contains the given scope."""
        if not scope or not self.scopes:
            return False
        scopes = {value.strip() for value in self.scopes.split(",") if value.strip()}
        return scope in scopes

    @property
    def is_expired(self) -> bool:
        """Check if token is expired"""
        return datetime.utcnow() > self.expires_at

    @property
    def is_refresh_expired(self) -> bool:
        """Check if refresh token is expired"""
        if not self.refresh_expires_at:
            return True
        return datetime.utcnow() > self.refresh_expires_at


class OAuthAuthCode(Base):
    __tablename__ = "oauth_auth_codes"

    code = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("oauth_clients.client_id"), nullable=False)
    redirect_uri = Column(String, nullable=False)
    scopes = Column(String, nullable=False)
    code_challenge = Column(String, nullable=False)
    code_challenge_method = Column(String, default="S256")
    consumed = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=False)

    client = relationship("OAuthClient")

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


class ProviderType(Base):
    __tablename__ = "provider_types"

    id = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    description = Column(Text)
    config_schema = Column(JSON, nullable=False, default=dict)
    adapter_locator = Column(String)  # module:Class path
    adapter_version = Column(String)
    sdk_min = Column(String)
    sdk_max = Column(String)
    capabilities = Column(JSON, default=list)  # list of strings
    config_schema_hash = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    providers = relationship("Provider", back_populates="type_rel")

    def to_dict(self, include_schema: bool = True) -> dict:
        payload = {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "created_at": serialize_datetime(self.created_at),
            "updated_at": serialize_datetime(self.updated_at),
            "adapter_locator": self.adapter_locator,
            "adapter_version": self.adapter_version,
            "sdk_min": self.sdk_min,
            "sdk_max": self.sdk_max,
            "capabilities": self.capabilities or [],
            "config_schema_hash": self.config_schema_hash,
        }
        if include_schema:
            payload["config_schema"] = self.config_schema or {"fields": []}
        return payload


class Provider(Base):
    __tablename__ = "providers"

    id = Column(String, primary_key=True, default=_generate_ulid)
    type = Column(Enum(ProviderTypeEnum), nullable=False)
    type_id = Column(String, ForeignKey("provider_types.id"), nullable=False)
    name = Column(String, nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    last_checked_at = Column(DateTime(timezone=True))
    status = Column(Enum(ProviderStatusEnum), default=ProviderStatusEnum.UNKNOWN)
    status_detail = Column(Text)
    # Phase 1 additions (nullable until backfilled)
    config_schema_version = Column(String)
    config_fingerprint = Column(String)

    type_rel = relationship("ProviderType", back_populates="providers")
    sync_endpoints = relationship("SyncEndpoint", back_populates="provider")
    event_mappings = relationship(
        "ProviderMapping",
        back_populates="provider",
        cascade="all, delete-orphan",
    )

    # Keep enum 'type' and raw string 'type_id' synchronized when either is set
    @validates("type")
    def _sync_type_enum(self, key, value):  # pragma: no cover - simple mapper
        if isinstance(value, str):
            value = ProviderTypeEnum(value)
        # Ensure type_id mirrors enum value
        self.type_id = value.value
        return value

    @validates("type_id")
    def _sync_type_id_str(self, key, value):  # pragma: no cover - simple mapper
        if isinstance(value, ProviderTypeEnum):
            value = value.value
        # If 'type' already set keep them aligned; avoid recursion via __dict__
        if value and "type" in self.__dict__:
            self.__dict__["type"] = ProviderTypeEnum(value)
        return value

    def to_dict(self, include_config: bool = True) -> dict:  # mirror pattern
        payload = {
            "id": self.id,
            "type": self.type.value if self.type else None,
            "type_id": self.type_id,
            "name": self.name,
            "enabled": self.enabled,
            "created_at": serialize_datetime(self.created_at),
            "updated_at": serialize_datetime(self.updated_at),
            "last_checked_at": serialize_datetime(self.last_checked_at),
            "status": (
                self.status.value if self.status else ProviderStatusEnum.UNKNOWN.value
            ),
            "status_detail": self.status_detail,
            "config_schema_version": self.config_schema_version,
            "config_fingerprint": self.config_fingerprint,
        }
        if include_config:
            payload["config"] = self.config or {}
        return payload


class Secret(Base):
    __tablename__ = "secrets"

    id = Column(String, primary_key=True, default=_generate_ulid)
    alias = Column(String, unique=True, nullable=False, index=True)
    owner_type = Column(String, nullable=False)
    owner_id = Column(String)
    tenant_id = Column(String)
    purpose = Column(String)
    latest_version_id = Column(String, ForeignKey("secret_versions.id"))
    created_by = Column(String)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    latest_version = relationship("SecretVersion", foreign_keys=[latest_version_id])
    versions = relationship(
        "SecretVersion",
        back_populates="secret",
        cascade="all, delete-orphan",
        foreign_keys="SecretVersion.secret_id",
    )


class SecretVersion(Base):
    __tablename__ = "secret_versions"

    id = Column(String, primary_key=True, default=_generate_ulid)
    secret_id = Column(
        String,
        ForeignKey("secrets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)
    key_id = Column(String)
    aead_alg = Column(String)
    wrapped_dek = Column(String)  # Placeholder (base64 / hex)
    nonce = Column(String)
    ciphertext = Column(String)
    associated_data = Column(String)
    checksum = Column(String)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    rotated_by = Column(String)
    is_revoked = Column(Boolean, default=False)

    secret = relationship("Secret", back_populates="versions", foreign_keys=[secret_id])

    __table_args__ = (
        UniqueConstraint(
            "secret_id", "version", name="uq_secret_versions_secret_version"
        ),
    )

    def to_dict(self, include_config: bool = False) -> dict:
        payload = {
            "id": self.id,
            "type": self.type.value if self.type else None,
            "type_id": self.type_id,
            "name": self.name,
            "enabled": self.enabled,
            "created_at": serialize_datetime(self.created_at),
            "updated_at": serialize_datetime(self.updated_at),
            "last_checked_at": (
                self.last_checked_at.isoformat() if self.last_checked_at else None
            ),
            "status": (
                self.status.value
                if self.status
                else ProviderStatusEnum.UNKNOWN.value
            ),
            "status_detail": self.status_detail,
        }
        if include_config:
            payload["config"] = self.config or {}
        return payload

    @validates("type")
    def _sync_type(self, key, value):
        if isinstance(value, str):
            value = ProviderTypeEnum(value)
        self.type_id = value.value
        return value

    @validates("type_id")
    def _sync_type_id(self, key, value):
        if isinstance(value, ProviderTypeEnum):
            value = value.value
        if value and "type" in self.__dict__:
            # keep Enum in sync without triggering validators
            self.__dict__["type"] = ProviderTypeEnum(value)
        return value


class Sync(Base):
    __tablename__ = "syncs"

    id = Column(String, primary_key=True, default=_generate_ulid)
    name = Column(String, nullable=False)
    direction = Column(Enum(SyncDirectionEnum), default=SyncDirectionEnum.BIDIRECTIONAL)
    interval_seconds = Column(Integer, default=180)
    window_days_past = Column(Integer, default=3)
    window_days_future = Column(Integer, default=14)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    endpoints = relationship(
        "SyncEndpoint",
        back_populates="sync",
        cascade="all, delete-orphan",
    )
    runs = relationship("SyncRun", back_populates="sync", cascade="all, delete-orphan")

    def to_dict(self, include_endpoints: bool = False) -> dict:
        payload = {
            "id": self.id,
            "name": self.name,
            "direction": self.direction.value,
            "interval_seconds": self.interval_seconds,
            "window_days_past": self.window_days_past,
            "window_days_future": self.window_days_future,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_endpoints:
            payload["endpoints"] = [endpoint.to_dict() for endpoint in self.endpoints]
        return payload


class SyncEndpoint(Base):
    __tablename__ = "sync_endpoints"
    __table_args__ = (
        UniqueConstraint("sync_id", "provider_id", name="uq_sync_provider"),
    )

    id = Column(String, primary_key=True, default=_generate_ulid)
    sync_id = Column(String, ForeignKey("syncs.id"), nullable=False)
    provider_id = Column(String, ForeignKey("providers.id"), nullable=False)
    role = Column(
        Enum(SyncEndpointRoleEnum),
        nullable=False,
        default=SyncEndpointRoleEnum.PRIMARY,
    )

    sync = relationship("Sync", back_populates="endpoints")
    provider = relationship("Provider", back_populates="sync_endpoints")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sync_id": self.sync_id,
            "provider_id": self.provider_id,
            "role": self.role.value,
        }


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    full_name = Column(String)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
