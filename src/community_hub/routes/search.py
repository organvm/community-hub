"""Search routes — full-text search across salons, transcripts, and readings."""

from __future__ import annotations

from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


async def _search_all(db_session, query: str) -> dict:
    """Run full-text search across all searchable tables."""
    results = {"salons": [], "segments": [], "entries": [], "taxonomy": []}

    if not query or len(query.strip()) < 2:
        return results

    q = query.strip()

    # Salons
    stmt = text("""
        SELECT id, title, notes, format,
               ts_rank(search_vector, plainto_tsquery('english', :q)) AS rank,
               ts_headline('english', coalesce(title, '') || ' ' || coalesce(notes, ''),
                           plainto_tsquery('english', :q),
                           'MaxWords=30, MinWords=10, StartSel=<mark>, StopSel=</mark>') AS headline
        FROM salons.sessions
        WHERE search_vector @@ plainto_tsquery('english', :q)
        ORDER BY rank DESC LIMIT 20
    """)
    rows = (await db_session.execute(stmt, {"q": q})).mappings().all()
    results["salons"] = [dict(r) for r in rows]

    # Segments (transcript text)
    stmt = text("""
        SELECT s.id, s.session_id, s.speaker, s.start_seconds,
               ts_rank(s.search_vector, plainto_tsquery('english', :q)) AS rank,
               ts_headline('english', s.text, plainto_tsquery('english', :q),
                           'MaxWords=40, MinWords=15, StartSel=<mark>, StopSel=</mark>') AS headline,
               ss.title AS session_title
        FROM salons.segments s
        JOIN salons.sessions ss ON s.session_id = ss.id
        WHERE s.search_vector @@ plainto_tsquery('english', :q)
        ORDER BY rank DESC LIMIT 30
    """)
    rows = (await db_session.execute(stmt, {"q": q})).mappings().all()
    results["segments"] = [dict(r) for r in rows]

    # Reading entries
    stmt = text("""
        SELECT id, title, author, source_type, difficulty,
               ts_rank(search_vector, plainto_tsquery('english', :q)) AS rank,
               ts_headline('english', coalesce(title, '') || ' by ' || coalesce(author, ''),
                           plainto_tsquery('english', :q),
                           'MaxWords=20, MinWords=5, StartSel=<mark>, StopSel=</mark>') AS headline
        FROM reading.entries
        WHERE search_vector @@ plainto_tsquery('english', :q)
        ORDER BY rank DESC LIMIT 20
    """)
    rows = (await db_session.execute(stmt, {"q": q})).mappings().all()
    results["entries"] = [dict(r) for r in rows]

    # Taxonomy nodes
    stmt = text("""
        SELECT id, slug, label, description,
               ts_rank(search_vector, plainto_tsquery('english', :q)) AS rank,
               ts_headline('english', coalesce(label, '') || ' ' || coalesce(description, ''),
                           plainto_tsquery('english', :q),
                           'MaxWords=20, MinWords=5, StartSel=<mark>, StopSel=</mark>') AS headline
        FROM salons.taxonomy_nodes
        WHERE search_vector @@ plainto_tsquery('english', :q)
        ORDER BY rank DESC LIMIT 20
    """)
    rows = (await db_session.execute(stmt, {"q": q})).mappings().all()
    results["taxonomy"] = [dict(r) for r in rows]

    return results


@router.get("/search")
@limiter.limit("30/minute")
async def search_page(request: Request, q: str = ""):
    """HTML search page with categorized results."""
    templates = request.app.state.templates
    results = {"salons": [], "segments": [], "entries": [], "taxonomy": []}
    total = 0

    if q.strip():
        async with request.app.state.db() as session:
            results = await _search_all(session, q)
        total = sum(len(v) for v in results.values())

    return templates.TemplateResponse(request=request, name="search.html", context={
        "request": request,
        "query": q,
        "results": results,
        "total": total,
    })


@router.get("/api/search")
@limiter.limit("30/minute")
async def search_api(request: Request, q: str = ""):
    """JSON search API — cross-organ endpoint for ORGAN-IV consumption."""
    results = {"salons": [], "segments": [], "entries": [], "taxonomy": []}

    if q.strip():
        async with request.app.state.db() as session:
            results = await _search_all(session, q)

    totals = {k: len(v) for k, v in results.items()}
    return {
        "query": q,
        "totals": totals,
        "total": sum(totals.values()),
        "results": results,
    }
