"""Planner: Plans routes - see services/plans.py for the actual logic."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from ucenik.core.permissions import require_subject_owner
from ucenik.core.security import get_current_user
from ucenik.models.plans import Plan
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.services import plans as plans_service
from ucenik.services.plans import get_plan_or_404 as get_plan

router = APIRouter(prefix="/subjects/{subject_id}/plans", tags=["planner"])


class CreatePlanRequest(BaseModel):
    title: str
    description: str | None = None


class UpdatePlanRequest(BaseModel):
    title: str | None = None
    description: str | None = None


class PlanPublic(BaseModel):
    id: str
    subject_id: str
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime


def _to_public(plan: Plan) -> PlanPublic:
    return PlanPublic(
        id=str(plan.id),
        subject_id=plan.subject_id,
        title=plan.title,
        description=plan.description,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@router.post("", response_model=PlanPublic, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: CreatePlanRequest,
    subject: Annotated[Subject, Depends(require_subject_owner)],
    user: Annotated[User, Depends(get_current_user)],
) -> PlanPublic:
    plan = await plans_service.create_plan(subject, user, payload.title, payload.description)
    return _to_public(plan)


@router.get("", response_model=list[PlanPublic])
async def list_plans(subject: Annotated[Subject, Depends(require_subject_owner)]) -> list[PlanPublic]:
    plans = await plans_service.list_plans(subject)
    return [_to_public(p) for p in plans]


@router.get("/{plan_id}", response_model=PlanPublic)
async def get_plan_details(
    plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> PlanPublic:
    return _to_public(plan)


@router.patch("/{plan_id}", response_model=PlanPublic)
async def update_plan(
    payload: UpdatePlanRequest,
    plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> PlanPublic:
    plan = await plans_service.update_plan(plan, payload.title, payload.description)
    return _to_public(plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> None:
    await plans_service.delete_plan(plan)
