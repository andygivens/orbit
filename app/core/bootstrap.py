"""Bootstrap helpers for default admin accounts, provider types, and sync defaults."""

import hashlib
import json
import secrets
from typing import Any, Dict, List

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..core.logging import logger
from ..core.settings import settings
from ..domain.models import (
    OAuthClient,
    Provider,
    ProviderType,
    ProviderTypeEnum,
    User,
)
from ..services.provider_config_validator import ProviderConfigValidator
from ..services.user_service import UserService

UI_CLIENT_ID = "orbit_ui"


def ensure_schema_updates(db: Session) -> None:
    """Apply lightweight schema updates that don't require migrations."""
    inspector = inspect(db.bind)

    # Add subject column to oauth_tokens if missing
    columns = {column["name"] for column in inspector.get_columns("oauth_tokens")}
    if "subject" not in columns:
        db.execute(text("ALTER TABLE oauth_tokens ADD COLUMN subject TEXT"))
        logger.info("Added oauth_tokens.subject column")

    # Add sync_id/details columns to sync_runs for new sync architecture
    sync_run_columns = {column["name"] for column in inspector.get_columns("sync_runs")}
    if "sync_id" not in sync_run_columns:
        db.execute(text("ALTER TABLE sync_runs ADD COLUMN sync_id TEXT"))
        logger.info("Added sync_runs.sync_id column")
    if "details" not in sync_run_columns:
        db.execute(text("ALTER TABLE sync_runs ADD COLUMN details TEXT"))
        logger.info("Added sync_runs.details column")

    # Add provider_id to sync_cursors for multi-provider support
    sync_cursor_columns = {
        column["name"]
        for column in inspector.get_columns("sync_cursors")
    }
    if "provider_id" not in sync_cursor_columns:
        db.execute(text("ALTER TABLE sync_cursors ADD COLUMN provider_id TEXT"))
        logger.info("Added sync_cursors.provider_id column")

    # Ensure providers table has type_id for FK to provider_types
    try:
        provider_columns = {
            column["name"]
            for column in inspector.get_columns("providers")
        }
    except Exception:
        provider_columns = set()

    if provider_columns and "type_id" not in provider_columns:
        db.execute(text("ALTER TABLE providers ADD COLUMN type_id TEXT"))
        logger.info("Added providers.type_id column")
        if "type" in provider_columns:
            db.execute(
                text(
                    "UPDATE providers SET type_id = type "
                    "WHERE type_id IS NULL"
                )
            )
            logger.info("Backfilled providers.type_id from legacy type column")

    # Phase 1: add provider phase columns if missing
    for col in ["config_schema_version", "config_fingerprint"]:
        if provider_columns and col not in provider_columns:
            try:
                db.execute(text(f"ALTER TABLE providers ADD COLUMN {col} TEXT"))
                logger.info("Added providers.%s column", col)
            except Exception as e:
                logger.warning("Could not add providers.%s column", col, error=str(e))

    # Phase 1: extend provider_types columns
    try:
        provider_type_columns = {
            c["name"] for c in inspector.get_columns("provider_types")
        }
    except Exception:
        provider_type_columns = set()
    new_pt_cols = [
        ("adapter_locator", "TEXT"),
        ("adapter_version", "TEXT"),
        ("sdk_min", "TEXT"),
        ("sdk_max", "TEXT"),
        ("capabilities", "JSON"),
        ("config_schema_hash", "TEXT"),
    ]
    for name, sqltype in new_pt_cols:
        if provider_type_columns and name not in provider_type_columns:
            try:
                db.execute(
                    text(
                        f"ALTER TABLE provider_types ADD COLUMN {name} {sqltype}"
                    )
                )
                logger.info("Added provider_types.%s column", name)
            except Exception as e:
                logger.warning(
                    "Could not add provider_types.%s column", name, error=str(e)
                )

    # Phase 1: create secrets + secret_versions tables if not exist
    existing_tables = set(inspector.get_table_names())
    if "secrets" not in existing_tables:
        db.execute(
            text(
                """
                CREATE TABLE secrets (
                  id TEXT PRIMARY KEY,
                  alias TEXT UNIQUE NOT NULL,
                  owner_type TEXT NOT NULL,
                  owner_id TEXT,
                  tenant_id TEXT,
                  purpose TEXT,
                  latest_version_id TEXT,
                  created_by TEXT,
                  created_at TIMESTAMP,
                  updated_at TIMESTAMP
                )
                """
            )
        )
        logger.info("Created secrets table")
    if "secret_versions" not in existing_tables:
        db.execute(
            text(
                """
                CREATE TABLE secret_versions (
                  id TEXT PRIMARY KEY,
                  secret_id TEXT NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
                  version INTEGER NOT NULL,
                  key_id TEXT,
                  aead_alg TEXT,
                  wrapped_dek TEXT,
                  nonce TEXT,
                  ciphertext TEXT,
                  associated_data TEXT,
                  checksum TEXT,
                  created_at TIMESTAMP,
                  rotated_by TEXT,
                  is_revoked BOOLEAN DEFAULT 0,
                  UNIQUE(secret_id, version)
                )
                """
            )
        )
        logger.info("Created secret_versions table")

    # Remove legacy custom CalDAV URL overrides for Apple providers
    try:
        apple_providers = (
            db.query(Provider)
            .filter(Provider.type_id == ProviderTypeEnum.APPLE_CALDAV.value)
            .all()
        )
    except Exception as exc:  # pragma: no cover - best effort cleanup
        logger.warning(
            "Could not inspect Apple providers for caldav_url cleanup",
            error=str(exc),
        )
    else:
        cleaned = 0
        for provider in apple_providers:
            config = provider.config or {}
            if not isinstance(config, dict):
                continue
            if "caldav_url" not in config:
                continue
            config.pop("caldav_url", None)
            provider.config = config
            provider.config_fingerprint = None
            cleaned += 1
        if cleaned:
            db.flush()
            logger.info(
                "Removed legacy Apple CalDAV URL overrides",
                providers=cleaned,
            )


def ensure_provider_types(db: Session) -> None:
    """Seed base provider types and config schema definitions."""
    existing_ids = {
        provider_type.id
        for provider_type in db.query(ProviderType).all()
    }

    definitions = _provider_type_definitions()

    created_count = 0
    for definition in definitions:
        if definition["id"] in existing_ids:
            continue
        db.add(
            ProviderType(
                id=definition["id"],
                label=definition["label"],
                description=definition["description"],
                config_schema=definition["config_schema"],
                adapter_locator=definition["adapter_locator"],
                adapter_version=definition["adapter_version"],
                sdk_min=definition.get("sdk_min"),
                sdk_max=definition.get("sdk_max"),
                capabilities=definition.get("capabilities"),
                config_schema_hash=definition.get("config_schema_hash"),
            )
        )
        created_count += 1

    if created_count:
        logger.info("Seeded provider types", created=created_count)

    # Backfill new metadata columns for all provider types (Phase 1)
    backfill_provider_type_metadata(db)


def backfill_provider_type_metadata(db: Session) -> None:
    """Populate adapter metadata, capabilities, and schema hash.

    Idempotent: updates only missing/null fields.
    """
    metadata_map = {
        definition["id"]: definition
        for definition in _provider_type_definitions()
    }
    types = db.query(ProviderType).all()
    any_updates = False
    for pt in types:
        updated = False
        defaults = metadata_map.get(pt.id, {})

        for field in ("adapter_locator", "adapter_version", "sdk_min", "sdk_max"):
            desired = defaults.get(field)
            if desired and getattr(pt, field, None) != desired:
                setattr(pt, field, desired)
                updated = True

        desired_schema = defaults.get("config_schema")
        if desired_schema and (pt.config_schema or {}) != desired_schema:
            pt.config_schema = json.loads(json.dumps(desired_schema))
            updated = True

        if (
            defaults.get("capabilities") is not None
            and pt.capabilities != defaults["capabilities"]
        ):
            pt.capabilities = defaults["capabilities"]
            updated = True

        desired_hash = defaults.get("config_schema_hash") or _schema_hash(
            pt.config_schema or {}
        )
        if pt.config_schema_hash != desired_hash:
            pt.config_schema_hash = desired_hash
            updated = True

        if updated:
            logger.info("Backfilled provider type metadata", type_id=pt.id)
            any_updates = True

    if any_updates:
        db.flush()


def _provider_type_definitions() -> List[Dict[str, Any]]:
    base: List[Dict[str, Any]] = [
        {
            "id": ProviderTypeEnum.APPLE_CALDAV.value,
            "label": "Apple iCloud CalDAV",
            "description": "Apple iCloud calendar via CalDAV",
            "adapter_locator": "app.providers.apple_caldav:AppleCalDAVAdapter",
            "adapter_version": "1.0.0",
            "sdk_min": "1.0.0",
            "sdk_max": None,
            "capabilities": [
                "read_events",
                "create_events",
                "update_events",
                "delete_events",
            ],
            "config_schema": {
                "fields": [
                    {
                        "name": "username",
                        "label": "Apple ID",
                        "type": "string",
                        "secret": False,
                    },
                    {
                        "name": "app_password",
                        "label": "App specific password",
                        "type": "secret",
                        "secret": True,
                    },
                    {
                        "name": "calendar_name",
                        "label": "Calendar Name",
                        "type": "string",
                        "secret": False,
                    },
                ]
            },
        },
        {
            "id": ProviderTypeEnum.SKYLIGHT.value,
            "label": "Skylight Frame",
            "description": "Skylight digital frame calendar API",
            "adapter_locator": "app.providers.skylight:SkylightAdapter",
            "adapter_version": "1.0.0",
            "sdk_min": "1.0.0",
            "sdk_max": None,
            "capabilities": [
                "read_events",
                "create_events",
                "update_events",
                "delete_events",
            ],
            "config_schema": {
                "fields": [
                    {
                        "name": "email",
                        "label": "Email",
                        "type": "string",
                        "secret": False,
                    },
                    {
                        "name": "password",
                        "label": "Password",
                        "type": "secret",
                        "secret": True,
                    },
                    {
                        "name": "frame_name",
                        "label": "Frame Name",
                        "type": "string",
                        "secret": False,
                    },
                    {
                        "name": "category_name",
                        "label": "Category Name",
                        "type": "string",
                        "secret": False,
                    },
                    {
                        "name": "base_url",
                        "label": "API Base URL",
                        "type": "string",
                        "secret": False,
                        "optional": True,
                    },
                ]
            },
        },
        {
            "id": ProviderTypeEnum.PUBLIC_CALDAV.value,
            "label": "Public CalDAV",
            "description": "Generic CalDAV endpoint (read/write configurable)",
            "adapter_locator": "app.providers.apple_caldav:AppleCalDAVAdapter",
            "adapter_version": "1.0.0",
            "sdk_min": "1.0.0",
            "sdk_max": None,
            "capabilities": [
                "read_events",
                "create_events",
                "update_events",
                "delete_events",
            ],
            "config_schema": {
                "fields": [
                    {
                        "name": "base_url",
                        "label": "CalDAV URL",
                        "type": "string",
                        "secret": False,
                    },
                    {
                        "name": "username",
                        "label": "Username",
                        "type": "string",
                        "secret": False,
                    },
                    {
                        "name": "password",
                        "label": "Password",
                        "type": "secret",
                        "secret": True,
                    },
                    {
                        "name": "calendar_path",
                        "label": "Calendar Path",
                        "type": "string",
                        "secret": False,
                    },
                ]
            },
        },
    ]

    definitions: List[Dict[str, Any]] = []
    for item in base:
        schema_copy = json.loads(json.dumps(item["config_schema"]))
        definition = {
            **item,
            "config_schema": schema_copy,
            "config_schema_hash": _schema_hash(schema_copy),
        }
        definitions.append(definition)

    return definitions


def _schema_hash(schema: Dict[str, Any]) -> str:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def deprecated_env_bootstrap_notice() -> None:
    """Log a notice if deprecated credential env vars are still set.

    This replaces the old ensure_default_providers_and_sync which created
    providers from env.
    Providers are now managed via API/UI and persisted in the database.
    """
    import os

    found = [v for v in settings._deprecated_env_vars if os.getenv(v)]
    if found:
        logger.warning(
            "Deprecated provider credential env vars detected (ignored)",
            vars=found,
        )


def ensure_default_admin(db: Session) -> str:
    """Ensure a default admin user exists. Returns password if created."""
    existing_admin = (
        db.query(User)
        .filter(User.is_superuser == True)  # noqa: E712
        .first()
    )
    if existing_admin:
        return ""

    user_service = UserService(db)
    password = user_service.generate_password()
    user_service.create_user("admin", password, is_superuser=True)

    credentials_box = (
        "\n" + "=" * 64 + "\n"
        + "||        ORBIT ADMIN DEFAULT CREDENTIALS GENERATED        ||\n"
        + "||                  username: admin                        ||\n"
        + f"||                  password: {password:<30}||\n"
        + "||   Rotate this password immediately after first login!   ||\n"
        + "=" * 64
    )

    logger.warning(credentials_box, component="bootstrap")
    return password


def ensure_ui_oauth_client(db: Session) -> None:
    """Ensure an OAuth client exists for the first-party UI."""
    client = (
        db.query(OAuthClient)
        .filter(OAuthClient.client_id == UI_CLIENT_ID)
        .first()
    )
    required_scopes = {"read:events", "write:events", "read:config", "write:config"}

    if client:
        existing_scopes = {scope.strip() for scope in client.scopes.split(",") if scope}
        if not required_scopes.issubset(existing_scopes):
            updated_scopes = sorted(existing_scopes.union(required_scopes))
            client.scopes = ",".join(updated_scopes)
            logger.info(
                "UI OAuth client scopes updated",
                client_id=UI_CLIENT_ID,
                scopes=client.scopes,
            )
        return

    secret_plain = secrets.token_urlsafe(24)
    hashed_secret = hashlib.sha256(secret_plain.encode()).hexdigest()
    client = OAuthClient(
        client_id=UI_CLIENT_ID,
        client_secret=hashed_secret,
        name="Orbit Admin UI",
        description="First-party UI login",
        scopes=",".join(sorted(required_scopes)),
        is_active=True,
    )
    db.add(client)
    logger.warning(
        "UI OAuth client provisioned",
        client_id=UI_CLIENT_ID,
        client_secret=secret_plain,
        note="Store securely; optional for public UI flows",
    )


def bootstrap_defaults(db: Session) -> None:
    ensure_schema_updates(db)
    ensure_provider_types(db)
    # Legacy env-based provider bootstrap removed; log notice if vars still present
    deprecated_env_bootstrap_notice()
    ensure_default_admin(db)
    ensure_ui_oauth_client(db)
    backfill_provider_fingerprints(db)


def backfill_provider_fingerprints(db: Session) -> None:
    """Compute and persist config fingerprints for existing providers missing them.

    Idempotent: only touches rows where config_fingerprint is NULL or empty.
    Uses the Phase 2 ProviderConfigValidator to ensure the sanitized config is canonical
    before hashing. Errors are logged and skipped to avoid blocking startup.
    """
    providers = (
        db.query(Provider)
        .filter(
            (Provider.config_fingerprint.is_(None))
            | (Provider.config_fingerprint == "")
        )
        .all()
    )
    if not providers:
        return
    validator = ProviderConfigValidator(db)
    updated = 0
    for provider in providers:
        try:
            # Reuse existing config; validator returns fingerprint + schema version
            result = validator.validate(provider.type_id, provider.config or {})
            provider.config = result.sanitized_config
            provider.config_fingerprint = result.fingerprint
            if not provider.config_schema_version:
                provider.config_schema_version = result.schema_version
            db.add(provider)
            updated += 1
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                "Failed to backfill provider fingerprint",
                provider_id=provider.id,
                error=str(e),
            )
    if updated:
        db.flush()
        logger.info("Backfilled provider fingerprints", updated=updated)
