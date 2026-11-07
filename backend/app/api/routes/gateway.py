"""OpenAI-compatible public gateway routes mounted at /v1."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gateway_auth import AuthenticatedGatewayContext, get_gateway_context
from app.db.session import get_db
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    OpenAIModelListResponse,
)
from app.services.chat_gateway import (
    ChatGatewayService,
    get_chat_gateway_service,
)
from app.services.model_resolver import (
    ModelResolverService,
    get_model_resolver_service,
)

gateway_router = APIRouter()


@gateway_router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    status_code=status.HTTP_200_OK,
    summary="Create chat completion (OpenAI compatible)",
)
async def create_chat_completion(
    request: ChatCompletionRequest,
    auth_ctx: Annotated[AuthenticatedGatewayContext, Depends(get_gateway_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    chat_service: Annotated[ChatGatewayService, Depends(get_chat_gateway_service)],
) -> Any:
    """OpenAI-compatible chat completion endpoint supporting non-streaming and Server-Sent Events streaming."""
    if request.stream:
        stream_generator = chat_service.stream_chat_completion(
            db=db,
            user=auth_ctx.user,
            key=auth_ctx.key,
            request=request,
        )
        return StreamingResponse(
            stream_generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return await chat_service.create_chat_completion(
        db=db,
        user=auth_ctx.user,
        key=auth_ctx.key,
        request=request,
    )


@gateway_router.get(
    "/models",
    response_model=OpenAIModelListResponse,
    status_code=status.HTTP_200_OK,
    summary="List models accessible to authenticated virtual key (OpenAI compatible)",
)
async def list_gateway_models(
    auth_ctx: Annotated[AuthenticatedGatewayContext, Depends(get_gateway_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    resolver_service: Annotated[
        ModelResolverService, Depends(get_model_resolver_service)
    ],
) -> OpenAIModelListResponse:
    """List all available gateway model offerings accessible through the virtual key owner's active credentials."""
    models = await resolver_service.list_user_models(db=db, user=auth_ctx.user)
    return OpenAIModelListResponse(object="list", data=models)
