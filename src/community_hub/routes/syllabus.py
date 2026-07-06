"""Syllabus routes — generate and view personalized learning paths."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select

from koinonia_db.models.syllabus import LearnerProfileRow, LearningPathRow, LearningModuleRow
from koinonia_db.syllabus_service import generate_learning_path

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/syllabus")
async def syllabus_form(request: Request):
    """Show the syllabus generation form."""
    templates = request.app.state.templates
    return templates.TemplateResponse(request=request, name="syllabus/form.html", context={"request": request})


@router.post("/syllabus/generate")
@limiter.limit("10/minute")
async def syllabus_generate(request: Request):
    """Generate a learning path from form submission."""
    templates = request.app.state.templates
    form = await request.form()
    organs = [str(o) for o in form.getlist("organs") if isinstance(o, str)]
    level_raw = form.get("level", "beginner")
    level = str(level_raw) if isinstance(level_raw, str) else "beginner"
    name_raw = form.get("name", "anonymous")
    name = str(name_raw) if isinstance(name_raw, str) else "anonymous"

    if not organs:
        return templates.TemplateResponse(request=request, name="syllabus/form.html", context={
            "request": request,
            "error": "Select at least one organ.",
        })

    async with request.app.state.db() as session:
        path = await generate_learning_path(session, organs, level, name)

    return templates.TemplateResponse(request=request, name="syllabus/path.html", context={
        "request": request,
        "path": path,
    })


@router.get("/syllabus/{path_id}")
async def syllabus_view(request: Request, path_id: str):
    """View a previously generated learning path."""
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        stmt = select(LearningPathRow).where(LearningPathRow.path_id == path_id)
        path_row = (await session.execute(stmt)).scalar_one_or_none()
        if not path_row:
            raise HTTPException(status_code=404, detail="Learning path not found")

        learner = await session.get(LearnerProfileRow, path_row.learner_id)
        modules_stmt = select(LearningModuleRow).where(
            LearningModuleRow.path_id == path_row.id
        ).order_by(LearningModuleRow.seq)
        modules = (await session.execute(modules_stmt)).scalars().all()

    path = {
        "path_id": path_row.path_id,
        "title": path_row.title,
        "organs": learner.organs_of_interest if learner else [],
        "level": learner.level if learner else "beginner",
        "total_hours": path_row.total_hours,
        "modules": [
            {
                "module_id": m.module_id,
                "title": m.title,
                "organ": m.organ,
                "difficulty": m.difficulty,
                "readings": m.readings or [],
                "questions": m.questions or [],
                "estimated_hours": m.estimated_hours,
            }
            for m in modules
        ],
    }

    return templates.TemplateResponse(request=request, name="syllabus/path.html", context={
        "request": request,
        "path": path,
    })


@router.get("/api/syllabus/generate")
@limiter.limit("20/minute")
async def api_syllabus_generate(
    request: Request,
    organs: str = "I",
    level: str = "beginner",
    name: str = "api-user",
):
    """JSON API — generate a learning path. Organs as comma-separated string."""
    organ_list = [o.strip() for o in organs.split(",") if o.strip()]
    if not organ_list:
        return {"error": "Provide at least one organ code (e.g., organs=I,II)"}

    valid_levels = {"beginner", "intermediate", "advanced"}
    if level not in valid_levels:
        return {"error": f"Level must be one of {valid_levels}"}

    async with request.app.state.db() as session:
        path = await generate_learning_path(session, organ_list, level, name)

    return path
