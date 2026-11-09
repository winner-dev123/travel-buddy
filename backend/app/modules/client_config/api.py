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
from app.modules.identity.service import IdentityService

router = APIRouter(prefix="/v1", tags=["config"])

SUPPORTED_LOCALES = ["en", "es", "pt-BR", "fr", "de"]
DEFAULT_LOCALE = "en"
_SEMVER = r"^\d+\.\d+\.\d+$"


class LegalDocuments(BaseModel):
    model_config = ConfigDict(frozen=True)

    terms_version: str
    privacy_version: str
    terms_url: str
    privacy_url: str
    community_guidelines_url: str


class ClientConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_supported_version: str
    latest_version: str
    update_required: bool
    supported_locales: list[str]
    default_locale: str
    feature_flags: dict[str, bool]
    legal: LegalDocuments
    minimum_age: int
    web_push_vapid_public_key: str | None = None  # Web Push lands with BL-3.16


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
    site = settings.public_site_url.rstrip("/")
    # The web is always deployed at the current version; only native apps can be outdated.
    outdated = platform != "web" and _version(app_version) < _version(
        settings.min_supported_app_version
    )
    return ClientConfig(
        min_supported_version=settings.min_supported_app_version,
        latest_version=settings.latest_app_version,
        update_required=outdated,
        supported_locales=SUPPORTED_LOCALES,
        default_locale=DEFAULT_LOCALE,
        feature_flags=flags.snapshot(),
        legal=LegalDocuments(
            terms_version=legal.terms_version,
            privacy_version=legal.privacy_version,
            terms_url=f"{site}/legal/terms",
            privacy_url=f"{site}/legal/privacy",
            community_guidelines_url=f"{site}/legal/community-guidelines",
        ),
        minimum_age=legal.minimum_age,
    )
