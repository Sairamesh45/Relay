"""Gateway authentication dependency authenticating virtual API keys for public OpenAI-compatible endpoints."""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gateway_errors import openai_auth_error
from app.db.session import get_db
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.services.virtual_key_service import (
    ExpiredVirtualKeyError,
    InvalidVirtualKeyError,
    RevokedVirtualKeyError,
    VirtualKeyService,
    get_virtual_key_service,
)


class AuthenticatedGatewayContext:
    """Authentication context containing the active virtual key and associated user."""

    def __init__(self, key: VirtualAPIKey, user: User, raw_key: str) -> None:
        self.key = key
        self.user = user
        self.raw_key = raw_key


async def get_gateway_context(
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
    authorization: str | None = Header(None, description="Bearer <virtual_api_key>"),
) -> AuthenticatedGatewayContext:
    """Authenticate incoming gateway requests using Bearer virtual API keys.

    Strictly relies on virtual API keys; does not permit development headers.
    Returns AuthenticatedGatewayContext containing the verified key and owning user.
    """
    if not authorization:
        raise openai_auth_error(
            "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. 'Authorization: Bearer YOUR_KEY').",
            code="missing_api_key",
        )

    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise openai_auth_error(
            "Malformed Authorization header. Format must be 'Bearer <your_virtual_key>'.",
            code="invalid_api_key",
        )

    raw_token = parts[1].strip()
    if not raw_token:
        raise openai_auth_error(
            "Empty API key provided in Bearer header.",
            code="invalid_api_key",
        )

    try:
        key_record, user = await key_service.authenticate_key(db, raw_token)
        return AuthenticatedGatewayContext(key=key_record, user=user, raw_key=raw_token)
    except ExpiredVirtualKeyError as exc:
        raise openai_auth_error(exc.message, code="expired_api_key") from exc
    except RevokedVirtualKeyError as exc:
        raise openai_auth_error(exc.message, code="revoked_api_key") from exc
    except InvalidVirtualKeyError as exc:
        raise openai_auth_error(exc.message, code="invalid_api_key") from exc
    except Exception as exc:
        raise openai_auth_error(
            "API key authentication failed.", code="invalid_api_key"
        ) from exc
