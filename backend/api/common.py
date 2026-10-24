"""Common serializer and formatting helpers for watchlistTracker (WT) API."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
import os
import uuid
from typing import Any, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from portfoliomaster.core.models import Instrument, Quote, QuoteStatus
from portfoliomaster.db.session import get_database_url

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


def get_jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    """Retrieve or initialize cached PyJWKClient for asymmetric signing keys."""
    global _JWKS_CLIENT
    clean_url = supabase_url.strip().rstrip("/")
    if _JWKS_CLIENT is None or getattr(_JWKS_CLIENT, "_supabase_url", None) != clean_url:
        jwks_url = f"{clean_url}/auth/v1/.well-known/jwks.json"
        _JWKS_CLIENT = jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
        setattr(_JWKS_CLIENT, "_supabase_url", clean_url)
    return _JWKS_CLIENT


def _get_jwt_secret() -> str:
    """Retrieve Supabase JWT secret from environment or fail closed."""
    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if secret:
        return secret

    is_prod = (
        os.environ.get("ENVIRONMENT", "").lower() in ("production", "prod")
        or os.environ.get("RENDER", "").lower() == "true"
        or os.environ.get("NODE_ENV", "").lower() == "production"
    )
    if is_prod:
        logger.error("[Auth] SUPABASE_JWT_SECRET is required in production for HS256 tokens but missing.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication configuration error: SUPABASE_JWT_SECRET not set.",
        )

    # In local testing and development only, provide a deterministic test secret
    test_secret = os.environ.get("TEST_JWT_SECRET") or os.environ.get("DEV_JWT_SECRET")
    if test_secret:
        return test_secret

    return "test-supabase-jwt-secret-for-testing-purposes-only-32b"


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: malformed token header ({e}).",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    alg = unverified_header.get("alg")
    if not alg or alg.lower() == "none" or alg not in ("HS256", "RS256", "ES256"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: unsupported or prohibited token algorithm '{alg}'.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Unsupported algorithm"'},
        )

    raw_supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    clean_supabase_url = raw_supabase_url.rstrip("/") if raw_supabase_url else None
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: malformed token ({e}).",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    except jwt.PyJWKClientError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: unable to verify key from JWKS ({e}).",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {e}.",
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

    role = payload.get("role", "authenticated")
    if role != "authenticated":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: unauthorized user role. service_role cannot access user-facing endpoints.",
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
    if val is None:
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _clean_str(val: object, default: str = "") -> str:
    if val is None:
        return default
    s = str(val).strip()
    return s if s and s.lower() != "nan" else default


def _clean_opt_str(val: object) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() != "nan" else None


def _instrument_to_dict(inst: Any) -> dict[str, object]:
    """Serialize Instrument dataclass, UserInstrument ORM row, or dictionary to standard JSON dict."""
    if inst is None:
        return {}

    if isinstance(inst, dict):
        inst_id = inst.get("id")
        user_ticker = inst.get("user_ticker", "")
        provider_symbol = inst.get("provider_symbol")
        exchange_raw = inst.get("exchange", "")
        currency = inst.get("currency", "USD")
        company_name = inst.get("company_name", "")
        analysis_date = inst.get("analysis_date")
        analysis_price = inst.get("analysis_reference_price")
        soy_date = inst.get("start_of_year_date")
        soy_price = inst.get("start_of_year_price")
        target_price = inst.get("target_price")
        comment = inst.get("comment", "")
        active = inst.get("active", True)
        created_at = inst.get("created_at")
        updated_at = inst.get("updated_at")
    else:
        inst_id = getattr(inst, "id", None)
        user_ticker = getattr(inst, "user_ticker", "")
        provider_symbol = getattr(inst, "provider_symbol", None)
        exchange_raw = getattr(inst, "exchange", "")
        currency = getattr(inst, "currency", "USD")
        company_name = getattr(inst, "company_name", "")
        analysis_date = getattr(inst, "analysis_date", None)
        analysis_price = getattr(inst, "analysis_reference_price", None)
        soy_date = getattr(inst, "start_of_year_date", None)
        soy_price = getattr(inst, "start_of_year_price", None)
        target_price = getattr(inst, "target_price", None)
        comment = getattr(inst, "comment", "") or ""
        active = getattr(inst, "active", True)
        created_at = getattr(inst, "created_at", None)
        updated_at = getattr(inst, "updated_at", None)

    id_val: object = str(inst_id) if isinstance(inst_id, uuid.UUID) else inst_id
    exchange_val = exchange_raw.value if hasattr(exchange_raw, "value") else str(exchange_raw or "")
    an_dt = analysis_date.isoformat() if hasattr(analysis_date, "isoformat") else (str(analysis_date) if analysis_date else None)
    soy_dt = soy_date.isoformat() if hasattr(soy_date, "isoformat") else (str(soy_date) if soy_date else None)

    res: dict[str, object] = {
        "id": id_val,
        "user_ticker": user_ticker,
        "provider_symbol": provider_symbol,
        "exchange": exchange_val,
        "currency": currency,
        "company_name": company_name,
        "analysis_date": an_dt,
        "analysis_reference_price": _to_float(analysis_price),
        "start_of_year_date": soy_dt,
        "start_of_year_price": _to_float(soy_price),
        "target_price": _to_float(target_price),
        "comment": comment,
        "active": bool(active),
    }

    if created_at is not None:
        res["created_at"] = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    if updated_at is not None:
        res["updated_at"] = updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at)

    return res


def _quote_to_dict(quote: Any) -> Optional[dict[str, object]]:
    """Serialize Quote dataclass, MarketQuote ORM row, or dictionary to standard JSON dict."""
    if quote is None:
        return None

    if isinstance(quote, dict):
        return quote

    quote_id = getattr(quote, "id", None)
    inst_id = getattr(quote, "instrument_id", None)
    price = getattr(quote, "price", None)
    prev_close = getattr(quote, "previous_close", None)
    q_ts = getattr(quote, "quote_timestamp", None)
    fetched_at = getattr(quote, "fetched_at", None) or getattr(quote, "last_valid_fetched_at", None)
    provider = getattr(quote, "provider", "Yahoo") or "Yahoo"
    status_raw = getattr(quote, "status", None)
    status_str = (
        status_raw.name
        if isinstance(status_raw, QuoteStatus)
        else str(status_raw) if status_raw else "UNAVAILABLE"
    )
    error_msg = getattr(quote, "error_message", None)

    return {
        "id": quote_id,
        "instrument_id": inst_id,
        "price": _to_float(price),
        "previous_close": _to_float(prev_close),
        "quote_timestamp": q_ts.isoformat() if hasattr(q_ts, "isoformat") else (str(q_ts) if q_ts else None),
        "fetched_at": fetched_at.isoformat() if hasattr(fetched_at, "isoformat") else (str(fetched_at) if fetched_at else None),
        "provider": provider,
        "status": status_str,
        "error_message": error_msg,
    }


def is_multi_tenant_db() -> bool:
    """Check if the configured database uses the multi-tenant schema (PostgreSQL or forced multi-tenant test)."""
    if os.environ.get("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "").lower() in ("true", "1", "yes"):
        return True
    url = get_database_url()
    return bool(url and not url.startswith("sqlite"))
