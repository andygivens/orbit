"""
OAuth service for managing OAuth clients and tokens.
Handles OAuth 2.0 Client Credentials flow for external service authentication.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..core.logging import logger
from ..domain.models import OAuthAuthCode, OAuthClient, OAuthToken


class OAuthService:
    def __init__(self, db: Session):
        self.db = db
        self.logger = logger.bind(component="oauth")

    def create_client(self, name: str, description: str = "", scopes: str = "read:events,write:events") -> OAuthClient:
        """Create a new OAuth client"""
        try:
            # Generate client credentials
            client_id = f"orbit_{secrets.token_urlsafe(16)}"
            client_secret = secrets.token_urlsafe(32)

            client = OAuthClient(
                client_id=client_id,
                client_secret=self._hash_secret(client_secret),
                name=name,
                description=description,
                scopes=scopes
            )

            self.db.add(client)
            self.db.commit()

            self.logger.info("Created OAuth client", client_id=client_id, name=name)

            # Return client with unhashed secret (only time it's available)
            client_dict = client.to_dict()
            client_dict["client_secret"] = client_secret  # Unhashed for initial setup
            return client_dict

        except Exception as e:
            self.db.rollback()
            self.logger.error("Failed to create OAuth client", error=str(e))
            raise

    def authenticate_client(self, client_id: str, client_secret: str) -> Optional[OAuthClient]:
        """Authenticate OAuth client credentials"""
        try:
            client = self.db.query(OAuthClient).filter(
                OAuthClient.client_id == client_id,
                OAuthClient.is_active
            ).first()

            if not client:
                self.logger.warning("OAuth client not found", client_id=client_id)
                return None

            # Verify client secret
            if not self._verify_secret(client_secret, client.client_secret):
                self.logger.warning("Invalid OAuth client secret", client_id=client_id)
                return None

            self.logger.info("OAuth client authenticated", client_id=client_id)
            return client

        except Exception as e:
            self.logger.error("OAuth client authentication failed", error=str(e))
            return None

    def create_access_token(
        self,
        client: OAuthClient,
        scopes: Optional[str] = None,
        expires_in: int = 86400,
        include_refresh: bool = True,
        subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an access token for an authenticated client

        Args:
            client: Authenticated OAuth client
            scopes: Token scopes (defaults to client scopes)
            expires_in: Access token lifetime in seconds (default 24h for MCP)
            include_refresh: Whether to include refresh token (for MCP compatibility)
        """
        try:
            # Use client scopes if none specified
            if not scopes:
                scopes = client.scopes

            # Generate access token
            access_token = secrets.token_urlsafe(32)
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

            subject_str = None
            if subject is not None:
                subject_str = str(subject)

            # Generate refresh token if requested (and offline_access scope is present)
            refresh_token = None
            refresh_expires_at = None
            scope_list = scopes.split(",") if scopes else []

            if include_refresh or "offline_access" in scope_list:
                refresh_token = secrets.token_urlsafe(32)
                # Refresh tokens last 30 days for MCP clients
                refresh_expires_at = datetime.utcnow() + timedelta(days=30)

            # Clean up expired tokens for this client
            self._cleanup_expired_tokens(client.client_id)

            # Create token record
            token = OAuthToken(
                access_token=access_token,
                client_id=client.client_id,
                scopes=scopes,
                expires_at=expires_at,
                refresh_token=refresh_token,
                refresh_expires_at=refresh_expires_at,
                subject=subject_str,
            )

            self.db.add(token)
            self.db.commit()

            self.logger.info("Created OAuth access token",
                           client_id=client.client_id,
                           expires_in=expires_in,
                           has_refresh=refresh_token is not None)

            result = {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "scope": scopes
            }

            if refresh_token:
                result["refresh_token"] = refresh_token

            if subject_str:
                result["subject"] = subject_str

            return result

        except Exception as e:
            self.db.rollback()
            self.logger.error("Failed to create access token", error=str(e))
            raise

    def create_auth_code(self, client: OAuthClient, redirect_uri: str, scopes: str, code_challenge: str, code_challenge_method: str = "S256", expires_in: int = 300) -> str:
        """Create an authorization code for Authorization Code + PKCE flow"""
        try:
            code = secrets.token_urlsafe(32)
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            auth_code = OAuthAuthCode(
                code=code,
                client_id=client.client_id,
                redirect_uri=redirect_uri,
                scopes=scopes,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                expires_at=expires_at,
            )
            self.db.add(auth_code)
            self.db.commit()
            self.logger.info("Created OAuth auth code", client_id=client.client_id)
            return code
        except Exception as e:
            self.db.rollback()
            self.logger.error("Failed to create auth code", error=str(e))
            raise

    def exchange_auth_code(self, client: OAuthClient, code: str, redirect_uri: str, code_verifier: str, expires_in: int = 3600) -> Optional[Dict[str, Any]]:
        """Exchange an authorization code for an access token (PKCE)"""
        try:
            record = self.db.query(OAuthAuthCode).filter(
                OAuthAuthCode.code == code,
                OAuthAuthCode.client_id == client.client_id
            ).first()
            if not record:
                self.logger.warning("Auth code not found", client_id=client.client_id)
                return None
            if record.consumed or record.is_expired:
                self.logger.warning("Auth code invalid/expired", client_id=client.client_id)
                return None
            if record.redirect_uri != redirect_uri:
                self.logger.warning("Redirect URI mismatch", client_id=client.client_id)
                return None
            # Verify PKCE
            if record.code_challenge_method == "S256":
                calculated = hashlib.sha256(code_verifier.encode()).digest()
                import base64
                calculated_b64 = base64.urlsafe_b64encode(calculated).rstrip(b"=").decode()
                if calculated_b64 != record.code_challenge:
                    self.logger.warning("PKCE verification failed", client_id=client.client_id)
                    return None
            else:
                # plain
                if code_verifier != record.code_challenge:
                    self.logger.warning("PKCE (plain) verification failed", client_id=client.client_id)
                    return None
            # Mark code consumed
            record.consumed = True
            self.db.commit()
            # Create token with refresh token for authorization code flow
            return self.create_access_token(client, scopes=record.scopes, expires_in=86400, include_refresh=True)
        except Exception as e:
            self.db.rollback()
            self.logger.error("Failed to exchange auth code", error=str(e))
            return None

    def refresh_access_token(self, refresh_token_value: str) -> Optional[Dict[str, Any]]:
        """Refresh an access token using a refresh token"""
        try:
            # Find the token by refresh token
            token = self.db.query(OAuthToken).filter(
                OAuthToken.refresh_token == refresh_token_value
            ).first()

            if not token:
                self.logger.warning("Refresh token not found", token_prefix=refresh_token_value[:8])
                return None

            # Check if refresh token is expired
            if token.is_refresh_expired:
                self.logger.warning("Refresh token expired",
                                  client_id=token.client_id,
                                  token_prefix=refresh_token_value[:8])
                return None

            # Check if client is still active
            if not token.client.is_active:
                self.logger.warning("OAuth client deactivated",
                                  client_id=token.client_id)
                return None

            # Generate new access token
            new_access_token = secrets.token_urlsafe(32)
            new_expires_at = datetime.utcnow() + timedelta(hours=24)  # 24h for MCP

            # Optionally rotate refresh token (recommended for security)
            new_refresh_token = secrets.token_urlsafe(32)
            new_refresh_expires_at = datetime.utcnow() + timedelta(days=30)

            # Update the token record
            old_access_token = token.access_token
            token.access_token = new_access_token
            token.expires_at = new_expires_at
            token.refresh_token = new_refresh_token
            token.refresh_expires_at = new_refresh_expires_at
            token.refresh_token_rotated = True
            token.last_used = datetime.utcnow()

            self.db.commit()

            self.logger.info("Refreshed OAuth access token",
                           client_id=token.client_id,
                           old_token_prefix=old_access_token[:8],
                           new_token_prefix=new_access_token[:8])

            response = {
                "access_token": new_access_token,
                "token_type": "Bearer",
                "expires_in": 86400,  # 24 hours
                "refresh_token": new_refresh_token,
                "scope": token.scopes,
            }

            if token.subject:
                response["subject"] = token.subject

            return response

        except Exception as e:
            self.db.rollback()
            self.logger.error("Failed to refresh access token", error=str(e))
            return None
            return None

    def validate_access_token(self, access_token: str, required_scope: Optional[str] = None) -> Optional[OAuthToken]:
        """Validate an access token and optionally check scope"""
        try:
            token = self.db.query(OAuthToken).filter(
                OAuthToken.access_token == access_token
            ).first()

            if not token:
                self.logger.warning("OAuth token not found", token_prefix=access_token[:8])
                return None

            # Check if token is expired
            if token.is_expired:
                self.logger.warning("OAuth token expired",
                                  client_id=token.client_id,
                                  token_prefix=access_token[:8])
                return None

            # Check if client is still active
            if not token.client.is_active:
                self.logger.warning("OAuth client deactivated",
                                  client_id=token.client_id)
                return None

            # Check scope if required
            if required_scope and not token.has_scope(required_scope):
                self.logger.warning("OAuth token lacks required scope",
                                  client_id=token.client_id,
                                  required_scope=required_scope,
                                  token_scopes=token.scopes)
                return None

            # Update last used timestamp
            token.last_used = datetime.utcnow()
            self.db.commit()

            self.logger.debug("OAuth token validated",
                            client_id=token.client_id,
                            token_prefix=access_token[:8])

            return token

        except Exception as e:
            self.logger.error("OAuth token validation failed", error=str(e))
            return None

    def revoke_token(self, access_token: str) -> bool:
        """Revoke an access token"""
        try:
            token = self.db.query(OAuthToken).filter(
                OAuthToken.access_token == access_token
            ).first()

            if token:
                self.db.delete(token)
                self.db.commit()
                self.logger.info("OAuth token revoked",
                               client_id=token.client_id,
                               token_prefix=access_token[:8])
                return True

            return False

        except Exception as e:
            self.db.rollback()
            self.logger.error("Failed to revoke OAuth token", error=str(e))
            return False

    def list_clients(self) -> List[Dict[str, Any]]:
        """List all OAuth clients"""
        try:
            clients = self.db.query(OAuthClient).filter(
                OAuthClient.is_active
            ).all()

            return [client.to_dict() for client in clients]

        except Exception as e:
            self.logger.error("Failed to list OAuth clients", error=str(e))
            return []

    def deactivate_client(self, client_id: str) -> bool:
        """Deactivate an OAuth client and revoke all its tokens"""
        try:
            client = self.db.query(OAuthClient).filter(
                OAuthClient.client_id == client_id
            ).first()

            if not client:
                return False

            # Deactivate client
            client.is_active = False

            # Delete all tokens for this client
            self.db.query(OAuthToken).filter(
                OAuthToken.client_id == client_id
            ).delete()

            self.db.commit()

            self.logger.info("OAuth client deactivated", client_id=client_id)
            return True

        except Exception as e:
            self.db.rollback()
            self.logger.error("Failed to deactivate OAuth client", error=str(e))
            return False

    def _hash_secret(self, secret: str) -> str:
        """Hash a client secret"""
        return hashlib.sha256(secret.encode()).hexdigest()

    def _verify_secret(self, secret: str, hashed_secret: str) -> bool:
        """Verify a client secret against its hash"""
        return hashlib.sha256(secret.encode()).hexdigest() == hashed_secret

    def _cleanup_expired_tokens(self, client_id: str):
        """Clean up expired tokens for a client"""
        try:
            expired_count = self.db.query(OAuthToken).filter(
                OAuthToken.client_id == client_id,
                OAuthToken.expires_at < datetime.utcnow()
            ).delete()

            if expired_count > 0:
                self.logger.debug("Cleaned up expired tokens",
                                client_id=client_id,
                                count=expired_count)

        except Exception as e:
            self.logger.error("Failed to cleanup expired tokens", error=str(e))
