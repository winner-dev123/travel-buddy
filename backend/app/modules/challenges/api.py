"""``/v1/groups/{id}/challenges``, ``/v1/challenges/{id}/…``, my rewards and badges
(BL-5.01..5.07)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.ratelimit.http import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.challenges.domain import STATUSES
from app.modules.challenges.schemas import (
    AcceptedAnswerList,
    CancelRequest,
    ChallengeDisputeOut,
    ChallengeDisputePage,
    ChallengeManagerView,
    ChallengeOut,
    ChallengePage,
    ChallengeResults,
    ChallengeSubmissionOut,
    ChallengeSubmissionPage,
    ChallengeTeamOut,
    ChallengeTeamPage,
    ChallengeWinnerOut,
    CreateChallengeRequest,
    CreateDisputeRequest,
    CreateTeamRequest,
    EvaluationStatus,
    FulfillmentTransitionRequest,
    HintList,
    JudgeSubmissionRequest,
    MyRewardPage,
    ResolveDisputeRequest,
    RewardFulfillmentOut,
    RewardFulfillmentPage,
    SubmissionResult,
    SubmitAnswerRequest,
    UpdateChallengeRequest,
    UserBadgeList,
    WinnerActionRequest,
)
from app.modules.challenges.service import ChallengeService

router = APIRouter(tags=["challenges"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def _service(request: Request) -> ChallengeService:
    service: ChallengeService = request.app.state.challenge_service
    return service


def _tagged(view: ChallengeManagerView, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        view.model_dump(mode="json"), status_code=status_code, headers={"ETag": f'"{view.version}"'}
    )


def _statuses(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values = tuple(dict.fromkeys(v.strip() for v in raw.split(",") if v.strip()))
    unknown = [v for v in values if v not in STATUSES]
    if unknown:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "Unknown challenge status.",
            errors=[FieldError(field="/status", code="enum", message=", ".join(unknown))],
        )
    return values


@router.get("/v1/groups/{group_id}/challenges", response_model=ChallengePage)
async def list_group_challenges(
    group_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    status_filter: Annotated[str | None, Query(alias="status", max_length=100)] = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ChallengePage:
    return await _service(request).list_for_group(
        principal.user_id, group_id, statuses=_statuses(status_filter), cursor=cursor, limit=limit
    )


@router.post(
    "/v1/groups/{group_id}/challenges",
    status_code=status.HTTP_201_CREATED,
    response_model=ChallengeManagerView,
)
async def create_challenge(
    group_id: uuid.UUID,
    body: CreateChallengeRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    view = await _service(request).create(
        principal, group_id, body, idempotency_key=idempotency_key
    )
    return _tagged(view, status.HTTP_201_CREATED)


@router.get("/v1/challenges/{challenge_id}", response_model=ChallengeOut)
async def get_challenge(
    challenge_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> ChallengeOut:
    return await _service(request).get(principal.user_id, challenge_id)


@router.patch("/v1/challenges/{challenge_id}", response_model=ChallengeManagerView)
async def update_challenge(
    challenge_id: uuid.UUID,
    body: UpdateChallengeRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).update(principal.user_id, challenge_id, body, if_match=if_match)
    )


@router.get("/v1/challenges/{challenge_id}/manage", response_model=ChallengeManagerView)
async def get_challenge_manager_view(
    challenge_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    return _tagged(await _service(request).manage(principal.user_id, challenge_id))


@router.post("/v1/challenges/{challenge_id}/publish", response_model=ChallengeManagerView)
async def publish_challenge(
    challenge_id: uuid.UUID, request: Request, principal: CurrentPrincipal, if_match: IfMatch = None
) -> JSONResponse:
    return _tagged(
        await _service(request).publish(principal.user_id, challenge_id, if_match=if_match)
    )


@router.post("/v1/challenges/{challenge_id}/cancel", response_model=ChallengeManagerView)
async def cancel_challenge(
    challenge_id: uuid.UUID, body: CancelRequest, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    return _tagged(await _service(request).cancel(principal.user_id, challenge_id, body.reason))


@router.get("/v1/challenges/{challenge_id}/hints", response_model=HintList)
async def list_challenge_hints(
    challenge_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> HintList:
    return await _service(request).hints(principal.user_id, challenge_id)


@router.get("/v1/challenges/{challenge_id}/teams", response_model=ChallengeTeamPage)
async def list_challenge_teams(
    challenge_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ChallengeTeamPage:
    return await _service(request).list_teams(
        principal.user_id, challenge_id, cursor=cursor, limit=limit
    )


@router.post(
    "/v1/challenges/{challenge_id}/teams",
    status_code=status.HTTP_201_CREATED,
    response_model=ChallengeTeamOut,
)
async def create_challenge_team(
    challenge_id: uuid.UUID, body: CreateTeamRequest, request: Request, principal: CurrentPrincipal
) -> ChallengeTeamOut:
    return await _service(request).create_team(principal.user_id, challenge_id, body)


@router.post("/v1/challenges/{challenge_id}/teams/{team_id}/join", response_model=ChallengeTeamOut)
async def join_challenge_team(
    challenge_id: uuid.UUID, team_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> ChallengeTeamOut:
    return await _service(request).join_team(principal.user_id, challenge_id, team_id)


@router.get("/v1/challenges/{challenge_id}/submissions", response_model=ChallengeSubmissionPage)
async def list_challenge_submissions(
    challenge_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    scope: Literal["mine", "all"] = "mine",
    evaluation_status: EvaluationStatus | None = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ChallengeSubmissionPage:
    return await _service(request).submissions(
        principal.user_id,
        challenge_id,
        scope=scope,
        evaluation_status=evaluation_status,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/v1/challenges/{challenge_id}/submissions",
    status_code=status.HTTP_201_CREATED,
    response_model=SubmissionResult,
    openapi_extra=rate_limited("submission"),
)
async def submit_challenge_answer(
    challenge_id: uuid.UUID,
    body: SubmitAnswerRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> SubmissionResult:
    return await _service(request).submit(
        principal.user_id, challenge_id, body, idempotency_key=idempotency_key
    )


@router.post(
    "/v1/challenges/{challenge_id}/submissions/{submission_id}/judgement",
    response_model=ChallengeSubmissionOut,
)
async def judge_challenge_submission(
    challenge_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: JudgeSubmissionRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> ChallengeSubmissionOut:
    return await _service(request).judge_submission(
        principal.user_id, challenge_id, submission_id, body
    )


@router.get(
    "/v1/challenges/{challenge_id}/answers",
    response_model=AcceptedAnswerList,
    openapi_extra=rate_limited("sensitive"),
)
async def get_challenge_answers(
    challenge_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    answers = await _service(request).answers(principal.user_id, challenge_id)
    return JSONResponse(answers.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.get("/v1/challenges/{challenge_id}/results", response_model=ChallengeResults)
async def get_challenge_results(
    challenge_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> ChallengeResults:
    return await _service(request).results(principal.user_id, challenge_id)


@router.post("/v1/challenges/{challenge_id}/results/publish", response_model=ChallengeResults)
async def publish_challenge_results(
    challenge_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> ChallengeResults:
    return await _service(request).publish_results(principal.user_id, challenge_id)


@router.post(
    "/v1/challenges/{challenge_id}/winners/{winner_id}/{action}",
    response_model=ChallengeWinnerOut,
)
async def update_challenge_winner(
    challenge_id: uuid.UUID,
    winner_id: uuid.UUID,
    action: Literal["confirm", "revoke"],
    request: Request,
    principal: CurrentPrincipal,
    body: WinnerActionRequest | None = None,
) -> ChallengeWinnerOut:
    return await _service(request).winner_action(
        principal.user_id, challenge_id, winner_id, action, body.note if body else None
    )


@router.get("/v1/challenges/{challenge_id}/disputes", response_model=ChallengeDisputePage)
async def list_challenge_disputes(
    challenge_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ChallengeDisputePage:
    return await _service(request).list_disputes(
        principal.user_id, challenge_id, cursor=cursor, limit=limit
    )


@router.post(
    "/v1/challenges/{challenge_id}/disputes",
    status_code=status.HTTP_201_CREATED,
    response_model=ChallengeDisputeOut,
    openapi_extra=rate_limited("sensitive"),
)
async def create_challenge_dispute(
    challenge_id: uuid.UUID,
    body: CreateDisputeRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> ChallengeDisputeOut:
    return await _service(request).create_dispute(principal.user_id, challenge_id, body)


@router.post(
    "/v1/challenges/{challenge_id}/disputes/{dispute_id}/resolve",
    response_model=ChallengeDisputeOut,
)
async def resolve_challenge_dispute(
    challenge_id: uuid.UUID,
    dispute_id: uuid.UUID,
    body: ResolveDisputeRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> ChallengeDisputeOut:
    return await _service(request).resolve_dispute(
        principal.user_id, challenge_id, dispute_id, body
    )


@router.get("/v1/challenges/{challenge_id}/fulfillments", response_model=RewardFulfillmentPage)
async def list_reward_fulfillments(
    challenge_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RewardFulfillmentPage:
    return await _service(request).list_fulfillments(
        principal.user_id, challenge_id, cursor=cursor, limit=limit
    )


@router.post(
    "/v1/challenges/{challenge_id}/fulfillments/{fulfillment_id}/transitions",
    response_model=RewardFulfillmentOut,
)
async def transition_reward_fulfillment(
    challenge_id: uuid.UUID,
    fulfillment_id: uuid.UUID,
    body: FulfillmentTransitionRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> RewardFulfillmentOut:
    return await _service(request).transition_fulfillment(
        principal.user_id, challenge_id, fulfillment_id, body
    )


@router.get("/v1/users/me/rewards", response_model=MyRewardPage)
async def list_my_rewards(
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    page = await _service(request).my_rewards(principal.user_id, cursor=cursor, limit=limit)
    return JSONResponse(page.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.get("/v1/users/{user_id}/badges", response_model=UserBadgeList)
async def list_user_badges(
    user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> UserBadgeList:
    return await _service(request).user_badges(principal.user_id, user_id)
