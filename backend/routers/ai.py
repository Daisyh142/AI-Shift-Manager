from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..db import get_session
from ..schemas import (
    AIActionExecuteRequest,
    AIActionExecuteResponse,
    AIDecisionFeedbackRequest,
    AIKpiResponse,
    AIChatRequest,
    AIChatResponse,
)
from ..services.ai_service import (
    execute_confirmed_action,
    generate_chat_response,
    get_ai_kpis,
    log_decision_feedback,
)
from .auth import require_owner

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat", response_model=AIChatResponse)
def chat_with_ai(
    request: AIChatRequest,
    owner=Depends(require_owner),
    session: Session = Depends(get_session),
) -> AIChatResponse:
    return generate_chat_response(session=session, owner_user_id=owner.id, request=request)


@router.post("/execute-action", response_model=AIActionExecuteResponse)
def ai_execute_action(
    request: AIActionExecuteRequest,
    owner=Depends(require_owner),
    session: Session = Depends(get_session),
) -> AIActionExecuteResponse:
    return execute_confirmed_action(session=session, owner_user_id=owner.id, request=request)


@router.post("/feedback", response_model=dict)
def ai_feedback(
    request: AIDecisionFeedbackRequest,
    owner=Depends(require_owner),
    session: Session = Depends(get_session),
) -> dict:
    log_decision_feedback(session=session, owner_user_id=owner.id, request=request)
    return {"status": "logged"}


@router.get("/kpis", response_model=AIKpiResponse)
def ai_kpis(
    days: int = Query(default=30, ge=1, le=365),
    _owner=Depends(require_owner),
    session: Session = Depends(get_session),
) -> AIKpiResponse:
    return get_ai_kpis(session=session, days=days)
