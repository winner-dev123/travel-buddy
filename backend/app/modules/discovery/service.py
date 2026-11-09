"""``GET /v1/travelers/discover`` (BL-2.03; DISC-001/003/004/005/006/007/008, T-LOC-01..04).

Reciprocity: only travellers who are themselves discoverable may browse, and only where they are
visible (``here_now``) or share an upcoming trip (``upcoming``). Invisible users neither appear
nor browse. The query takes a destination, never coordinates, and cards carry no distances,
coordinates or activity times. Blocked users never appear in either direction.
"""

from __future__ import annotations

import random
import secrets
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.time import Clock
from app.modules.connections import service as connections
from app.modules.destinations import service as destinations
from app.modules.discovery.domain import Traits, bucket, order, score
from app.modules.discovery.schemas import Presence, Shared, TravelerCard
from app.modules.identity import service as identity
from app.modules.location import service as location
from app.modules.profiles import service as profiles
from app.modules.trust_safety import service as trust_safety

MAX_RESULTS = 50
BIO_SNIPPET = 140


@dataclass(frozen=True, slots=True)
class DiscoverParams:
    scope: Literal["here_now", "upcoming"] = "here_now"
    destination_id: uuid.UUID | None = None
    travel_start_date: date | None = None
    travel_end_date: date | None = None
    travel_styles: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Candidate:
    user_id: uuid.UUID
    destination_id: uuid.UUID
    area_id: uuid.UUID | None
    start: date | None
    end: date | None


def _disabled(message: str) -> AppError:
    return AppError(ErrorCode.DISCOVERY_DISABLED, message)


def _traits(
    profile: profiles.DiscoveryProfile | None, start: date | None, end: date | None
) -> Traits:
    if profile is None:
        return Traits(start=start, end=end)
    return Traits(
        interests=frozenset(profile.interests),
        travel_styles=frozenset(profile.travel_styles),
        languages=frozenset(profile.languages_spoken),
        start=start,
        end=end,
    )


class DiscoveryService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        rng: random.Random | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._rng = rng

    async def discover(
        self, viewer: uuid.UUID, params: DiscoverParams, *, preferences: list[str]
    ) -> list[TravelerCard]:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            settings = await location.require_discovery(session, viewer)
            mine = await location.active_session(session, viewer)
            if params.scope == "here_now":
                if mine is None or mine.visibility != "visible":
                    raise _disabled("Share your city in discovery (visible) to see who's here.")
                destination = params.destination_id or mine.destination_id
                if destination != mine.destination_id:
                    raise _disabled("You can only browse the city where you're visible.")
                viewer_start, viewer_end = mine.travel_start_date, mine.travel_end_date
                candidates = [
                    _Candidate(
                        s.user_id,
                        s.destination_id,
                        s.area_destination_id,
                        s.travel_start_date,
                        s.travel_end_date,
                    )
                    for s in await location.visible_sessions_in(
                        session, destination, exclude=viewer
                    )
                ]
            else:
                if params.destination_id is None:
                    raise AppError(ErrorCode.VALIDATION_FAILED, "Choose a destination.")
                destination = params.destination_id
                own = await location.shared_upcoming(session, viewer, destination)
                visible_here = (
                    mine is not None
                    and mine.visibility == "visible"
                    and mine.destination_id == destination
                )
                if own is None and not visible_here:
                    raise _disabled(
                        "Share an upcoming trip to this destination to see who's going."
                    )
                viewer_start = params.travel_start_date or (own.start_date if own else None)
                viewer_end = params.travel_end_date or (own.end_date if own else None)
                candidates = [
                    _Candidate(r.user_id, r.destination_id, None, r.start_date, r.end_date)
                    for r in await location.shared_upcoming_in(
                        session, destination, exclude=viewer, start=viewer_start, end=viewer_end
                    )
                ]

            hidden = await trust_safety.blocked_ids(session, viewer)
            candidates = [c for c in candidates if c.user_id not in hidden]
            people = await profiles.discovery_profiles(
                session, [viewer, *(c.user_id for c in candidates)]
            )
            eligible = []
            for candidate in candidates:
                profile = people.get(candidate.user_id)
                if profile is None or not profile.discoverable:
                    continue
                if not await identity.is_active(session, candidate.user_id):
                    continue
                if params.travel_styles and not set(params.travel_styles) & set(
                    profile.travel_styles
                ):
                    continue
                if params.interests and not {i.lower() for i in params.interests} & set(
                    profile.interests
                ):
                    continue
                if params.languages and not set(params.languages) & set(profile.languages_spoken):
                    continue
                eligible.append(candidate)

            me = _traits(people.get(viewer), viewer_start, viewer_end)
            scores = {
                c.user_id: score(me, _traits(people[c.user_id], c.start, c.end)) for c in eligible
            }
            declined = await connections.declined_requesters(session, viewer)
            rng = self._rng or random.Random(secrets.randbits(64))  # noqa: S311 - ordering only
            ranked = order(
                eligible,
                score_of=lambda c: scores[c.user_id],
                deprioritized=lambda c: c.user_id in declined,
                rng=rng,
            )[:MAX_RESULTS]

            summaries = await profiles.authors(session, [c.user_id for c in ranked])
            area_ids = {c.area_id for c in ranked if c.area_id}
            places = await destinations.summaries_by_id(
                session, [destination, *area_ids], preferences
            )
            cards: list[TravelerCard] = []
            for candidate in ranked:
                profile = people[candidate.user_id]
                author = summaries.get(candidate.user_id)
                if author is None:
                    continue
                relationship, can_request = await connections.relationship_between(
                    session, viewer, candidate.user_id, now
                )
                both_neighborhood = (
                    settings.granularity == "neighborhood" and profile.granularity == "neighborhood"
                )
                shown = not profile.restricted
                cards.append(
                    TravelerCard.model_validate(
                        {
                            "user": profiles.user_summary(author),
                            "bio_snippet": (profile.bio or "")[:BIO_SNIPPET] or None
                            if shown
                            else None,
                            "travel_styles": profile.travel_styles if shown else [],
                            "interests": profile.interests if shown else [],
                            "languages_spoken": profile.languages_spoken if shown else [],
                            "presence": Presence.model_validate(
                                {
                                    "kind": params.scope,
                                    "destination": places[destination],
                                    "area": places.get(candidate.area_id)
                                    if both_neighborhood and candidate.area_id
                                    else None,
                                    "travel_start_date": candidate.start,
                                    "travel_end_date": candidate.end,
                                }
                            ),
                            "shared": Shared(
                                travel_styles=sorted(me.travel_styles & set(profile.travel_styles))
                                if shown
                                else [],
                                interests=sorted(me.interests & set(profile.interests))
                                if shown
                                else [],
                                languages=sorted(me.languages & set(profile.languages_spoken))
                                if shown
                                else [],
                            ),
                            "compatibility": bucket(scores[candidate.user_id]),
                            "relationship": relationship,
                            "can_request_connection": can_request,
                        }
                    )
                )
            return cards
