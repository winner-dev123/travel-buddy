"""``/v1/billing``: products, entitlements, purchases, web checkout, purchase history and store
webhooks (BL-3.01/3.02/3.14/3.15)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.feature_flags import Flag, gate
from app.core.i18n import parse_accept_language
from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.billing.domain import StoreEvent
from app.modules.billing.providers import PurchaseClaim
from app.modules.billing.schemas import (
    AppleRestoreRequest,
    AppleVerifyRequest,
    DevBillingEventRequest,
    Entitlements,
    GoogleRestoreRequest,
    GoogleVerifyRequest,
    ProductList,
    TransactionPage,
    VerifyPurchaseResult,
)
from app.modules.billing.service import BillingService

router = APIRouter(prefix="/v1/billing", tags=["billing"])
# Entitlements (everyone has the free plan) and store webhooks stay open when billing is off.
_BILLING = gate(Flag.BILLING)
dev_router = APIRouter(prefix="/v1/dev/billing", tags=["dev"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language", max_length=200)]
VerifyBody = Annotated[AppleVerifyRequest | GoogleVerifyRequest, Field(discriminator="provider")]
RestoreBody = Annotated[AppleRestoreRequest | GoogleRestoreRequest, Field(discriminator="provider")]
NO_STORE = {"Cache-Control": "no-store"}
# Relative paths on the web origin only: absolute URLs are refused (no open redirects).
RELATIVE_PATH = r"^/[A-Za-z0-9/_\-.~%?=&]*$"


def _service(request: Request) -> BillingService:
    service: BillingService = request.app.state.billing_service
    return service


@router.get("/products", dependencies=_BILLING, response_model=ProductList)
async def list_products(
    request: Request,
    platform: Literal["ios", "android", "web"],
    accept_language: AcceptLanguage = None,
) -> ProductList:
    """Offers in display order with localized titles; web offers carry Stripe's price."""
    return ProductList(
        data=await _service(request).products(platform, parse_accept_language(accept_language))
    )


@router.get("/transactions", response_model=TransactionPage)
async def list_transactions(
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    """My payments, refunds and disputes across the stores and the web, newest first."""
    page = await _service(request).transactions(
        principal.user_id,
        cursor=cursor,
        limit=limit,
        preferences=parse_accept_language(accept_language),
    )
    return JSONResponse(page.model_dump(mode="json"), headers=NO_STORE)


@router.get("/entitlements", response_model=Entitlements, response_model_by_alias=True)
async def get_entitlements(request: Request, principal: CurrentPrincipal) -> JSONResponse:
    out = await _service(request).entitlements(principal.user_id)
    return JSONResponse(out.model_dump(mode="json", by_alias=True), headers=NO_STORE)


@router.post(
    "/purchases/verify",
    dependencies=_BILLING,
    response_model=VerifyPurchaseResult,
    response_model_by_alias=True,
    openapi_extra=rate_limited("billing"),
)
async def verify_purchase(
    body: Annotated[VerifyBody, Body()],
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    if isinstance(body, AppleVerifyRequest):
        claim = PurchaseClaim(store="apple", payload=body.signed_transaction)
    else:
        claim = PurchaseClaim(
            store="google",
            payload=body.purchase_token,
            sku=body.product_sku,
            package_name=body.package_name,
        )
    out = await _service(request).verify(principal, claim, idempotency_key=idempotency_key)
    return JSONResponse(out.model_dump(mode="json", by_alias=True), headers=NO_STORE)


@router.post(
    "/purchases/restore",
    dependencies=_BILLING,
    response_model=Entitlements,
    response_model_by_alias=True,
    openapi_extra=rate_limited("billing"),
)
async def restore_purchases(
    body: Annotated[RestoreBody, Body()],
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    if isinstance(body, AppleRestoreRequest):
        claims = [PurchaseClaim(store="apple", payload=t) for t in body.signed_transactions]
    else:
        claims = [
            PurchaseClaim(
                store="google",
                payload=p.purchase_token,
                sku=p.product_sku,
                package_name=body.package_name,
            )
            for p in body.purchases
        ]
    out = await _service(request).restore(principal, claims, idempotency_key=idempotency_key)
    return JSONResponse(out.model_dump(mode="json", by_alias=True), headers=NO_STORE)


@dev_router.post("/events")
async def simulate_store_event(
    body: DevBillingEventRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, str]:
    """Development and tests only (mounted with ``DEV_BILLING_ENABLED``)."""
    del principal  # any signed-in developer may drive the simulated store
    outcome = await _service(request).apply_event(
        provider="dev",
        provider_event_id=body.event_id or str(uuid.uuid4()),
        original_transaction_id=body.original_transaction_id,
        event=StoreEvent(body.event),
        signed_date=body.signed_date,
    )
    return {"outcome": outcome}


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    success_path: str = Field(max_length=512, pattern=RELATIVE_PATH)
    cancel_path: str = Field(max_length=512, pattern=RELATIVE_PATH)


class PortalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_path: str | None = Field(default=None, max_length=512, pattern=RELATIVE_PATH)


@router.post(
    "/checkout-sessions",
    dependencies=_BILLING,
    status_code=201,
    openapi_extra=rate_limited("billing"),
)
async def create_checkout_session(
    body: CheckoutRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    """Web only (ADR-0012): a hosted Checkout URL; only the webhook grants entitlements."""
    url, expires_at = await _service(request).checkout(
        principal,
        product_id=body.product_id,
        success_path=body.success_path,
        cancel_path=body.cancel_path,
        idempotency_key=idempotency_key,
    )
    return JSONResponse(
        {"url": url, "expires_at": expires_at.isoformat() if expires_at else None},
        status_code=201,
        headers=NO_STORE,
    )


@router.post(
    "/portal-sessions",
    dependencies=_BILLING,
    status_code=201,
    openapi_extra=rate_limited("billing"),
)
async def create_portal_session(
    request: Request,
    principal: CurrentPrincipal,
    body: Annotated[PortalRequest | None, Body()] = None,
) -> JSONResponse:
    url = await _service(request).portal(principal, return_path=body.return_path if body else None)
    return JSONResponse({"url": url, "expires_at": None}, status_code=201, headers=NO_STORE)


class AppleNotificationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    signedPayload: str = Field(min_length=1, max_length=65536)  # noqa: N815 - Apple's name


@router.post("/webhooks/apple", openapi_extra=rate_limited("webhook"))
async def receive_apple_notification(
    body: AppleNotificationRequest, request: Request
) -> dict[str, str]:
    """App Store Server Notifications v2; verified against the pinned Apple root."""
    outcome = await _service(request).apple_webhook(body.signedPayload)
    return {"status": outcome}


@router.post(
    "/webhooks/google",
    status_code=status.HTTP_204_NO_CONTENT,
    openapi_extra=rate_limited("webhook"),
)
async def receive_google_notification(
    body: dict[str, Any],
    request: Request,
    authorization: Annotated[str | None, Header(max_length=4096)] = None,
) -> Response:
    """Play Real-time Developer Notifications via Pub/Sub push; the push OIDC token is verified
    before the message is read."""
    await _service(request).google_webhook(body, authorization)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/webhooks/stripe", openapi_extra=rate_limited("webhook"))
async def receive_stripe_webhook(
    request: Request,
    stripe_signature: Annotated[
        str | None, Header(alias="Stripe-Signature", max_length=2048)
    ] = None,
) -> dict[str, str]:
    """Signature-verified against the raw body before parsing; stored once per event."""
    outcome = await _service(request).stripe_webhook(await request.body(), stripe_signature)
    return {"status": outcome}
