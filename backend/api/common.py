"""Common serializer and formatting helpers for watchlistTracker (WT) API."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
import os
import re
import threading
import uuid
from typing import Any, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from portfoliomaster.core.models import QuoteStatus
from portfoliomaster.core.parsing import clean_opt_str, clean_str, safe_float
from portfoliomaster.db.ports import instrument_to_dict, quote_to_dict
from portfoliomaster.db.session import get_database_url, is_production

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Authenticated Supabase user principal derived strictly from verified JWT claims."""
    user_id: uuid.UUID
    email: Optional[str] = None
    role: str = "authenticated"
    claims: dict[str, Any] = field(default_factory=dict)


_JWKS_CLIENT: Optional[jwt.PyJWKClient] = None
_JWKS_CLIENT_LOCK = threading.Lock()


def get_jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    """Retrieve or initialize cached PyJWKClient for asymmetric signing keys (thread-safe)."""
    global _JWKS_CLIENT
    clean_url = supabase_url.strip().rstrip("/")
    client = _JWKS_CLIENT
    if client is None or getattr(client, "_supabase_url", None) != clean_url:
        with _JWKS_CLIENT_LOCK:
            client = _JWKS_CLIENT
            if client is None or getattr(client, "_supabase_url", None) != clean_url:
                jwks_url = f"{clean_url}/auth/v1/.well-known/jwks.json"
                client = jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
                setattr(client, "_supabase_url", clean_url)
                _JWKS_CLIENT = client
    return client


def _configured_jwt_secret() -> str | None:
    """Validate the configured HS256 key without including its value in errors."""
    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if os.environ.get("ENVIRONMENT") == "test" and not is_production():
        return secret or os.environ.get("TEST_JWT_SECRET") or None
    if not secret:
        return None

    normalized = secret.casefold().replace("_", "-")
    if (
        len(secret.encode("utf-8")) < 32
        or secret != secret.strip()
        or normalized.startswith((
            "test-", "dev-", "default-", "static-", "change-me", "changeme",
            "replace-me", "your-", "super-secret-jwt-token-",
        ))
        or re.fullmatch(r"(.{1,16})\1+", normalized)
    ):
        raise ValueError("SUPABASE_JWT_SECRET must be at least 32 bytes and must not be a default or placeholder.")
    return secret


def validate_auth_configuration() -> None:
    """Require an HS256 key or a Supabase project URL for JWKS verification."""
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    if _configured_jwt_secret() is None and not supabase_url:
        raise ValueError("Configure SUPABASE_JWT_SECRET for HS256 or SUPABASE_URL for asymmetric JWTs.")
    if is_production() and is_multi_tenant_db() and not supabase_url:
        raise ValueError("SUPABASE_URL is required in production multi-tenant mode to enforce JWT issuer validation.")


def _get_jwt_secret() -> str:
    """Fail closed before decoding an HS256 token if its key is unusable."""
    try:
        secret = _configured_jwt_secret()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error: invalid SUPABASE_JWT_SECRET.",
        ) from exc

    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error: SUPABASE_JWT_SECRET not set.",
        )
    return secret


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthenticatedUser:
    """FastAPI authentication dependency.
    
    Validates Supabase-signed JWT against either symmetric (HS256) secret or
    asymmetric (RS256/ES256) JWKS endpoint based on token algorithm and configuration.
    Strictly verifies signature, expiration, audience ('authenticated'), and issuer if configured.
    Derives user_id strictly from verified 'sub' claim.
    Rejects 'service_role' on user-facing routes, 'alg=none', and forged identities.
    Fails closed with HTTP 401 for missing, invalid, or expired credentials.
    """
    token: Optional[str] = None

    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
    elif request:
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth_header and auth_header.strip().startswith("Bearer "):
            token = auth_header.strip().split(" ", 1)[1].strip()
        elif "sb-access-token" in request.cookies:
            token = request.cookies.get("sb-access-token")
        elif "supabase-auth-token" in request.cookies:
            token = request.cookies.get("supabase-auth-token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing or invalid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Unverified header inspect to determine algorithm
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as e:
        logger.warning("[Auth] Malformed JWT header: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: malformed token header.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    alg = unverified_header.get("alg")
    if not alg or alg.lower() == "none" or alg not in ("HS256", "RS256", "ES256"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: unsupported or prohibited token algorithm.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Unsupported algorithm"'},
        )

    raw_supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    clean_supabase_url = raw_supabase_url.rstrip("/") if raw_supabase_url else None
    if is_production() and is_multi_tenant_db() and not clean_supabase_url:
        logger.error("[Auth] SUPABASE_URL is required in production multi-tenant mode.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error: SUPABASE_URL is required.",
        )
    expected_issuer = f"{clean_supabase_url}/auth/v1" if clean_supabase_url else None

    # 2. Strict cryptographic signature & claim verification
    try:
        if alg == "HS256":
            jwt_secret = _get_jwt_secret()
            decode_kwargs: dict[str, Any] = {
                "algorithms": ["HS256"],
                "audience": "authenticated",
                "options": {
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": bool(expected_issuer),
                },
            }
            if expected_issuer:
                decode_kwargs["issuer"] = expected_issuer
            payload = jwt.decode(token, jwt_secret, **decode_kwargs)

        else:
            # Asymmetric mode: RS256 or ES256
            if not clean_supabase_url:
                logger.error("[Auth] Asymmetric signing key presented but SUPABASE_URL is not set.")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Authentication configuration error: SUPABASE_URL required for asymmetric key verification.",
                )
            jwks_client = get_jwks_client(clean_supabase_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            decode_kwargs = {
                "algorithms": ["RS256", "ES256"],
                "audience": "authenticated",
                "options": {
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": bool(expected_issuer),
                },
            }
            if expected_issuer:
                decode_kwargs["issuer"] = expected_issuer
            payload = jwt.decode(token, signing_key.key, **decode_kwargs)

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: token has expired.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Token expired"'},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: invalid token audience.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Invalid audience"'},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: invalid token issuer.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Invalid issuer"'},
        )
    except jwt.InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: invalid token signature.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Invalid signature"'},
        )
    except jwt.DecodeError as e:
        logger.warning("[Auth] JWT decode failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: malformed token.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    except jwt.PyJWKClientError as e:
        logger.warning("[Auth] JWKS key verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: unable to verify signing key.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    except jwt.PyJWTError as e:
        logger.warning("[Auth] JWT verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: invalid token.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: token missing subject (sub) claim.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    try:
        user_uuid = uuid.UUID(str(sub))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: token subject is not a valid UUID.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    role = payload.get("role")
    if role != "authenticated":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: unauthorized user role. Only authenticated user tokens are permitted.",
        )

    return AuthenticatedUser(
        user_id=user_uuid,
        email=payload.get("email"),
        role=role,
        claims=payload,
    )


def get_current_user_id(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> uuid.UUID:
    """FastAPI dependency to resolve the verified tenant user UUID."""
    return current_user.user_id


def _to_float(val: object) -> Optional[float]:
    return safe_float(val)


def _clean_str(val: object, default: str = "") -> str:
    cleaned = clean_str(val)
    return cleaned if cleaned else default


def _clean_opt_str(val: object) -> Optional[str]:
    return clean_opt_str(val)


def _instrument_to_dict(inst: Any) -> dict[str, object]:
    """Serialize Instrument dataclass, UserInstrument ORM row, or dictionary to standard JSON dict."""
    return instrument_to_dict(inst)


def _quote_to_dict(quote: Any) -> Optional[dict[str, object]]:
    """Serialize Quote dataclass, MarketQuote ORM row, or dictionary to standard JSON dict."""
    return quote_to_dict(quote)


def is_multi_tenant_db() -> bool:
    """Check if the configured database uses the multi-tenant schema (PostgreSQL or forced multi-tenant test)."""
    if os.environ.get("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "").lower() in ("true", "1", "yes"):
        return True
    url = get_database_url()
    return bool(url and not url.startswith("sqlite"))
