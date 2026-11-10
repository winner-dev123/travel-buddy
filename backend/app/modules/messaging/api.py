"""``/v1/conversations``: direct conversations, messages, receipts, mute, clear, pins (BL-3.03)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.messaging.schemas import (
    ClearConversationRequest,
    ConversationOut,
    ConversationPage,
    EditMessageRequest,
    Kind,
    MessageList,
    MessageOut,
    MuteConversationRequest,
    OpenDirectConversationRequest,
    ReceiptState,
    SendMessageRequest,
    UpdateReceiptsRequest,
)
from app.modules.messaging.service import MessagingService

router = APIRouter(prefix="/v1/conversations", tags=["messaging"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
Emoji = Annotated[str, Path(min_length=1, max_length=64)]


def _service(request: Request) -> MessagingService:
    service: MessagingService = request.app.state.messaging_service
    return service


@router.get("", response_model=ConversationPage)
async def list_conversations(
    request: Request,
    principal: CurrentPrincipal,
    kind: Kind | None = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ConversationPage:
    return await _service(request).list_conversations(
        principal.user_id, kind=kind, cursor=cursor, limit=limit
    )


@router.post(
    "",
    response_model=ConversationOut,
    responses={201: {"model": ConversationOut}},
)
async def open_direct_conversation(
    body: OpenDirectConversationRequest, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    out, created = await _service(request).open_direct(principal, body)
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> ConversationOut:
    return await _service(request).get_conversation(principal.user_id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MessageList:
    return await _service(request).list_messages(
        principal.user_id,
        conversation_id,
        before_seq=before_seq,
        after_seq=after_seq,
        limit=limit,
    )


@router.post(
    "/{conversation_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageOut,
    openapi_extra=rate_limited("message"),
)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    # Deduplication is on client_message_id (DM-005); the header is required for consistency.
    del idempotency_key
    out, replayed = await _service(request).send(principal, conversation_id, body)
    return JSONResponse(
        out.model_dump(mode="json", exclude_none=False),
        status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        headers={"Idempotent-Replayed": "true"} if replayed else {},
    )


@router.patch(
    "/{conversation_id}/messages/{message_id}",
    response_model=MessageOut,
    openapi_extra=rate_limited("message"),
)
async def edit_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    body: EditMessageRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> MessageOut:
    return await _service(request).edit(principal.user_id, conversation_id, message_id, body.body)


@router.delete("/{conversation_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    reason_code: Annotated[str | None, Query(max_length=40)] = None,
) -> Response:
    del reason_code  # moderator removals arrive with group chat
    await _service(request).delete(principal.user_id, conversation_id, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{conversation_id}/messages/{message_id}/reactions/{emoji}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_reaction(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    emoji: Emoji,
    request: Request,
    principal: CurrentPrincipal,
) -> Response:
    await _service(request).react(principal.user_id, conversation_id, message_id, emoji, add=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{conversation_id}/messages/{message_id}/reactions/{emoji}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_reaction(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    emoji: Emoji,
    request: Request,
    principal: CurrentPrincipal,
) -> Response:
    await _service(request).react(principal.user_id, conversation_id, message_id, emoji, add=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/threads/{message_id}", response_model=MessageList)
async def list_thread_replies(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MessageList:
    return await _service(request).thread(
        principal.user_id, conversation_id, message_id, after_seq=after_seq, limit=limit
    )


@router.put("/{conversation_id}/receipts", response_model=ReceiptState)
async def update_receipts(
    conversation_id: uuid.UUID,
    body: UpdateReceiptsRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> ReceiptState:
    return await _service(request).update_receipts(principal.user_id, conversation_id, body)


@router.put("/{conversation_id}/mute", response_model=ConversationOut)
async def mute_conversation(
    conversation_id: uuid.UUID,
    body: MuteConversationRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> ConversationOut:
    return await _service(request).mute(principal.user_id, conversation_id, body)


@router.post("/{conversation_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
async def clear_conversation(
    conversation_id: uuid.UUID,
    body: ClearConversationRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> Response:
    await _service(request).clear(principal.user_id, conversation_id, body.through_seq)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/pins", response_model=MessageList)
async def list_pins(
    conversation_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> MessageList:
    return await _service(request).pins(principal.user_id, conversation_id)


@router.put("/{conversation_id}/pins/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def pin_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
) -> Response:
    await _service(request).pin(principal.user_id, conversation_id, message_id, on=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{conversation_id}/pins/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unpin_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
) -> Response:
    await _service(request).pin(principal.user_id, conversation_id, message_id, on=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
