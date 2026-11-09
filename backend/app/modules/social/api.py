"""HTTP adapters for ``/v1/posts*`` and ``/v1/users/{userId}/posts``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.i18n import parse_accept_language
from app.core.pagination import Page
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.social.schemas import CreatePostRequest, Post, UpdatePostRequest
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
