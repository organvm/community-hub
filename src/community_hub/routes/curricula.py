"""Curricula routes — browse reading group curricula and sessions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select, func

from koinonia_db.models.reading import Curriculum, ReadingSessionRow, DiscussionQuestion, Guide

router = APIRouter()


@router.get("/")
async def curricula_list(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        total = (await session.execute(
            select(func.count(Curriculum.id))
        )).scalar() or 0
        stmt = select(Curriculum).order_by(Curriculum.id).limit(limit).offset(offset)
        result = await session.execute(stmt)
        curricula = result.scalars().all()
    prev_offset = max(0, offset - limit) if offset > 0 else None
    next_offset = offset + limit if offset + limit < total else None
    return templates.TemplateResponse(request=request, name="curricula/list.html", context={
        "request": request,
        "curricula": curricula,
        "total": total,
        "limit": limit,
        "offset": offset,
        "prev_offset": prev_offset,
        "next_offset": next_offset,
    })


@router.get("/{curriculum_id}")
async def curriculum_detail(request: Request, curriculum_id: int):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        curriculum = await session.get(Curriculum, curriculum_id)
        if not curriculum:
            raise HTTPException(status_code=404, detail="Curriculum not found")
        stmt = select(ReadingSessionRow).where(
            ReadingSessionRow.curriculum_id == curriculum_id
        ).order_by(ReadingSessionRow.week)
        sessions = (await session.execute(stmt)).scalars().all()
    return templates.TemplateResponse(request=request, name="curricula/detail.html", context={
        "request": request,
        "curriculum": curriculum,
        "sessions": sessions,
    })


@router.get("/{curriculum_id}/sessions/{session_id}")
async def session_detail(request: Request, curriculum_id: int, session_id: int):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        reading_session = await session.get(ReadingSessionRow, session_id)
        if not reading_session or reading_session.curriculum_id != curriculum_id:
            raise HTTPException(status_code=404, detail="Session not found")
        stmt_q = select(DiscussionQuestion).where(
            DiscussionQuestion.session_id == session_id
        )
        questions = (await session.execute(stmt_q)).scalars().all()
        stmt_g = select(Guide).where(Guide.session_id == session_id)
        guide = (await session.execute(stmt_g)).scalar()
    return templates.TemplateResponse(request=request, name="curricula/session.html", context={
        "request": request,
        "reading_session": reading_session,
        "questions": questions,
        "guide": guide,
    })
