"""HTTP adapters for ``/v1/destinations*`` (anonymous-capable except ``resolve``)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.i18n import parse_accept_language
from app.core.pagination import Page
from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.destinations.models import Continent, DestinationKind
from app.modules.destinations.schemas import Destination, DestinationSummary
from app.modules.destinations.service import DestinationService, ListFilters

router = APIRouter(prefix="/v1/destinations", tags=["destinations"])

_KINDS = {kind.value for kind in DestinationKind}
_CONTINENTS = {c.value for c in Continent}
CountryCode = Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")]
Limit = Annotated[int, Query(ge=1, le=100)]
CursorParam = Annotated[str | None, Query(max_length=1024)]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language", max_length=200)]


def _service(request: Request) -> DestinationService:
    service: DestinationService = request.app.state.destination_service
    return service


def _kinds(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    kinds = tuple(dict.fromkeys(k.strip() for k in raw.split(",") if k.strip()))
    unknown = [k for k in kinds if k not in _KINDS]
    if unknown:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "Unknown destination kind.",
            errors=[
                FieldError(
                    field="/kind", code="enum", message=f"Unknown kind: {', '.join(unknown)}"
                )
            ],
        )
    return kinds


def _preferences(accept_language: str | None) -> list[str]:
    return parse_accept_language(accept_language)


@router.get("", response_model=Page[DestinationSummary])
async def list_destinations(
    request: Request,
    accept_language: AcceptLanguage = None,
    kind: Annotated[str | None, Query(max_length=120)] = None,
    country: CountryCode = None,
    continent: Annotated[str | None, Query(max_length=40)] = None,
    featured: bool | None = None,
    sort: Literal["popularity", "slug"] = "popularity",
    cursor: CursorParam = None,
    limit: Limit = 20,
) -> Page[DestinationSummary]:
    if continent is not None and continent not in _CONTINENTS:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "Unknown continent.",
            errors=[FieldError(field="/continent", code="enum", message="Unknown continent.")],
        )
    filters = ListFilters(
        kinds=_kinds(kind), country=country, continent=continent, featured=featured
    )
    return await _service(request).list(
        filters, sort=sort, cursor=cursor, limit=limit, preferences=_preferences(accept_language)
    )


@router.get(
    "/search", response_model=Page[DestinationSummary], openapi_extra=rate_limited("search")
)
async def search_destinations(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    accept_language: AcceptLanguage = None,
    kind: Annotated[str | None, Query(max_length=120)] = None,
    country: CountryCode = None,
    limit: Limit = 10,
) -> Page[DestinationSummary]:
    return await _service(request).search(
        q,
        kinds=_kinds(kind),
        country=country,
        limit=limit,
        preferences=_preferences(accept_language),
    )


@router.get("/featured", response_model=Page[DestinationSummary])
async def featured_destinations(
    request: Request,
    accept_language: AcceptLanguage = None,
    cursor: CursorParam = None,
    limit: Limit = 20,
) -> Page[DestinationSummary]:
    return await _service(request).featured(
        cursor=cursor, limit=limit, preferences=_preferences(accept_language)
    )


@router.get("/lookup", response_model=Destination)
async def lookup_destination(
    request: Request,
    path: Annotated[
        str,
        Query(
            max_length=300,
            pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*){0,5}$",
        ),
    ],
    accept_language: AcceptLanguage = None,
) -> Destination:
    return await _service(request).lookup(path, preferences=_preferences(accept_language))


@router.get("/resolve", response_model=Destination)
async def resolve_destination(
    request: Request,
    _principal: Annotated[Principal, Depends(get_principal)],
    near: Annotated[str, Query(max_length=40)],
    accept_language: AcceptLanguage = None,
) -> Destination:
    return await _service(request).resolve(near, preferences=_preferences(accept_language))


@router.get("/{destination_id}", response_model=Destination)
async def get_destination(
    destination_id: uuid.UUID, request: Request, accept_language: AcceptLanguage = None
) -> Destination:
    return await _service(request).get(destination_id, preferences=_preferences(accept_language))


@router.get("/{destination_id}/children", response_model=Page[DestinationSummary])
async def destination_children(
    destination_id: uuid.UUID,
    request: Request,
    accept_language: AcceptLanguage = None,
    cursor: CursorParam = None,
    limit: Limit = 20,
) -> Page[DestinationSummary]:
    return await _service(request).children(
        destination_id, cursor=cursor, limit=limit, preferences=_preferences(accept_language)
    )
