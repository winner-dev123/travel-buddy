"""Google Play Billing (BL-6.01; BILL-002, BILL-003, BILL-007, BILL-008).

* Purchases are verified with the Play Developer API (``purchases.subscriptionsv2`` for
  subscriptions, ``purchases.products`` for one-time products) using a service account; the
  client's token is never trusted on its own. New purchases are acknowledged, or Google refunds
  them after three days.
* Real-time Developer Notifications arrive through a Pub/Sub push subscription. The push carries a
  Google-signed OIDC token: its signature, issuer, audience (our endpoint) and service account are
  checked before anything is read. Notifications only say *that* something changed; the state is
  re-read from the API.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx
import jwt

from app.core.errors import AppError, ErrorCode
from app.modules.billing.domain import SubscriptionStatus
from app.modules.billing.providers import PurchaseClaim, StoreTransaction

API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
SCOPE = "https://www.googleapis.com/auth/androidpublisher"
GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret

# subscriptionsv2 ``subscriptionState`` → our status. ``CANCELED`` still has access until the
# expiry (auto-renew off); ``PENDING`` (payment not yet made) and ``PENDING_PURCHASE_CANCELED``
# grant nothing and are refused at verification.
_STATES: Mapping[str, SubscriptionStatus] = {
    "SUBSCRIPTION_STATE_ACTIVE": SubscriptionStatus.ACTIVE,
    "SUBSCRIPTION_STATE_CANCELED": SubscriptionStatus.ACTIVE,
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": SubscriptionStatus.IN_GRACE_PERIOD,
    "SUBSCRIPTION_STATE_ON_HOLD": SubscriptionStatus.IN_BILLING_RETRY,
    "SUBSCRIPTION_STATE_PAUSED": SubscriptionStatus.PAUSED,
    "SUBSCRIPTION_STATE_EXPIRED": SubscriptionStatus.EXPIRED,
}
# RTDN subscription notification types that end access at once (refund or revocation).
REVOKING_NOTIFICATIONS = frozenset({12})  # SUBSCRIPTION_REVOKED


class GooglePlayError(Exception):
    """The Play Developer API refused or failed (not the user's fault)."""


class GoogleAuthError(Exception):
    """A push request without a valid Google OIDC token."""


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    client_email: str
    private_key: str
    token_uri: str = TOKEN_URI

    @classmethod
    def from_json(cls, raw: str) -> ServiceAccount:
        data = json.loads(raw)
        return cls(
            client_email=str(data["client_email"]),
            private_key=str(data["private_key"]),
            token_uri=str(data.get("token_uri") or TOKEN_URI),
        )


@dataclass(frozen=True, slots=True)
class PlaySubscription:
    """The authoritative state of a subscription purchase token."""

    purchase_token: str
    sku: str
    status: SubscriptionStatus | None  # None: pending or unknown, grants nothing
    auto_renew: bool
    started_at: datetime | None
    expires_at: datetime | None
    order_id: str
    acknowledged: bool
    test: bool
    account_id: str | None  # obfuscatedExternalAccountId set by the app at purchase


@dataclass(frozen=True, slots=True)
class PlayProduct:
    purchase_token: str
    sku: str
    purchased: bool  # purchaseState 0
    purchased_at: datetime | None
    order_id: str
    acknowledged: bool
    test: bool
    account_id: str | None


def _rfc3339(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _millis(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC)
    except (TypeError, ValueError):
        return None


def parse_subscription(token: str, data: Mapping[str, Any]) -> PlaySubscription:
    items = data.get("lineItems") or [{}]
    item = items[0] if isinstance(items[0], dict) else {}
    plan = item.get("autoRenewingPlan") or {}
    state = str(data.get("subscriptionState", ""))
    identifiers = data.get("externalAccountIdentifiers") or {}
    return PlaySubscription(
        purchase_token=token,
        sku=str(item.get("productId", "")),
        status=_STATES.get(state),
        auto_renew=bool(plan.get("autoRenewEnabled", False))
        and state != "SUBSCRIPTION_STATE_CANCELED",
        started_at=_rfc3339(data.get("startTime")),
        expires_at=_rfc3339(item.get("expiryTime")),
        order_id=str(data.get("latestOrderId") or item.get("latestSuccessfulOrderId") or token),
        acknowledged=data.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        test="testPurchase" in data,
        account_id=identifiers.get("obfuscatedExternalAccountId"),
    )


def parse_product(token: str, sku: str, data: Mapping[str, Any]) -> PlayProduct:
    return PlayProduct(
        purchase_token=token,
        sku=sku,
        purchased=data.get("purchaseState") == 0,
        purchased_at=_millis(data.get("purchaseTimeMillis")),
        order_id=str(data.get("orderId") or token),
        acknowledged=data.get("acknowledgementState") == 1,
        test=data.get("purchaseType") == 0,
        account_id=data.get("obfuscatedExternalAccountId"),
    )


class PlayApi(Protocol):
    """The calls we make to the Play Developer API (a fake stands in for tests)."""

    async def subscription(self, token: str) -> Mapping[str, Any]: ...
    async def product(self, sku: str, token: str) -> Mapping[str, Any]: ...
    async def acknowledge_subscription(self, sku: str, token: str) -> None: ...
    async def acknowledge_product(self, sku: str, token: str) -> None: ...


class GooglePlayApi:
    """``PlayApi`` over HTTPS with a service account (OAuth 2.0 JWT bearer grant)."""

    def __init__(
        self, account: ServiceAccount, package_name: str, http_client: httpx.AsyncClient
    ) -> None:
        self._account = account
        self._package = package_name
        self._http = http_client
        self._token: tuple[str, float] | None = None
        self._lock = asyncio.Lock()

    async def _access_token(self) -> str:
        async with self._lock:
            if self._token is not None and self._token[1] > time.monotonic() + 60:
                return self._token[0]
            issued = int(time.time())
            assertion = jwt.encode(
                {
                    "iss": self._account.client_email,
                    "scope": SCOPE,
                    "aud": self._account.token_uri,
                    "iat": issued,
                    "exp": issued + 3600,
                },
                self._account.private_key,
                algorithm="RS256",
            )
            response = await self._http.post(
                self._account.token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=10,
            )
            if response.status_code != 200:
                raise GooglePlayError(f"token exchange failed ({response.status_code})")
            body = response.json()
            self._token = (str(body["access_token"]), time.monotonic() + int(body["expires_in"]))
            return self._token[0]

    async def _call(self, method: str, path: str) -> Mapping[str, Any]:
        token = await self._access_token()
        response = await self._http.request(
            method,
            f"{API}/{quote(self._package, safe='')}/{path}",
            headers={"Authorization": f"Bearer {token}"},
            json={} if method == "POST" else None,
            timeout=10,
        )
        if response.status_code in (400, 404, 410):
            raise AppError(ErrorCode.PURCHASE_INVALID, "This purchase couldn't be verified.")
        if response.status_code >= 300:
            raise GooglePlayError(f"Play Developer API answered {response.status_code}")
        body: Mapping[str, Any] = response.json() if response.content else {}
        return body

    async def subscription(self, token: str) -> Mapping[str, Any]:
        return await self._call("GET", f"purchases/subscriptionsv2/tokens/{quote(token, safe='')}")

    async def product(self, sku: str, token: str) -> Mapping[str, Any]:
        return await self._call(
            "GET", f"purchases/products/{quote(sku, safe='')}/tokens/{quote(token, safe='')}"
        )

    async def acknowledge_subscription(self, sku: str, token: str) -> None:
        await self._call(
            "POST",
            f"purchases/subscriptions/{quote(sku, safe='')}/tokens/{quote(token, safe='')}"
            ":acknowledge",
        )

    async def acknowledge_product(self, sku: str, token: str) -> None:
        await self._call(
            "POST",
            f"purchases/products/{quote(sku, safe='')}/tokens/{quote(token, safe='')}:acknowledge",
        )


class GooglePlayProvider:
    """``BillingProvider`` for Play Billing: the client sends the purchase token and SKU."""

    def __init__(self, api: PlayApi, package_name: str) -> None:
        self._api = api
        self.package_name = package_name

    async def verify(self, claim: PurchaseClaim, *, now: datetime) -> StoreTransaction:
        if claim.package_name != self.package_name or not claim.sku:
            raise AppError(ErrorCode.PURCHASE_INVALID, "This purchase is for another app.")
        try:
            if claim.product_kind == "auto_renewable":
                return await self._verify_subscription(claim.payload, claim.sku, now)
            return await self._verify_product(claim.payload, claim.sku, now)
        except GooglePlayError:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Google Play couldn't confirm the purchase right now. Try again soon.",
                headers={"Retry-After": "30"},
            ) from None

    async def subscription_state(self, token: str) -> PlaySubscription:
        return parse_subscription(token, await self._api.subscription(token))

    async def _verify_subscription(self, token: str, sku: str, now: datetime) -> StoreTransaction:
        state = await self.subscription_state(token)
        if state.sku != sku or state.status is None:
            raise AppError(ErrorCode.PURCHASE_INVALID, "This purchase couldn't be verified.")
        if not state.acknowledged:
            await self._api.acknowledge_subscription(sku, token)
        return StoreTransaction(
            provider="google",
            sku=sku,
            original_transaction_id=token,  # stable across renewals of this purchase
            transaction_id=state.order_id,
            purchased_at=min(state.started_at or now, now),
            status=state.status,
            auto_renew=state.auto_renew,
            environment="sandbox" if state.test else "production",
            expires_at=state.expires_at,
        )

    async def _verify_product(self, token: str, sku: str, now: datetime) -> StoreTransaction:
        product = parse_product(token, sku, await self._api.product(sku, token))
        if not product.purchased:
            raise AppError(ErrorCode.PURCHASE_INVALID, "This purchase couldn't be verified.")
        if not product.acknowledged:
            await self._api.acknowledge_product(sku, token)
        return StoreTransaction(
            provider="google",
            sku=sku,
            original_transaction_id=token,
            transaction_id=product.order_id,
            purchased_at=min(product.purchased_at or now, now),
            status=SubscriptionStatus.ACTIVE,
            auto_renew=False,
            environment="sandbox" if product.test else "production",
        )


# ─────────────────────────── Pub/Sub push (RTDN) ───────────────────────────


class GoogleKeys(Protocol):
    async def key_for(self, kid: str) -> Any: ...


class GoogleCerts:
    """Google's OIDC signing keys, cached for an hour (refetched on an unknown ``kid``)."""

    def __init__(self, http_client: httpx.AsyncClient, url: str = GOOGLE_CERTS) -> None:
        self._http = http_client
        self._url = url
        self._keys: dict[str, Any] = {}
        self._fetched = 0.0
        self._lock = asyncio.Lock()

    async def key_for(self, kid: str) -> Any:
        async with self._lock:
            stale = time.monotonic() - self._fetched > 3600
            if kid not in self._keys or stale:
                response = await self._http.get(self._url, timeout=10)
                response.raise_for_status()
                self._keys = {
                    str(k["kid"]): jwt.PyJWK(k).key for k in response.json().get("keys", [])
                }
                self._fetched = time.monotonic()
            if kid not in self._keys:
                raise GoogleAuthError("unknown signing key")
            return self._keys[kid]


class PushVerifier:
    """Checks the OIDC token Pub/Sub attaches to push requests."""

    def __init__(self, keys: GoogleKeys, *, audience: str, service_account: str) -> None:
        self._keys = keys
        self._audience = audience
        self._service_account = service_account

    async def verify(self, authorization: str | None) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise GoogleAuthError("missing token")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise GoogleAuthError("unexpected algorithm")
            key = await self._keys.key_for(str(header.get("kid", "")))
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                options={"require": ["exp", "iat", "iss", "aud"]},
                leeway=30,
            )
        except (jwt.PyJWTError, httpx.HTTPError) as exc:
            raise GoogleAuthError(str(exc)) from None
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise GoogleAuthError("issuer")
        if claims.get("email") != self._service_account or claims.get("email_verified") is not True:
            raise GoogleAuthError("service account")


@dataclass(frozen=True, slots=True)
class DeveloperNotification:
    message_id: str
    published_at: datetime | None
    package_name: str
    kind: str  # "subscription" | "one_time" | "voided" | "test" | "other"
    purchase_token: str | None
    sku: str | None
    notification_type: int | None
    order_id: str | None = None  # voided purchases name the order (one-time products)


def parse_push(body: Mapping[str, Any]) -> DeveloperNotification:
    message = body.get("message")
    if not isinstance(message, dict) or not message.get("messageId"):
        raise ValueError("no message")
    try:
        data = json.loads(base64.b64decode(str(message.get("data", "")), validate=True))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("data is not base64 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("data is not an object")
    kind, token, sku, ntype, order = "other", None, None, None, None
    if isinstance(data.get("subscriptionNotification"), dict):
        note = data["subscriptionNotification"]
        kind, token, sku = "subscription", note.get("purchaseToken"), note.get("subscriptionId")
        ntype = note.get("notificationType")
    elif isinstance(data.get("oneTimeProductNotification"), dict):
        note = data["oneTimeProductNotification"]
        kind, token, sku = "one_time", note.get("purchaseToken"), note.get("sku")
        ntype = note.get("notificationType")
    elif isinstance(data.get("voidedPurchaseNotification"), dict):
        note = data["voidedPurchaseNotification"]
        kind, token, order = "voided", note.get("purchaseToken"), note.get("orderId")
    elif "testNotification" in data:
        kind = "test"
    return DeveloperNotification(
        message_id=str(message["messageId"]),
        published_at=_rfc3339(message.get("publishTime")),
        package_name=str(data.get("packageName", "")),
        kind=kind,
        purchase_token=str(token) if token else None,
        sku=str(sku) if sku else None,
        notification_type=int(str(ntype)) if str(ntype).isdigit() else None,
        order_id=str(order) if order else None,
    )
