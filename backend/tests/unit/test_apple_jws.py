"""App Store signed data verification (BILL-003, BILL-007; ADR-0017)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError
from app.modules.billing.apple import (
    AppleJWSVerifier,
    AppleSignatureError,
    AppleStoreProvider,
    notification_event,
)
from app.modules.billing.domain import StoreEvent, SubscriptionStatus
from app.modules.billing.providers import PurchaseClaim
from tests.apple_chain import AppleChain, transaction

BUNDLE = "app.travelbuddy.test"


def _verifier(chain: AppleChain) -> AppleJWSVerifier:
    return AppleJWSVerifier(root_fingerprints=[chain.root_fingerprint], bundle_id=BUNDLE)


def _now() -> datetime:
    return datetime.now(tz=UTC)


@pytest.mark.req("BILL-003")
def test_a_genuine_transaction_verifies_and_maps_to_a_store_transaction() -> None:
    chain = AppleChain.create()
    signed = chain.sign(
        transaction(bundle_id=BUNDLE, product_id="premium.monthly", original_transaction_id="1000")
    )
    payload = _verifier(chain).decode(signed, now=_now())
    assert payload["productId"] == "premium.monthly"
    tx = asyncio.run(
        AppleStoreProvider(_verifier(chain)).verify(
            PurchaseClaim(store="apple", payload=signed), now=_now()
        )
    )
    assert (tx.provider, tx.sku, tx.original_transaction_id) == ("apple", "premium.monthly", "1000")
    assert (tx.status, tx.environment) == (SubscriptionStatus.ACTIVE, "sandbox")


@pytest.mark.req("BILL-003")
def test_states_follow_expiry_and_revocation() -> None:
    chain = AppleChain.create()
    provider = AppleStoreProvider(_verifier(chain))
    expired = chain.sign(
        transaction(
            bundle_id=BUNDLE,
            product_id="p",
            original_transaction_id="1",
            expires_in=timedelta(days=-1),
        )
    )
    revoked = chain.sign(
        transaction(bundle_id=BUNDLE, product_id="p", original_transaction_id="2", revoked=True)
    )
    claim = lambda jws: PurchaseClaim(store="apple", payload=jws)  # noqa: E731
    expired_tx = asyncio.run(provider.verify(claim(expired), now=_now()))
    revoked_tx = asyncio.run(provider.verify(claim(revoked), now=_now()))
    assert expired_tx.status is SubscriptionStatus.EXPIRED
    assert revoked_tx.status is SubscriptionStatus.REVOKED


@pytest.mark.req("BILL-003", "BILL-007")
def test_forgeries_are_rejected() -> None:
    chain = AppleChain.create()
    genuine = chain.sign(transaction(bundle_id=BUNDLE, product_id="p", original_transaction_id="1"))
    header, _payload, signature = genuine.split(".")
    tampered = f"{header}.{chain.sign({'productId': 'free.lifetime'}).split('.')[1]}.{signature}"
    with pytest.raises(AppleSignatureError):
        _verifier(chain).decode(tampered, now=_now())  # signature no longer matches
    impostor = AppleChain.create()  # a chain we did not pin
    with pytest.raises(AppleSignatureError):
        _verifier(chain).decode(
            impostor.sign(
                transaction(bundle_id=BUNDLE, product_id="p", original_transaction_id="1")
            ),
            now=_now(),
        )
    unmarked = AppleChain.create(leaf_marker=False)
    with pytest.raises(AppleSignatureError):
        _verifier(unmarked).decode(
            unmarked.sign(
                transaction(bundle_id=BUNDLE, product_id="p", original_transaction_id="1")
            ),
            now=_now(),
        )
    with pytest.raises(AppleSignatureError):
        _verifier(chain).decode(genuine, now=_now() + timedelta(days=400))  # leaf expired
    with pytest.raises(AppleSignatureError):
        _verifier(chain).decode("not.a-jws", now=_now())
    other_app = chain.sign(
        transaction(bundle_id="com.other", product_id="p", original_transaction_id="1")
    )
    with pytest.raises(AppError):
        asyncio.run(
            AppleStoreProvider(_verifier(chain)).verify(
                PurchaseClaim(store="apple", payload=other_app), now=_now()
            )
        )


@pytest.mark.req("BILL-007", "BILL-008")
@pytest.mark.parametrize(
    ("kind", "subtype", "event"),
    [
        ("SUBSCRIBED", "INITIAL_BUY", StoreEvent.RENEWED),
        ("DID_RENEW", None, StoreEvent.RENEWED),
        ("DID_RENEW", "BILLING_RECOVERY", StoreEvent.RECOVERED),
        ("DID_CHANGE_RENEWAL_STATUS", "AUTO_RENEW_DISABLED", StoreEvent.AUTO_RENEW_OFF),
        ("DID_CHANGE_RENEWAL_STATUS", "AUTO_RENEW_ENABLED", StoreEvent.AUTO_RENEW_ON),
        ("DID_FAIL_TO_RENEW", "GRACE_PERIOD", StoreEvent.GRACE),
        ("DID_FAIL_TO_RENEW", None, StoreEvent.BILLING_RETRY),
        ("GRACE_PERIOD_EXPIRED", None, StoreEvent.BILLING_RETRY),
        ("EXPIRED", "VOLUNTARY", StoreEvent.EXPIRED),
        ("REFUND", None, StoreEvent.REFUNDED),
        ("REVOKE", None, StoreEvent.REFUNDED),
        ("PRICE_INCREASE", "PENDING", None),
        ("TEST", None, None),
    ],
)
def test_notification_types_map_to_store_events(
    kind: str, subtype: str | None, event: StoreEvent | None
) -> None:
    assert notification_event(kind, subtype) is event
