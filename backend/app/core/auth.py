"""Authentication boundary supporting development identity and Supabase JWT / Google OAuth integration."""

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_DEV_USER_EMAIL = "sairamesh189@gmail.com"
DEFAULT_DEV_USER_ID = uuid.UUID("1b1b001f-d53f-46b4-8f95-167f72873b6b")


def _base64url_decode(s: str) -> bytes:
    """Decode base64url string with proper padding."""
    rem = len(s) % 4
    if rem > 0:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s)


def verify_and_decode_supabase_jwt(token: str) -> dict[str, Any]:
    """Verify and decode a Supabase Auth JWT token (HS256).

    Extracts claims (sub, email, exp, role) and cryptographically verifies signature
    against SUPABASE_JWT_SECRET, SUPABASE_SERVICE_ROLE_KEY, or SUPABASE_SECRET_KEY.
    """
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed JWT: must contain header, payload, and signature.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    header_b64, payload_b64, signature_b64 = parts

    # 1. Decode payload
    try:
        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT payload encoding.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # 2. Check token expiration
    exp = payload.get("exp")
    if exp is not None and isinstance(exp, (int, float)):
        if time.time() > float(exp):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 3. Cryptographically verify signature if a Supabase secret key is configured
    jwt_secret = (
        settings.SUPABASE_JWT_SECRET
        or settings.SUPABASE_SECRET_KEY
        or settings.SUPABASE_SERVICE_ROLE_KEY
    )

    if jwt_secret:
        try:
            signing_input = f"{header_b64}.{payload_b64}".encode()
            expected_sig = hmac.new(
                jwt_secret.encode("utf-8"), signing_input, hashlib.sha256
            ).digest()
            actual_sig = _base64url_decode(signature_b64)
            if not hmac.compare_digest(expected_sig, actual_sig):
                logger.warning("Supabase JWT signature verification failed.")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token signature.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Error verifying JWT signature: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token cryptographic verification failed.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    return payload


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_dev_user_id: Annotated[str | None, Header(alias="X-Dev-User-Id")] = None,
    x_dev_user_email: Annotated[str | None, Header(alias="X-Dev-User-Email")] = None,
) -> User:
    """Resolve the authenticated user supporting Relay JWT (cookie or Bearer) and dev identity fallback.

    Security Boundary Rules:
    1. Check HttpOnly cookie 'access_token' or Authorization: Bearer <token>.
    2. Decode and cryptographically verify Relay JWT using JWT_SECRET_KEY.
    3. If invalid and Supabase keys exist, attempt Supabase JWT fallback.
    4. Development identity only functions when APP_ENV == 'development' AND ENABLE_DEV_AUTH is True.
    5. Any attempt to use development identity headers in production or staging without a valid token is rejected with 401.
    6. All operations are strictly scoped to the resolved User entity.
    """
    raw_token: str | None = None

    # 1. First priority: Check HttpOnly access_token cookie
    if request.cookies.get("access_token"):
        raw_token = request.cookies.get("access_token")

    # 2. Second priority: Authorization: Bearer <token>
    elif authorization and authorization.strip().lower().startswith("bearer "):
        raw_token = authorization.strip()[7:].strip()

    if raw_token:
        # A. Try decoding as Relay JWT
        try:
            payload = jwt.decode(
                raw_token,
                settings.JWT_SECRET_KEY,
                algorithms=["HS256"],
            )
            token_type = payload.get("type")
            if token_type != "access":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token type: expected 'access', got '{token_type}'.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            sub = payload.get("sub")
            if not sub:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token claims: missing 'sub' identifier.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            try:
                user_uuid = uuid.UUID(str(sub).strip())
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid user identifier in token.",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from exc

            result = await db.execute(select(User).where(User.id == user_uuid))
            user = result.scalar_one_or_none()

            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is inactive.",
                )

            return user

        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except HTTPException:
            raise
        except jwt.InvalidTokenError as err:
            # Fall back to Supabase JWT verification if legacy Supabase secret is configured
            jwt_secret = (
                settings.SUPABASE_JWT_SECRET
                or settings.SUPABASE_SECRET_KEY
                or settings.SUPABASE_SERVICE_ROLE_KEY
            )
            if not jwt_secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication token signature.",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from err

            payload = verify_and_decode_supabase_jwt(raw_token)
            sub = payload.get("sub")
            if not sub:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token claims: missing 'sub' identifier.",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from err

            try:
                user_uuid = uuid.UUID(str(sub).strip())
            except ValueError:
                user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"supabase.auth.{sub}")

            user_email = (
                payload.get("email") or f"user-{str(user_uuid)[:8]}@relay-user.internal"
            ).lower()

            result = await db.execute(select(User).where(User.id == user_uuid))
            user = result.scalar_one_or_none()

            if user is None:
                email_result = await db.execute(
                    select(User).where(User.email == user_email)
                )
                existing_email_user = email_result.scalar_one_or_none()
                if existing_email_user is not None:
                    user = existing_email_user
                else:
                    user = User(
                        id=user_uuid,
                        email=user_email,
                        is_active=True,
                    )
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)

            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is inactive.",
                ) from err

            return user

    # 3. Development identity fallback (only permitted when APP_ENV == 'development' AND ENABLE_DEV_AUTH is True)
    is_dev = settings.APP_ENV.lower() == "development"
    dev_auth_enabled = settings.ENABLE_DEV_AUTH

    if not is_dev or not dev_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Resolve identity in development mode
    dev_id: uuid.UUID = DEFAULT_DEV_USER_ID
    email: str = DEFAULT_DEV_USER_EMAIL

    if x_dev_user_id:
        try:
            dev_id = uuid.UUID(x_dev_user_id.strip())
        except ValueError:
            dev_id = uuid.uuid5(uuid.NAMESPACE_DNS, x_dev_user_id.strip())

    if x_dev_user_email:
        email = x_dev_user_email.strip().lower()
    elif x_dev_user_id and dev_id != DEFAULT_DEV_USER_ID:
        email = f"user-{str(dev_id)[:8]}@gateway.local"

    # Query or auto-provision the development user in the database
    result = await db.execute(select(User).where(User.id == dev_id))
    user = result.scalar_one_or_none()

    if user is None:
        email_result = await db.execute(select(User).where(User.email == email))
        existing_email_user = email_result.scalar_one_or_none()
        if existing_email_user is not None:
            user = existing_email_user
        else:
            user = User(
                id=dev_id,
                email=email,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    return user
