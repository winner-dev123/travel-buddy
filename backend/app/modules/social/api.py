"""HTTP adapters for ``/v1/posts*`` and ``/v1/users/{userId}/posts``."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.i18n import parse_accept_language
from app.core.pagination import Page
from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.social.follows import FollowService
from app.modules.social.interactions import InteractionService
from app.modules.social.models import PostKind
from app.modules.social.public import CACHE_CONTROL, PublicPostService
from app.modules.social.schemas import (
    CommentOut,
    CreateCommentRequest,
    CreatePostRequest,
    FollowState,
    Post,
    ReactionOut,
    ReactionRequest,
    ReactionResult,
    ShareLink,
    ShareRequest,
    UpdateCommentRequest,
    UpdatePostRequest,
    UserSummary,
)
from app.modules.social.service import PostService

router = APIRouter(tags=["posts"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language", max_length=200)]


def _service(request: Request) -> PostService:
    service: PostService = request.app.state.post_service
    return service


@router.post("/v1/posts", status_code=status.HTTP_201_CREATED, response_model=Post)
async def create_post(
    body: CreatePostRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    post, replayed = await _service(request).create(
        principal,
        body,
        idempotency_key=idempotency_key,
        preferences=parse_accept_language(accept_language),
    )
    headers = {"Location": f"/v1/posts/{post.id}"}
    if replayed:
        headers["Idempotent-Replayed"] = "true"
    return JSONResponse(post.as_json(), status_code=status.HTTP_201_CREATED, headers=headers)


@router.get("/v1/posts/{post_id}", response_model=Post)
async def get_post(
    post_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    post = await _service(request).get(
        principal.user_id, post_id, preferences=parse_accept_language(accept_language)
    )
    return JSONResponse(post.as_json())


@router.patch("/v1/posts/{post_id}", response_model=Post)
async def update_post(
    post_id: uuid.UUID,
    body: UpdatePostRequest,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    post = await _service(request).update(
        principal, post_id, body, preferences=parse_accept_language(accept_language)
    )
    return JSONResponse(post.as_json())


@router.delete("/v1/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).delete(principal, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/users/{user_id}/posts", response_model=Page[Post], tags=["profiles"])
async def list_user_posts(
    user_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    page = await _service(request).list_by_author(
        principal.user_id,
        user_id,
        cursor=cursor,
        limit=limit,
        preferences=parse_accept_language(accept_language),
    )
    return JSONResponse(
        {
            "data": [p.as_json() for p in page.data],
            "page": page.page.model_dump(mode="json"),
        }
    )


# ─────────────────────────────── interactions (BL-1.11) ───────────────────────────────

Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _interactions(request: Request) -> InteractionService:
    service: InteractionService = request.app.state.interaction_service
    return service


def _follows(request: Request) -> FollowService:
    service: FollowService = request.app.state.follow_service
    return service


def _page_json(page: Page[Any]) -> dict[str, Any]:
    return {
        "data": [item.model_dump(mode="json") for item in page.data],
        "page": page.page.model_dump(mode="json"),
    }


@router.get("/v1/posts/{post_id}/reactions", response_model=Page[ReactionOut])
async def list_post_reactions(
    post_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _interactions(request).list_reactions(
        principal.user_id, post_id, cursor=cursor, limit=limit
    )
    return JSONResponse(_page_json(page))


@router.post("/v1/posts/{post_id}/reactions", response_model=ReactionResult)
async def react_to_post(
    post_id: uuid.UUID, body: ReactionRequest, request: Request, principal: CurrentPrincipal
) -> ReactionResult:
    return await _interactions(request).react(principal.user_id, post_id, body.reaction)


@router.delete("/v1/posts/{post_id}/reactions/me", status_code=status.HTTP_204_NO_CONTENT)
async def remove_post_reaction(
    post_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _interactions(request).unreact(principal.user_id, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/posts/{post_id}/comments", response_model=Page[CommentOut])
async def list_post_comments(
    post_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _interactions(request).list_comments(
        principal.user_id, post_id, parent_id=None, cursor=cursor, limit=limit
    )
    return JSONResponse(_page_json(page))


@router.post(
    "/v1/posts/{post_id}/comments", status_code=status.HTTP_201_CREATED, response_model=CommentOut
)
async def create_comment(
    post_id: uuid.UUID,
    body: CreateCommentRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    comment, replayed = await _interactions(request).create_comment(
        principal, post_id, body, idempotency_key=idempotency_key
    )
    headers = {"Idempotent-Replayed": "true"} if replayed else {}
    return JSONResponse(
        comment.model_dump(mode="json"), status_code=status.HTTP_201_CREATED, headers=headers
    )


@router.patch("/v1/comments/{comment_id}", response_model=CommentOut)
async def update_comment(
    comment_id: uuid.UUID,
    body: UpdateCommentRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> CommentOut:
    return await _interactions(request).update_comment(principal.user_id, comment_id, body.body)


@router.delete("/v1/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _interactions(request).delete_comment(principal.user_id, comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/comments/{comment_id}/replies", response_model=Page[CommentOut])
async def list_comment_replies(
    comment_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _interactions(request).list_replies(
        principal.user_id, comment_id, cursor=cursor, limit=limit
    )
    return JSONResponse(_page_json(page))


@router.put("/v1/posts/{post_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def bookmark_post(
    post_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _interactions(request).bookmark(principal.user_id, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/v1/posts/{post_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def unbookmark_post(
    post_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _interactions(request).unbookmark(principal.user_id, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/users/me/bookmarks", response_model=Page[Post])
async def list_my_bookmarks(
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _interactions(request).list_bookmarks(
        principal.user_id,
        cursor=cursor,
        limit=limit,
        preferences=parse_accept_language(accept_language),
    )
    return JSONResponse(
        {"data": [p.as_json() for p in page.data], "page": page.page.model_dump(mode="json")}
    )


@router.post(
    "/v1/posts/{post_id}/shares", status_code=status.HTTP_201_CREATED, response_model=ShareLink
)
async def share_post(
    post_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    body: ShareRequest | None = None,
) -> ShareLink:
    return await _interactions(request).share(
        principal.user_id, post_id, body.channel if body else None
    )


# ─────────────────────────────── follows ───────────────────────────────


@router.put("/v1/users/{user_id}/follow", response_model=FollowState, tags=["follows"])
async def follow_user(
    user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> FollowState:
    return await _follows(request).follow(principal.user_id, user_id)


@router.delete(
    "/v1/users/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT, tags=["follows"]
)
async def unfollow_user(
    user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _follows(request).unfollow(principal.user_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/users/me/follow-requests", response_model=Page[UserSummary], tags=["follows"])
async def list_my_follow_requests(
    request: Request, principal: CurrentPrincipal, cursor: Cursor = None, limit: Limit = 20
) -> JSONResponse:
    page = await _follows(request).requests(principal.user_id, cursor=cursor, limit=limit)
    return JSONResponse(_page_json(page))


@router.post(
    "/v1/users/me/follow-requests/{user_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["follows"],
)
async def approve_follow_request(
    user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _follows(request).decide(principal.user_id, user_id, approve=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/v1/users/me/follow-requests/{user_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["follows"],
)
async def decline_follow_request(
    user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _follows(request).decide(principal.user_id, user_id, approve=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/users/{user_id}/followers", response_model=Page[UserSummary], tags=["profiles"])
async def list_followers(
    user_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _follows(request).followers(principal.user_id, user_id, cursor=cursor, limit=limit)
    return JSONResponse(_page_json(page))


@router.get("/v1/users/{user_id}/following", response_model=Page[UserSummary], tags=["profiles"])
async def list_following(
    user_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _follows(request).following(principal.user_id, user_id, cursor=cursor, limit=limit)
    return JSONResponse(_page_json(page))


# ─────────────────────────────── guest mode (AUTH-012) ───────────────────────────────

_KINDS = {kind.value for kind in PostKind}


def _public(request: Request) -> PublicPostService:
    service: PublicPostService = request.app.state.public_post_service
    return service


def _categories(raw: str | None) -> list[str]:
    kinds = [k.strip() for k in (raw or "").split(",") if k.strip()]
    unknown = sorted(set(kinds) - _KINDS)
    if unknown:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "Unknown post category.",
            errors=[FieldError(field="/category", code="enum", message=", ".join(unknown))],
        )
    return list(dict.fromkeys(kinds))


@router.get("/v1/public/posts", tags=["feed"], openapi_extra=rate_limited("guest"))
async def list_public_posts(
    request: Request,
    accept_language: AcceptLanguage = None,
    destination_id: uuid.UUID | None = None,
    category: Annotated[str | None, Query(max_length=300)] = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _public(request).list(
        destination_id=destination_id,
        kinds=_categories(category),
        cursor=cursor,
        limit=limit,
        preferences=parse_accept_language(accept_language),
    )
    return JSONResponse(
        {"data": page.data, "page": page.page.model_dump(mode="json")},
        headers={"Cache-Control": CACHE_CONTROL},
    )


@router.get("/v1/public/posts/{post_id}", tags=["feed"], openapi_extra=rate_limited("guest"))
async def get_public_post(
    post_id: uuid.UUID, request: Request, accept_language: AcceptLanguage = None
) -> JSONResponse:
    post = await _public(request).get(post_id, preferences=parse_accept_language(accept_language))
    return JSONResponse(post, headers={"Cache-Control": CACHE_CONTROL})
