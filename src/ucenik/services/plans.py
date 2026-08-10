"""Planner: Plans (§Phase 7). A Plan is an ordered container of Lectures
(services/lectures.py) for one subject. Teacher/admin only end to end - no
student access to any Planner content in this phase (see docs/roadmap.md
and docs/frontend-spec.md: this is a drafting tool for the teacher, not
something published to students yet).
"""

from datetime import UTC, datetime

from beanie.operators import In

from ucenik.errors.service import NotFoundError, parse_object_id
from ucenik.models.lecture_versions import LectureVersion
from ucenik.models.lectures import Lecture
from ucenik.models.plans import Plan
from ucenik.models.subjects import Subject
from ucenik.models.users import User


async def get_plan_or_404(subject_id: str, plan_id: str) -> Plan:
    """Fetches a plan and verifies it belongs to `subject_id` - same
    cross-subject-probing guard as core/permissions.py's get_document.
    """
    plan = await Plan.get(parse_object_id("Plan", plan_id))
    if plan is None or plan.subject_id != subject_id:
        raise NotFoundError("Plan", plan_id)
    return plan


async def create_plan(subject: Subject, teacher: User, title: str, description: str | None) -> Plan:
    plan = Plan(subject_id=str(subject.id), teacher_id=str(teacher.id), title=title, description=description)
    await plan.insert()
    return plan


async def list_plans(subject: Subject) -> list[Plan]:
    return await Plan.find(Plan.subject_id == str(subject.id)).to_list()


async def update_plan(plan: Plan, title: str | None, description: str | None) -> Plan:
    if title is not None:
        plan.title = title
    if description is not None:
        plan.description = description
    plan.updated_at = datetime.now(UTC)
    await plan.save()
    return plan


async def delete_plan(plan: Plan) -> None:
    lecture_ids = [str(lecture.id) for lecture in await Lecture.find(Lecture.plan_id == str(plan.id)).to_list()]
    if lecture_ids:
        await LectureVersion.find(In(LectureVersion.lecture_id, lecture_ids)).delete()
        await Lecture.find(Lecture.plan_id == str(plan.id)).delete()
    await plan.delete()
