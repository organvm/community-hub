"""FastAPI application for the ORGAN-VI community hub."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from community_hub.config import Settings
from community_hub.csrf import CSRFMiddleware
from community_hub.logging_config import configure_logging
from community_hub.routes import salons, curricula, community, api, feeds, live
from community_hub.routes import search as search_routes
from community_hub.routes import syllabus as syllabus_routes

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, SessionLocal
    configure_logging(debug=Settings.DEBUG)
    logger.info("ORGAN-VI Community Hub starting", extra={"version": "0.4.0"})
    db_url = Settings.require_db()
    engine = create_async_engine(db_url, pool_size=5, max_overflow=10)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.db = SessionLocal
    logger.info("Database connection established")
    yield
    if engine:
        await engine.dispose()
        logger.info("Database connection closed")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ORGAN-VI Community Hub",
        description=(
            "Community portal for the ORGANVM eight-organ system. "
            "Browse archived salons, reading group curricula, community events, "
            "contributor profiles, and generate personalized learning paths."
        ),
        version="0.4.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "api", "description": "JSON API endpoints for all community hub data"},
            {"name": "salons", "description": "Browse archived salon sessions and transcripts"},
            {"name": "curricula", "description": "Reading group curricula and sessions"},
            {"name": "community", "description": "Events, contributors, and community stats"},
            {"name": "search", "description": "Full-text search across all content"},
            {"name": "syllabus", "description": "Personalized learning path generation"},
            {"name": "feeds", "description": "Atom 1.0 syndication feeds"},
            {"name": "live", "description": "WebSocket live salon rooms"},
        ],
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — origins configurable via ALLOWED_ORIGINS env var (comma-separated)
    allowed_origins = Settings.ALLOWED_ORIGINS
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    # CSRF protection (double-submit cookie)
    app.add_middleware(CSRFMiddleware)

    # Rate limiting
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    from typing import cast
    from starlette.types import ExceptionHandler
    app.add_exception_handler(RateLimitExceeded, cast(ExceptionHandler, _rate_limit_exceeded_handler))

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    # Make csrf_token available in all templates via request.state
    templates.env.globals["csrf_field"] = (
        lambda request: f'<input type="hidden" name="csrf_token" '
        f'value="{getattr(request.state, "csrf_token", "")}">'
    )
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Global exception handler — HTML for browsers, JSON for API clients
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        accept = request.headers.get("accept", "")
        if "text/html" in accept and not request.url.path.startswith("/api"):
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "request": request,
                    "status_code": exc.status_code,
                    "detail": exc.detail,
                },
                status_code=exc.status_code,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        accept = request.headers.get("accept", "")
        if "text/html" in accept and not request.url.path.startswith("/api"):
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "request": request,
                    "status_code": 500,
                    "detail": "Internal Server Error",
                },
                status_code=500,
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(salons.router, prefix="/salons", tags=["salons"])
    app.include_router(curricula.router, prefix="/curricula", tags=["curricula"])
    app.include_router(community.router, prefix="/community", tags=["community"])
    app.include_router(api.router, prefix="/api", tags=["api"])
    app.include_router(search_routes.router, tags=["search"])
    app.include_router(syllabus_routes.router, tags=["syllabus"])
    app.include_router(feeds.router, tags=["feeds"])
    app.include_router(live.router, tags=["live"])

    @app.get("/")
    async def index(request: Request):
        return templates.TemplateResponse(request=request, name="index.html", context={"request": request})

    return app


app = create_app()


def run():
    """Entry point for the community-hub CLI."""
    uvicorn.run(
        "community_hub.app:app",
        host=Settings.HOST,
        port=Settings.PORT,
        reload=Settings.DEBUG,
    )


if __name__ == "__main__":
    run()
