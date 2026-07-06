"""Community routes — events, contributors, stats."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, func

from koinonia_db.models.community import Event, Contributor, Contribution
from koinonia_db.models.salon import SalonSessionRow, TaxonomyNodeRow
from koinonia_db.models.reading import Curriculum, Entry

router = APIRouter()


@router.get("/events")
async def events_list(request: Request):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        stmt = select(Event).order_by(Event.date.desc())
        events = (await session.execute(stmt)).scalars().all()
    return templates.TemplateResponse(request=request, name="community/events.html", context={
        "request": request,
        "events": events,
    })


@router.get("/contributors")
async def contributors_list(request: Request):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        stmt = select(Contributor).order_by(Contributor.first_contribution_date.desc())
        contributors = (await session.execute(stmt)).scalars().all()
    return templates.TemplateResponse(request=request, name="community/contributors.html", context={
        "request": request,
        "contributors": contributors,
    })


@router.get("/contributors/{handle}")
async def contributor_detail(request: Request, handle: str):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        stmt = select(Contributor).where(Contributor.github_handle == handle)
        contributor = (await session.execute(stmt)).scalar_one_or_none()
        if not contributor:
            raise HTTPException(status_code=404, detail="Contributor not found")
        stmt_c = (
            select(Contribution)
            .where(Contribution.contributor_id == contributor.id)
            .order_by(Contribution.date.desc())
        )
        contributions = (await session.execute(stmt_c)).scalars().all()
    return templates.TemplateResponse(request=request, name="community/contributor_detail.html", context={
        "request": request,
        "contributor": contributor,
        "contributions": contributions,
    })


@router.get("/stats")
async def stats(request: Request):
    templates = request.app.state.templates
    async with request.app.state.db() as session:
        salon_count = (await session.execute(
            select(func.count(SalonSessionRow.id))
        )).scalar() or 0
        curriculum_count = (await session.execute(
            select(func.count(Curriculum.id))
        )).scalar() or 0
        entry_count = (await session.execute(
            select(func.count(Entry.id))
        )).scalar() or 0
        taxonomy_count = (await session.execute(
            select(func.count(TaxonomyNodeRow.id))
        )).scalar() or 0
        contributor_count = (await session.execute(
            select(func.count(Contributor.id))
        )).scalar() or 0
        event_count = (await session.execute(
            select(func.count(Event.id))
        )).scalar() or 0
    return templates.TemplateResponse(request=request, name="community/stats.html", context={
        "request": request,
        "stats": {
            "salons": salon_count,
            "curricula": curriculum_count,
            "reading_entries": entry_count,
            "taxonomy_nodes": taxonomy_count,
            "contributors": contributor_count,
            "events": event_count,
        },
    })
