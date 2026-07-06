"""Salon routes — browse archived salons and transcripts."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select, func

from koinonia_db.models.salon import SalonSessionRow, Participant, Segment

router = APIRouter()


@router.get("/")
async def salon_list(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        total = (await session.execute(
            select(func.count(SalonSessionRow.id))
        )).scalar() or 0
        stmt = (
            select(SalonSessionRow)
            .order_by(SalonSessionRow.date.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        sessions = result.scalars().all()
    prev_offset = max(0, offset - limit) if offset > 0 else None
    next_offset = offset + limit if offset + limit < total else None
    return templates.TemplateResponse(request=request, name="salons/list.html", context={
        "request": request,
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset,
        "prev_offset": prev_offset,
        "next_offset": next_offset,
    })


@router.get("/{session_id}")
async def salon_detail(request: Request, session_id: int):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        salon = await session.get(SalonSessionRow, session_id)
        if not salon:
            raise HTTPException(status_code=404, detail="Salon not found")
        stmt_p = select(Participant).where(Participant.session_id == session_id)
        participants = (await session.execute(stmt_p)).scalars().all()
        stmt_s = select(Segment).where(
            Segment.session_id == session_id
        ).order_by(Segment.start_seconds)
        segments = (await session.execute(stmt_s)).scalars().all()
    return templates.TemplateResponse(request=request, name="salons/detail.html", context={
        "request": request,
        "salon": salon,
        "participants": participants,
        "segments": segments,
    })
