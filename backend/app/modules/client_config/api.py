"""``GET /v1/client-config``: feature flags, version policy, locales and legal versions.

Anonymous-capable. Clients must send the legal versions served here when registering; the
backend rejects any other versions with ``consent_required`` (AUTH-009).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.core.feature_flags import FeatureFlags
from app.core.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    negotiate_ui_locale,
    parse_accept_language,
)
from app.modules.client_config.catalog import catalog
from app.modules.identity.service import IdentityService

router = APIRouter(prefix="/v1", tags=["config"])

_SEMVER = r"^\d+\.\d+\.\d+$"


class LegalDocuments(BaseModel):
    model_config = ConfigDict(frozen=True)

    terms_version: str
    privacy_version: str
    terms_url: str
    privacy_url: str
    community_guidelines_url: str


class SupportContact(BaseModel):
    model_config = ConfigDict(frozen=True)

    email: str
    url: str | None


class ManifestKey(BaseModel):
    """Public key that verifies offline package manifests, matched by ``key_id`` (OFF-001)."""

    model_config = ConfigDict(frozen=True)

    key_id: str
    alg: Literal["Ed25519"]
    public_key: str  # base64 of the raw 32-byte key


class ClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_supported_version: str
    latest_version: str
    update_required: bool
    supported_locales: list[str]
    default_locale: str
    feature_flags: dict[str, bool]
    legal: LegalDocuments
    support: SupportContact
    minimum_age: int
    web_push_vapid_public_key: str | None = None
    offline_manifest_keys: list[ManifestKey] = []


def _version(value: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in value.split("."))
    return major, minor, patch


@router.get("/client-config", response_model=ClientConfig)
async def get_client_config(
    request: Request,
    platform: Literal["ios", "android", "web"],
    app_version: Annotated[str, Query(pattern=_SEMVER)],
) -> ClientConfig:
    settings: Settings = request.app.state.settings
    flags: FeatureFlags = request.app.state.feature_flags
    identity: IdentityService = request.app.state.identity_service
    legal = identity.legal_requirements()
    vapid = getattr(request.app.state, "web_push_vapid", None)
    offline = getattr(request.app.state, "offline_package_service", None)
    site = settings.public_site_url.rstrip("/")
    # The web is always deployed at the current version; only native apps can be outdated.
    outdated = platform != "web" and _version(app_version) < _version(
        settings.min_supported_app_version
    )
    return ClientConfig(
        min_supported_version=settings.min_supported_app_version,
        latest_version=settings.latest_app_version,
        update_required=outdated,
        supported_locales=list(SUPPORTED_LOCALES),
        default_locale=DEFAULT_LOCALE,
        feature_flags=flags.snapshot(),
        legal=LegalDocuments(
            terms_version=legal.terms_version,
            privacy_version=legal.privacy_version,
            terms_url=f"{site}/legal/terms",
            privacy_url=f"{site}/legal/privacy",
            community_guidelines_url=f"{site}/legal/community-guidelines",
        ),
        support=SupportContact(email=settings.support_email, url=settings.support_url or None),
        minimum_age=legal.minimum_age,
        web_push_vapid_public_key=vapid.public_key if vapid is not None else None,
        offline_manifest_keys=[
            ManifestKey.model_validate(key)
            for key in (offline.public_keys() if offline is not None else [])
        ],
    )


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    label: str
    group: str | None = None


class TravelInterestCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    travel_styles: list[CatalogEntry]
    interests: list[CatalogEntry]


@router.get("/catalog/travel-interests", response_model=TravelInterestCatalog)
async def get_travel_interest_catalog(request: Request) -> TravelInterestCatalog:
    """Travel styles and suggested interests, labelled in the best UI locale (PROF-004, I18N-003);
    no sign-in needed (onboarding shows it before the profile exists)."""
    tags = parse_accept_language(request.headers.get("accept-language"))
    locale = negotiate_ui_locale(tags[0] if tags else None)
    return TravelInterestCatalog.model_validate(catalog(locale))
