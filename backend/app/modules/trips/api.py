"""``/v1/trips``: trips, days, items and offline sync (BL-4.04)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.feature_flags import Flag, gate
from app.core.i18n import parse_accept_language
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.trips.saved_places import SavedPlaceService
from app.modules.trips.schemas import (
    ApplyItineraryRequest,
    CollaboratorRequest,
    CreateTripRequest,
    DayInput,
    ItemInput,
    ItemPatch,
    SavedPlaceOut,
    SavedPlacePage,
    SavePlaceRequest,
    SyncRequest,
    SyncResult,
    TripOut,
    TripSummaryPage,
    UpdateTripRequest,
)
from app.modules.trips.service import TripService

router = APIRouter(prefix="/v1/trips", tags=["trips"], dependencies=gate(Flag.TRIPS))

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _service(request: Request) -> TripService:
    service: TripService = request.app.state.trip_service
    return service


def _tagged(trip: TripOut, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        trip.model_dump(mode="json"), status_code=status_code, headers={"ETag": f'"{trip.version}"'}
    )


@router.get("", response_model=TripSummaryPage)
async def list_trips(
    request: Request,
    principal: CurrentPrincipal,
    status_filter: Annotated[
        Literal["planning", "active", "completed", "archived"] | None, Query(alias="status")
    ] = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TripSummaryPage:
    return await _service(request).list_mine(
        principal.user_id, status=status_filter, cursor=cursor, limit=limit
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TripOut)
async def create_trip(
    body: CreateTripRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    trip = await _service(request).create(principal, body, idempotency_key=idempotency_key)
    return _tagged(trip, status.HTTP_201_CREATED)


@router.get("/{trip_id}", response_model=TripOut)
async def get_trip(
    trip_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    return _tagged(await _service(request).get(principal.user_id, trip_id))


@router.patch("/{trip_id}", response_model=TripOut)
async def update_trip(
    trip_id: uuid.UUID,
    body: UpdateTripRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).update(principal.user_id, trip_id, body, if_match=if_match)
    )


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip(
    trip_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).delete(principal.user_id, trip_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{trip_id}/collaborators/{user_id}", response_model=TripOut)
async def set_trip_collaborator(
    trip_id: uuid.UUID,
    user_id: uuid.UUID,
    body: CollaboratorRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> TripOut:
    return await _service(request).set_collaborator(principal.user_id, trip_id, user_id, body.role)


@router.delete("/{trip_id}/collaborators/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_trip_collaborator(
    trip_id: uuid.UUID, user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).remove_collaborator(principal.user_id, trip_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{trip_id}/days", status_code=status.HTTP_201_CREATED, response_model=TripOut)
async def add_day(
    trip_id: uuid.UUID,
    body: DayInput,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    trip = await _service(request).add_day(principal.user_id, trip_id, body, if_match=if_match)
    return _tagged(trip, status.HTTP_201_CREATED)


@router.patch("/{trip_id}/days/{day_id}", response_model=TripOut)
async def update_day(
    trip_id: uuid.UUID,
    day_id: uuid.UUID,
    body: DayInput,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).update_day(
            principal.user_id, trip_id, day_id, body, if_match=if_match
        )
    )


@router.delete("/{trip_id}/days/{day_id}", response_model=TripOut)
async def delete_day(
    trip_id: uuid.UUID,
    day_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).delete_day(principal.user_id, trip_id, day_id, if_match=if_match)
    )


@router.post(
    "/{trip_id}/days/{day_id}/items", status_code=status.HTTP_201_CREATED, response_model=TripOut
)
async def add_item(
    trip_id: uuid.UUID,
    day_id: uuid.UUID,
    body: ItemInput,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    trip = await _service(request).add_item(
        principal.user_id, trip_id, day_id, body, if_match=if_match
    )
    return _tagged(trip, status.HTTP_201_CREATED)


@router.patch("/{trip_id}/items/{item_id}", response_model=TripOut)
async def update_item(
    trip_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemPatch,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).update_item(
            principal.user_id, trip_id, item_id, body, if_match=if_match
        )
    )


@router.delete("/{trip_id}/items/{item_id}", response_model=TripOut)
async def delete_item(
    trip_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).delete_item(principal.user_id, trip_id, item_id, if_match=if_match)
    )


@router.post("/{trip_id}/apply-itinerary", response_model=TripOut)
async def apply_itinerary(
    trip_id: uuid.UUID,
    body: ApplyItineraryRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).apply_itinerary(principal.user_id, trip_id, body, if_match=if_match)
    )


@router.post("/{trip_id}/sync", response_model=SyncResult)
async def sync_trip(
    trip_id: uuid.UUID,
    body: SyncRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> SyncResult:
    return await _service(request).sync(principal, trip_id, body, idempotency_key=idempotency_key)


# ─────────────────────────────── saved places (TRIP-003) ───────────────────────────────

saved_places_router = APIRouter(
    prefix="/v1/users/me/saved-places", tags=["trips"], dependencies=gate(Flag.TRIPS)
)
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language", max_length=200)]
Collection = Annotated[str, Query(min_length=1, max_length=40)]


def _saved(request: Request) -> SavedPlaceService:
    service: SavedPlaceService = request.app.state.saved_place_service
    return service


@saved_places_router.get("", response_model=SavedPlacePage)
async def list_saved_places(
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
    collection: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    destination_id: uuid.UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SavedPlacePage:
    return await _saved(request).list(
        principal.user_id,
        collection=collection,
        destination_id=destination_id,
        cursor=cursor,
        limit=limit,
        preferences=parse_accept_language(accept_language),
    )


@saved_places_router.put("/{place_id}", response_model=SavedPlaceOut)
async def save_place(
    place_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    body: SavePlaceRequest | None = None,
    accept_language: AcceptLanguage = None,
) -> SavedPlaceOut:
    return await _saved(request).save(
        principal.user_id,
        place_id,
        body or SavePlaceRequest(),
        preferences=parse_accept_language(accept_language),
    )


@saved_places_router.delete("/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsave_place(
    place_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    collection: Collection = "default",
) -> Response:
    await _saved(request).unsave(principal.user_id, place_id, collection)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
