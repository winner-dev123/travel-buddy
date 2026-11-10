"""Google Play adapters: state mapping, push parsing, OIDC push auth, API client (BL-6.01)."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.errors import AppError, ErrorCode
from app.modules.billing.domain import SubscriptionStatus
from app.modules.billing.google import (
    GoogleAuthError,
    GooglePlayApi,
    GooglePlayProvider,
    PushVerifier,
    ServiceAccount,
    parse_push,
    parse_subscription,
)
from app.modules.billing.providers import PurchaseClaim

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
PACKAGE = "app.travelbuddy"
AUDIENCE = "https://api.travelbuddy.app/v1/billing/webhooks/google"
PUSHER = "rtdn-push@travelbuddy.iam.gserviceaccount.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()


def _subscription(state: str, **extra: Any) -> dict[str, Any]:
    return {
        "subscriptionState": state,
        "startTime": "2026-11-01T10:00:00.000Z",
        "latestOrderId": "GPA.1111-2222-3333-44444..1",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED",
        "lineItems": [
            {
                "productId": "premium_monthly",
                "expiryTime": "2026-12-01T10:00:00.000Z",
                "autoRenewingPlan": {"autoRenewEnabled": True},
            }
        ],
        **extra,
    }


@pytest.mark.req("BILL-002", "BILL-005")
@pytest.mark.parametrize(
    ("state", "status", "auto_renew"),
    [
        ("SUBSCRIPTION_STATE_ACTIVE", SubscriptionStatus.ACTIVE, True),
        ("SUBSCRIPTION_STATE_CANCELED", SubscriptionStatus.ACTIVE, False),  # access until expiry
        ("SUBSCRIPTION_STATE_IN_GRACE_PERIOD", SubscriptionStatus.IN_GRACE_PERIOD, True),
        ("SUBSCRIPTION_STATE_ON_HOLD", SubscriptionStatus.IN_BILLING_RETRY, True),
        ("SUBSCRIPTION_STATE_PAUSED", SubscriptionStatus.PAUSED, True),
        ("SUBSCRIPTION_STATE_EXPIRED", SubscriptionStatus.EXPIRED, True),
        ("SUBSCRIPTION_STATE_PENDING", None, True),  # not paid yet: grants nothing
    ],
)
def test_subscription_states_map_to_ours(
    state: str, status: SubscriptionStatus | None, auto_renew: bool
) -> None:
    parsed = parse_subscription("tok", _subscription(state))
    assert parsed.status is status
    assert parsed.auto_renew is auto_renew
    assert parsed.sku == "premium_monthly"
    assert parsed.expires_at == datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
    assert parsed.order_id == "GPA.1111-2222-3333-44444..1"
    assert parsed.test is False


def _push(data: Mapping[str, Any], message_id: str = "m-1") -> dict[str, Any]:
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    return {
        "message": {"data": encoded, "messageId": message_id, "publishTime": NOW.isoformat()},
        "subscription": "projects/tb/subscriptions/rtdn",
    }


@pytest.mark.req("BILL-007")
def test_push_messages_are_decoded() -> None:
    note = parse_push(
        _push(
            {
                "packageName": PACKAGE,
                "subscriptionNotification": {
                    "notificationType": 12,
                    "purchaseToken": "tok",
                    "subscriptionId": "premium_monthly",
                },
            }
        )
    )
    assert (note.kind, note.purchase_token, note.sku, note.notification_type) == (
        "subscription",
        "tok",
        "premium_monthly",
        12,
    )
    voided = parse_push(
        _push(
            {
                "packageName": PACKAGE,
                "voidedPurchaseNotification": {"purchaseToken": "t2", "orderId": "GPA.9"},
            }
        )
    )
    assert (voided.kind, voided.purchase_token, voided.order_id) == ("voided", "t2", "GPA.9")
    assert parse_push(_push({"packageName": PACKAGE, "testNotification": {}})).kind == "test"
    with pytest.raises(ValueError, match="base64"):
        parse_push({"message": {"messageId": "x", "data": "%%%"}})
    with pytest.raises(ValueError, match="no message"):
        parse_push({"subscription": "s"})


class _Keys:
    async def key_for(self, kid: str) -> Any:
        if kid != "k1":
            raise GoogleAuthError("unknown signing key")
        return KEY.public_key()


def _token(**claims: Any) -> str:
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": AUDIENCE,
        "email": PUSHER,
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
        **claims,
    }
    return jwt.encode(payload, PEM, algorithm="RS256", headers={"kid": "k1"})


@pytest.mark.security
@pytest.mark.req("BILL-007")
def test_push_requests_need_a_google_token_for_our_endpoint_and_account() -> None:
    verifier = PushVerifier(_Keys(), audience=AUDIENCE, service_account=PUSHER)
    asyncio.run(verifier.verify(f"Bearer {_token()}"))
    bad = [
        None,
        "Basic abc",
        f"Bearer {_token(aud='https://evil.example/hook')}",
        f"Bearer {_token(iss='https://evil.example')}",
        f"Bearer {_token(email='someone@else.iam.gserviceaccount.com')}",
        f"Bearer {_token(email_verified=False)}",
        f"Bearer {_token(exp=int(time.time()) - 3600)}",
        f"Bearer {jwt.encode({'aud': AUDIENCE}, 'x' * 32, algorithm='HS256')}",  # alg swap
        "Bearer " + _token().rsplit(".", 1)[0] + ".bad-signature",
    ]
    for authorization in bad:
        with pytest.raises(GoogleAuthError):
            asyncio.run(verifier.verify(authorization))


class _Play:
    """The Play Developer API behind ``httpx.MockTransport``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.subscription = _subscription(
            "SUBSCRIPTION_STATE_ACTIVE", acknowledgementState="ACKNOWLEDGEMENT_STATE_PENDING"
        )
        self.tokens_issued = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url))
        if url == "https://oauth2.googleapis.com/token":
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
            claims = jwt.decode(
                form["assertion"][0],
                KEY.public_key(),
                algorithms=["RS256"],
                audience="https://oauth2.googleapis.com/token",
            )
            assert claims["iss"] == "play-api@travelbuddy.iam.gserviceaccount.com"
            assert claims["scope"] == "https://www.googleapis.com/auth/androidpublisher"
            self.tokens_issued += 1
            return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer ya29.test"
        base = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{PACKAGE}"
        if url == f"{base}/purchases/subscriptionsv2/tokens/tok%2Fwith%2Bchars":
            return httpx.Response(200, json=self.subscription)
        if url.endswith(":acknowledge"):
            return httpx.Response(200)
        return httpx.Response(404, json={"error": {"code": 404}})


def _provider(play: _Play) -> GooglePlayProvider:
    account = ServiceAccount.from_json(
        json.dumps(
            {"client_email": "play-api@travelbuddy.iam.gserviceaccount.com", "private_key": PEM}
        )
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(play.handle))
    return GooglePlayProvider(GooglePlayApi(account, PACKAGE, client), PACKAGE)


def _claim(token: str = "tok/with+chars", **extra: Any) -> PurchaseClaim:  # noqa: S107
    values: dict[str, Any] = {
        "store": "google",
        "payload": token,
        "sku": "premium_monthly",
        "package_name": PACKAGE,
        "product_kind": "auto_renewable",
        **extra,
    }
    return PurchaseClaim(**values)


@pytest.mark.req("BILL-002", "BILL-003")
def test_subscription_purchases_are_verified_and_acknowledged() -> None:
    play = _Play()
    provider = _provider(play)

    async def run() -> None:
        tx = await provider.verify(_claim(), now=NOW)
        assert tx.provider == "google"
        assert tx.original_transaction_id == "tok/with+chars"
        assert tx.transaction_id == "GPA.1111-2222-3333-44444..1"
        assert tx.status is SubscriptionStatus.ACTIVE
        assert tx.expires_at == datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
        await provider.verify(_claim(), now=NOW)  # the access token is reused

    asyncio.run(run())
    acks = [url for method, url in play.calls if method == "POST" and "acknowledge" in url]
    assert (
        acks
        == [
            f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{PACKAGE}"
            "/purchases/subscriptions/premium_monthly/tokens/tok%2Fwith%2Bchars:acknowledge"
        ]
        * 2
    )
    assert play.tokens_issued == 1


@pytest.mark.req("BILL-003")
def test_wrong_app_sku_or_pending_payment_is_refused() -> None:
    play = _Play()
    provider = _provider(play)
    refusals = [
        _claim(package_name="com.other.app"),
        _claim(sku="premium_yearly"),  # the token is for another SKU
        _claim(token="unknown-token"),  # 404 from Play
    ]
    for claim in refusals:
        with pytest.raises(AppError) as raised:
            asyncio.run(provider.verify(claim, now=NOW))
        assert raised.value.code is ErrorCode.PURCHASE_INVALID
    play.subscription = _subscription("SUBSCRIPTION_STATE_PENDING")
    with pytest.raises(AppError) as pending:
        asyncio.run(provider.verify(_claim(), now=NOW))
    assert pending.value.code is ErrorCode.PURCHASE_INVALID


@pytest.mark.req("BILL-003")
def test_play_outages_are_retryable_not_the_users_fault() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    account = ServiceAccount(client_email="a@b.iam.gserviceaccount.com", private_key=PEM)
    client = httpx.AsyncClient(transport=httpx.MockTransport(down))
    provider = GooglePlayProvider(GooglePlayApi(account, PACKAGE, client), PACKAGE)
    with pytest.raises(AppError) as raised:
        asyncio.run(provider.verify(_claim(), now=NOW))
    assert raised.value.code is ErrorCode.SERVICE_UNAVAILABLE
