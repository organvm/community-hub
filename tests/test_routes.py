"""Comprehensive route tests for the community-hub FastAPI application.

Uses mocked database sessions to avoid requiring a real PostgreSQL instance.
All async DB access (``request.app.state.db()``) is replaced with a mock
async context manager that yields a mock ``AsyncSession``.

Preserved: the original import-and-structure checks at the bottom.
"""

from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Helpers: mock ORM rows as lightweight SimpleNamespace objects
# ---------------------------------------------------------------------------


def _salon_row(
    id: int = 1,
    title: str = "Test Salon",
    date_val: datetime | None = None,
    format: str = "deep_dive",
    facilitator: str | None = "Alice",
    notes: str = "Some notes.",
    organ_tags: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        title=title,
        date=date_val or datetime(2025, 6, 15, tzinfo=timezone.utc),
        format=format,
        facilitator=facilitator,
        notes=notes,
        organ_tags=organ_tags or ["I", "VI"],
    )


def _participant_row(
    name: str = "Bob",
    role: str = "participant",
    session_id: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(id=1, name=name, role=role, session_id=session_id)


def _segment_row(
    speaker: str = "Bob",
    text: str = "Hello world.",
    start_seconds: float = 0.0,
    end_seconds: float = 5.0,
    confidence: float = 0.95,
    session_id: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        session_id=session_id,
        speaker=speaker,
        text=text,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        confidence=confidence,
    )


def _curriculum_row(
    id: int = 1,
    title: str = "Test Curriculum",
    theme: str = "philosophy",
    organ_focus: str | None = "I",
    duration_weeks: int = 8,
    description: str = "A test curriculum.",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        title=title,
        theme=theme,
        organ_focus=organ_focus,
        duration_weeks=duration_weeks,
        description=description,
    )


def _reading_session_row(
    id: int = 1,
    curriculum_id: int = 1,
    week: int = 1,
    title: str = "Week 1: Intro",
    duration_minutes: int = 90,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        curriculum_id=curriculum_id,
        week=week,
        title=title,
        duration_minutes=duration_minutes,
    )


def _event_row(
    id: int = 1,
    type: str = "salon",
    title: str = "Test Event",
    date_val: datetime | None = None,
    description: str = "An event.",
    format: str = "virtual",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        type=type,
        title=title,
        date=date_val or datetime(2025, 6, 20, tzinfo=timezone.utc),
        description=description,
        format=format,
    )


def _contributor_row(
    id: int = 1,
    github_handle: str = "testuser",
    name: str = "Test User",
    organs_active: list[str] | None = None,
    first_contribution_date_val: date | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        github_handle=github_handle,
        name=name,
        organs_active=organs_active or ["I", "VI"],
        first_contribution_date=first_contribution_date_val or date(2024, 1, 1),
    )


def _contribution_row(
    id: int = 1,
    contributor_id: int = 1,
    repo: str = "koinonia-db",
    type: str = "code",
    url: str | None = "https://github.com/organvm-vi-koinonia/koinonia-db/pull/1",
    date_val: date | None = None,
    description: str = "Initial commit",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        contributor_id=contributor_id,
        repo=repo,
        type=type,
        url=url,
        date=date_val or date(2024, 1, 1),
        description=description,
    )


def _taxonomy_root(
    id: int = 1,
    slug: str = "theoria",
    label: str = "Theoria",
    organ_id: int | None = 1,
    description: str = "Foundational theory.",
    parent_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        slug=slug,
        label=label,
        organ_id=organ_id,
        description=description,
        parent_id=parent_id,
    )


def _taxonomy_child(
    id: int = 2,
    slug: str = "recursion",
    label: str = "Recursion",
    parent_id: int = 1,
    description: str = "Recursive structures.",
    organ_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        slug=slug,
        label=label,
        organ_id=organ_id,
        description=description,
        parent_id=parent_id,
    )


# ---------------------------------------------------------------------------
# Mock session builder
# ---------------------------------------------------------------------------


class MockScalarsResult:
    """Mimic ``result.scalars()`` with a pre-loaded list."""

    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class MockResult:
    """Mimic the object returned by ``await session.execute(stmt)``.

    Supports ``.scalar()``, ``.scalar_one_or_none()``, ``.scalars()``,
    ``.mappings()``, and ``.all()`` (for named-tuple-style rows used
    by grouped contribution counts).
    """

    def __init__(
        self,
        scalar_value: Any = None,
        rows: list[Any] | None = None,
        mapping_rows: list[dict] | None = None,
        named_tuple_rows: list[Any] | None = None,
    ):
        self._scalar_value = scalar_value
        self._rows = rows or []
        self._mapping_rows = mapping_rows or []
        self._named_tuple_rows = named_tuple_rows or []

    def scalar(self) -> Any:
        return self._scalar_value

    def scalar_one_or_none(self) -> Any:
        return self._scalar_value

    def scalars(self) -> MockScalarsResult:
        return MockScalarsResult(self._rows)

    def mappings(self) -> MockScalarsResult:
        return MockScalarsResult(self._mapping_rows)

    def all(self) -> list[Any]:
        return self._named_tuple_rows


def _build_mock_session(
    execute_side_effects: list[MockResult] | None = None,
    get_return: Any = None,
) -> AsyncMock:
    """Build a mock async session with configurable execute results.

    ``execute_side_effects`` is a list of ``MockResult`` objects.  Each
    call to ``session.execute()`` consumes the next item.  If the list
    is exhausted, further calls return an empty ``MockResult``.

    ``get_return`` is the value returned by ``session.get()``.
    """
    session = AsyncMock()

    effects = list(execute_side_effects or [])

    async def _execute_side_effect(*args, **kwargs):
        if effects:
            return effects.pop(0)
        return MockResult()

    session.execute = AsyncMock(side_effect=_execute_side_effect)
    session.get = AsyncMock(return_value=get_return)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    return session


def _patch_db(app, mock_session: AsyncMock):
    """Replace ``app.state.db`` with an async ctx-mgr yielding *mock_session*."""

    @asynccontextmanager
    async def _db():
        yield mock_session

    app.state.db = _db


# ---------------------------------------------------------------------------
# Fixture: creates a fresh app per test with DB + lifespan mocked out
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Return a freshly-created FastAPI app with the lifespan bypassed.

    Each test patches ``app.state.db`` with its own mock via ``_patch_db``.
    """
    from community_hub.app import create_app

    application = create_app()

    # Pre-populate state so routes don't fail on missing attributes.
    application.state.engine = MagicMock()

    # Default no-op DB factory (tests override this).
    default_session = _build_mock_session()

    @asynccontextmanager
    async def _default_db():
        yield default_session

    application.state.db = _default_db
    return application


# ===========================================================================
# Route tests (async, using httpx + ASGITransport)
# ===========================================================================


# ---------------------------------------------------------------------------
# Tests: /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Tests: GET / (index)
# ---------------------------------------------------------------------------


class TestIndexPage:
    @pytest.mark.asyncio
    async def test_index_returns_html(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: /api/stats
# ---------------------------------------------------------------------------


class TestApiStats:
    @pytest.mark.asyncio
    async def test_stats_returns_counts(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=5),   # salon count
            MockResult(scalar_value=3),   # curriculum count
            MockResult(scalar_value=42),  # taxonomy count
            MockResult(scalar_value=2),   # contributor count
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["salons"] == 5
        assert data["curricula"] == 3
        assert data["taxonomy_nodes"] == 42
        assert data["contributors"] == 2

    @pytest.mark.asyncio
    async def test_stats_returns_json_content_type(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=0),
            MockResult(scalar_value=0),
            MockResult(scalar_value=0),
            MockResult(scalar_value=0),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats")
        assert "application/json" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: /api/health/deep
# ---------------------------------------------------------------------------


class TestApiHealthDeep:
    @pytest.mark.asyncio
    async def test_deep_health_connected(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(),                 # SELECT 1
            MockResult(scalar_value=5),   # salon count
            MockResult(scalar_value=3),   # curriculum count
            MockResult(scalar_value=42),  # taxonomy count
            MockResult(scalar_value=1),   # contributor count
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health/deep")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"
        assert data["organ"] == "VI"
        assert data["organ_name"] == "Koinonia"
        assert data["version"] == "0.4.0"
        assert "counts" in data
        assert data["counts"]["salons"] == 5

    @pytest.mark.asyncio
    async def test_deep_health_db_error(self, app):
        """When the DB raises, the endpoint should return degraded status."""
        session = _build_mock_session()
        session.execute = AsyncMock(side_effect=Exception("Connection refused"))
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health/deep")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["database"] == "error"


# ---------------------------------------------------------------------------
# Tests: /api/manifest
# ---------------------------------------------------------------------------


class TestApiManifest:
    @pytest.mark.asyncio
    async def test_manifest_structure(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["organ_id"] == "VI"
        assert data["organ_name"] == "Koinonia"
        assert data["organ_slug"] == "vi-koinonia"
        assert data["version"] == "0.4.0"
        assert "endpoints" in data
        assert "salons" in data["endpoints"]
        assert "curricula" in data["endpoints"]
        assert "taxonomy" in data["endpoints"]
        assert "search" in data["endpoints"]
        assert "capabilities" in data
        assert "salon_archive" in data["capabilities"]
        assert "atom_feeds" in data["capabilities"]

    @pytest.mark.asyncio
    async def test_manifest_endpoints_contain_base_url(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/manifest")
        data = resp.json()
        for key, url in data["endpoints"].items():
            assert url.startswith("http"), f"Endpoint {key} should be a full URL"


# ---------------------------------------------------------------------------
# Tests: /api/salons
# ---------------------------------------------------------------------------


class TestApiSalons:
    @pytest.mark.asyncio
    async def test_salon_list_paginated(self, app):
        salon = _salon_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=1),  # total count
            MockResult(rows=[salon]),    # salon rows
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Test Salon"
        assert data["items"][0]["format"] == "deep_dive"
        assert data["items"][0]["organ_tags"] == ["I", "VI"]
        assert "limit" in data
        assert "offset" in data

    @pytest.mark.asyncio
    async def test_salon_list_empty(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=0),
            MockResult(rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_salon_list_date_serialized_as_iso(self, app):
        salon = _salon_row(date_val=datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc))
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=1),
            MockResult(rows=[salon]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons")
        data = resp.json()
        assert data["items"][0]["date"] == "2025-03-01T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Tests: /api/salons/{id}
# ---------------------------------------------------------------------------


class TestApiSalonDetail:
    @pytest.mark.asyncio
    async def test_salon_detail_found(self, app):
        salon = _salon_row()
        participant = _participant_row()
        segment = _segment_row()
        session = _build_mock_session(
            execute_side_effects=[
                MockResult(rows=[participant]),   # participants
                MockResult(rows=[segment]),       # segments
            ],
            get_return=salon,
        )
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["title"] == "Test Salon"
        assert data["notes"] == "Some notes."
        assert len(data["participants"]) == 1
        assert data["participants"][0]["name"] == "Bob"
        assert data["participants"][0]["role"] == "participant"
        assert len(data["segments"]) == 1
        assert data["segments"][0]["speaker"] == "Bob"
        assert data["segments"][0]["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_salon_detail_not_found(self, app):
        session = _build_mock_session(get_return=None)
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons/999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Salon not found"

    @pytest.mark.asyncio
    async def test_salon_detail_with_no_participants_or_segments(self, app):
        salon = _salon_row(notes="", facilitator=None)
        session = _build_mock_session(
            execute_side_effects=[
                MockResult(rows=[]),  # no participants
                MockResult(rows=[]),  # no segments
            ],
            get_return=salon,
        )
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["participants"] == []
        assert data["segments"] == []
        assert data["facilitator"] is None


# ---------------------------------------------------------------------------
# Tests: /api/curricula
# ---------------------------------------------------------------------------


class TestApiCurricula:
    @pytest.mark.asyncio
    async def test_curricula_list_paginated(self, app):
        curriculum = _curriculum_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=1),
            MockResult(rows=[curriculum]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/curricula")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Test Curriculum"
        assert data["items"][0]["theme"] == "philosophy"
        assert data["items"][0]["duration_weeks"] == 8
        assert data["items"][0]["organ_focus"] == "I"

    @pytest.mark.asyncio
    async def test_curricula_list_empty(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=0),
            MockResult(rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/curricula?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []


# ---------------------------------------------------------------------------
# Tests: /api/curricula/{id}
# ---------------------------------------------------------------------------


class TestApiCurriculumDetail:
    @pytest.mark.asyncio
    async def test_curriculum_detail_found(self, app):
        curriculum = _curriculum_row()
        reading_session = _reading_session_row()
        session = _build_mock_session(
            execute_side_effects=[
                MockResult(rows=[reading_session]),
            ],
            get_return=curriculum,
        )
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/curricula/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["title"] == "Test Curriculum"
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["week"] == 1
        assert data["sessions"][0]["title"] == "Week 1: Intro"
        assert data["sessions"][0]["duration_minutes"] == 90

    @pytest.mark.asyncio
    async def test_curriculum_detail_not_found(self, app):
        session = _build_mock_session(get_return=None)
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/curricula/999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Curriculum not found"

    @pytest.mark.asyncio
    async def test_curriculum_detail_no_sessions(self, app):
        curriculum = _curriculum_row()
        session = _build_mock_session(
            execute_side_effects=[MockResult(rows=[])],
            get_return=curriculum,
        )
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/curricula/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []


# ---------------------------------------------------------------------------
# Tests: /api/taxonomy
# ---------------------------------------------------------------------------


class TestApiTaxonomy:
    @pytest.mark.asyncio
    async def test_taxonomy_tree(self, app):
        root = _taxonomy_root()
        child = _taxonomy_child()
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[root]),    # roots query
            MockResult(rows=[child]),   # children of root
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/taxonomy")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["slug"] == "theoria"
        assert data[0]["label"] == "Theoria"
        assert data[0]["organ_id"] == 1
        assert len(data[0]["children"]) == 1
        assert data[0]["children"][0]["slug"] == "recursion"
        assert data[0]["children"][0]["label"] == "Recursion"

    @pytest.mark.asyncio
    async def test_taxonomy_empty(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/taxonomy")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    @pytest.mark.asyncio
    async def test_taxonomy_multiple_roots(self, app):
        root1 = _taxonomy_root(id=1, slug="theoria", label="Theoria", organ_id=1)
        root2 = _taxonomy_root(id=3, slug="poiesis", label="Poiesis", organ_id=2)
        child1 = _taxonomy_child(id=2, slug="recursion", parent_id=1)
        child2 = _taxonomy_child(id=4, slug="generative-art", label="Generative Art", parent_id=3)
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[root1, root2]),   # roots
            MockResult(rows=[child1]),          # children of root1
            MockResult(rows=[child2]),          # children of root2
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/taxonomy")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["slug"] == "theoria"
        assert data[1]["slug"] == "poiesis"


# ---------------------------------------------------------------------------
# Tests: /api/contributors
# ---------------------------------------------------------------------------


class TestApiContributors:
    @pytest.mark.asyncio
    async def test_contributors_list_paginated(self, app):
        contributor = _contributor_row()
        count_row = SimpleNamespace(contributor_id=1, cnt=3)
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=1),               # total count
            MockResult(rows=[contributor]),            # contributor rows
            MockResult(named_tuple_rows=[count_row]),  # contribution counts
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/contributors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["github_handle"] == "testuser"
        assert data["items"][0]["name"] == "Test User"
        assert data["items"][0]["contribution_count"] == 3
        assert data["items"][0]["organs_active"] == ["I", "VI"]

    @pytest.mark.asyncio
    async def test_contributors_list_empty(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=0),
            MockResult(rows=[]),
            MockResult(named_tuple_rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/contributors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []


# ---------------------------------------------------------------------------
# Tests: /api/contributors/{handle}
# ---------------------------------------------------------------------------


class TestApiContributorDetail:
    @pytest.mark.asyncio
    async def test_contributor_detail_found(self, app):
        contributor = _contributor_row()
        contribution = _contribution_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=contributor),  # scalar_one_or_none
            MockResult(rows=[contribution]),        # contributions query
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/contributors/testuser")
        assert resp.status_code == 200
        data = resp.json()
        assert data["github_handle"] == "testuser"
        assert data["name"] == "Test User"
        assert data["contribution_count"] == 1
        assert len(data["contributions"]) == 1
        assert data["contributions"][0]["repo"] == "koinonia-db"
        assert data["contributions"][0]["type"] == "code"
        assert data["contributions"][0]["description"] == "Initial commit"

    @pytest.mark.asyncio
    async def test_contributor_detail_not_found(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=None),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/contributors/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Contributor not found"

    @pytest.mark.asyncio
    async def test_contributor_detail_no_contributions(self, app):
        contributor = _contributor_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=contributor),
            MockResult(rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/contributors/testuser")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contribution_count"] == 0
        assert data["contributions"] == []


# ---------------------------------------------------------------------------
# Tests: /api/search
# ---------------------------------------------------------------------------


class TestApiSearch:
    @pytest.mark.asyncio
    async def test_search_with_query(self, app):
        """Search endpoint returns structured JSON with category buckets."""
        salon_hit = {
            "id": 1, "title": "Found Salon", "notes": "x", "format": "deep_dive",
            "rank": 0.5, "headline": "<mark>test</mark>",
        }
        session = _build_mock_session(execute_side_effects=[
            MockResult(mapping_rows=[salon_hit]),  # salons FTS
            MockResult(mapping_rows=[]),           # segments FTS
            MockResult(mapping_rows=[]),           # entries FTS
            MockResult(mapping_rows=[]),           # taxonomy FTS
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/search?q=test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "test"
        assert "totals" in data
        assert "total" in data
        assert "results" in data
        assert data["total"] == 1
        assert data["totals"]["salons"] == 1

    @pytest.mark.asyncio
    async def test_search_empty_query(self, app):
        """Empty query should return empty results without hitting DB."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/search?q=")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert all(len(v) == 0 for v in data["results"].values())

    @pytest.mark.asyncio
    async def test_search_short_query_skipped(self, app):
        """Query shorter than 2 chars returns empty results from _search_all."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/search?q=x")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_search_results_structure(self, app):
        """Verify that all four category keys are present in results."""
        session = _build_mock_session(execute_side_effects=[
            MockResult(mapping_rows=[]),
            MockResult(mapping_rows=[]),
            MockResult(mapping_rows=[]),
            MockResult(mapping_rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/search?q=philosophy")
        data = resp.json()
        for key in ("salons", "segments", "entries", "taxonomy"):
            assert key in data["results"]
            assert key in data["totals"]


# ---------------------------------------------------------------------------
# Tests: Atom feeds /feeds/*.xml
# ---------------------------------------------------------------------------


class TestFeedSalonsXml:
    @pytest.mark.asyncio
    async def test_feed_salons_xml(self, app):
        salon = _salon_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[salon]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/feeds/salons.xml")
        assert resp.status_code == 200
        assert "application/atom+xml" in resp.headers.get("content-type", "")
        body = resp.text
        assert "<?xml" in body
        assert "Test Salon" in body
        assert "ORGAN-VI Salons" in body

    @pytest.mark.asyncio
    async def test_feed_salons_empty(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/feeds/salons.xml")
        assert resp.status_code == 200
        assert "application/atom+xml" in resp.headers.get("content-type", "")
        assert "<?xml" in resp.text


class TestFeedEventsXml:
    @pytest.mark.asyncio
    async def test_feed_events_xml(self, app):
        event = _event_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[event]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/feeds/events.xml")
        assert resp.status_code == 200
        assert "application/atom+xml" in resp.headers.get("content-type", "")
        body = resp.text
        assert "Test Event" in body
        assert "ORGAN-VI Community Events" in body

    @pytest.mark.asyncio
    async def test_feed_events_empty(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/feeds/events.xml")
        assert resp.status_code == 200
        assert "application/atom+xml" in resp.headers.get("content-type", "")


class TestFeedCurriculaXml:
    @pytest.mark.asyncio
    async def test_feed_curricula_xml(self, app):
        curriculum = _curriculum_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[curriculum]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/feeds/curricula.xml")
        assert resp.status_code == 200
        assert "application/atom+xml" in resp.headers.get("content-type", "")
        body = resp.text
        assert "Test Curriculum" in body
        assert "ORGAN-VI Reading Curricula" in body

    @pytest.mark.asyncio
    async def test_feed_curricula_empty(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/feeds/curricula.xml")
        assert resp.status_code == 200
        assert "application/atom+xml" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: HTML pages -- /salons/
# ---------------------------------------------------------------------------


class TestSalonHtmlRoutes:
    @pytest.mark.asyncio
    async def test_salon_list_html(self, app):
        salon = _salon_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=1),
            MockResult(rows=[salon]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/salons/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_salon_detail_html(self, app):
        salon = _salon_row()
        participant = _participant_row()
        segment = _segment_row()
        session = _build_mock_session(
            execute_side_effects=[
                MockResult(rows=[participant]),
                MockResult(rows=[segment]),
            ],
            get_return=salon,
        )
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/salons/1")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: HTML pages -- /curricula/
# ---------------------------------------------------------------------------


class TestCurriculaHtmlRoutes:
    @pytest.mark.asyncio
    async def test_curricula_list_html(self, app):
        curriculum = _curriculum_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=1),
            MockResult(rows=[curriculum]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/curricula/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_curriculum_detail_html(self, app):
        curriculum = _curriculum_row()
        reading_session = _reading_session_row()
        session = _build_mock_session(
            execute_side_effects=[
                MockResult(rows=[reading_session]),
            ],
            get_return=curriculum,
        )
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/curricula/1")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: HTML pages -- /community/*
# ---------------------------------------------------------------------------


class TestCommunityHtmlRoutes:
    @pytest.mark.asyncio
    async def test_events_list_html(self, app):
        event = _event_row()
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[event]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/community/events")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_stats_page_html(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=5),   # salon count
            MockResult(scalar_value=3),   # curriculum count
            MockResult(scalar_value=10),  # entry count
            MockResult(scalar_value=42),  # taxonomy count
            MockResult(scalar_value=2),   # contributor count
            MockResult(scalar_value=7),   # event count
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/community/stats")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: HTML pages -- /syllabus
# ---------------------------------------------------------------------------


class TestSyllabusHtmlRoutes:
    @pytest.mark.asyncio
    async def test_syllabus_form_renders(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/syllabus")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: /api/syllabus/generate
# ---------------------------------------------------------------------------


class TestApiSyllabusGenerate:
    @pytest.mark.asyncio
    async def test_api_syllabus_generate(self, app):
        """Mock the generate_learning_path service and verify JSON response."""
        mock_path = {
            "path_id": "abc12345",
            "title": "Learning Path: I",
            "organs": ["I"],
            "level": "beginner",
            "total_hours": 4.0,
            "modules": [
                {
                    "module_id": "recursion-beg",
                    "title": "Recursion",
                    "organ": "theoria",
                    "difficulty": "beginner",
                    "readings": ["See Theoria documentation"],
                    "questions": ["What is recursion?"],
                    "estimated_hours": 2.0,
                }
            ],
        }

        with patch(
            "community_hub.routes.syllabus.generate_learning_path",
            new_callable=AsyncMock,
            return_value=mock_path,
        ):
            session = _build_mock_session()
            _patch_db(app, session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/syllabus/generate?organs=I&level=beginner")
            assert resp.status_code == 200
            data = resp.json()
            assert data["path_id"] == "abc12345"
            assert data["organs"] == ["I"]
            assert data["level"] == "beginner"
            assert len(data["modules"]) == 1
            assert data["modules"][0]["title"] == "Recursion"

    @pytest.mark.asyncio
    async def test_api_syllabus_generate_multiple_organs(self, app):
        """Comma-separated organ codes should be accepted."""
        mock_path = {
            "path_id": "xyz99999",
            "title": "Learning Path: I, II",
            "organs": ["I", "II"],
            "level": "intermediate",
            "total_hours": 8.0,
            "modules": [],
        }
        with patch(
            "community_hub.routes.syllabus.generate_learning_path",
            new_callable=AsyncMock,
            return_value=mock_path,
        ):
            session = _build_mock_session()
            _patch_db(app, session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/syllabus/generate?organs=I,II&level=intermediate"
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["organs"] == ["I", "II"]

    @pytest.mark.asyncio
    async def test_api_syllabus_generate_invalid_level(self, app):
        """Invalid level should return an error message, not raise."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/syllabus/generate?organs=I&level=expert")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_api_syllabus_generate_empty_organs(self, app):
        """Empty organs param should return an error message."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/syllabus/generate?organs=&level=beginner")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# Tests: HTML search page -- /search
# ---------------------------------------------------------------------------


class TestSearchHtmlPage:
    @pytest.mark.asyncio
    async def test_search_page_empty_query(self, app):
        """The HTML search page renders with an empty query and no DB calls."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/search")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_search_page_with_query(self, app):
        """The HTML search page renders when a query is provided."""
        session = _build_mock_session(execute_side_effects=[
            MockResult(mapping_rows=[]),
            MockResult(mapping_rows=[]),
            MockResult(mapping_rows=[]),
            MockResult(mapping_rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/search?q=philosophy")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: Pagination parameter validation
# ---------------------------------------------------------------------------


class TestPaginationParams:
    @pytest.mark.asyncio
    async def test_salon_list_custom_pagination(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=100),
            MockResult(rows=[_salon_row(id=i) for i in range(1, 6)]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons?limit=5&offset=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 5
        assert data["offset"] == 10

    @pytest.mark.asyncio
    async def test_salon_list_invalid_limit(self, app):
        """Limit below 1 should be rejected by FastAPI validation."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons?limit=0")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_salon_list_limit_too_high(self, app):
        """Limit above 200 should be rejected by FastAPI validation."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/salons?limit=999")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_curricula_list_negative_offset(self, app):
        """Negative offset should be rejected by FastAPI validation."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/curricula?offset=-1")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_contributors_list_custom_pagination(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=50),
            MockResult(rows=[]),
            MockResult(named_tuple_rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/contributors?limit=10&offset=20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 10
        assert data["offset"] == 20


# ---------------------------------------------------------------------------
# Tests: 404 on HTML routes
# ---------------------------------------------------------------------------


class TestHtmlNotFound:
    @pytest.mark.asyncio
    async def test_salon_detail_html_404(self, app):
        session = _build_mock_session(get_return=None)
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/salons/999",
                headers={"accept": "text/html"},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_curriculum_detail_html_404(self, app):
        session = _build_mock_session(get_return=None)
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/curricula/999",
                headers={"accept": "text/html"},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_contributor_detail_html_404(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=None),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/community/contributors/nonexistent",
                headers={"accept": "text/html"},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: CSRF middleware behavior
# ---------------------------------------------------------------------------


class TestCSRFMiddleware:
    @pytest.mark.asyncio
    async def test_csrf_cookie_is_set_on_get(self, app):
        """GET requests should receive a csrf_token cookie."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert "csrf_token" in resp.cookies

    @pytest.mark.asyncio
    async def test_post_without_csrf_rejected(self, app):
        """POST to a non-API, non-exempted path without CSRF token should get 403."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/syllabus/generate",
                data={"organs": "I", "level": "beginner", "name": "test"},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_post_with_valid_csrf_token(self, app):
        """POST with matching csrf_token cookie+form field should pass CSRF check."""
        mock_path = {
            "path_id": "abc12345",
            "title": "Learning Path: I",
            "organs": ["I"],
            "level": "beginner",
            "total_hours": 4.0,
            "modules": [],
        }
        with patch(
            "community_hub.routes.syllabus.generate_learning_path",
            new_callable=AsyncMock,
            return_value=mock_path,
        ):
            session = _build_mock_session()
            _patch_db(app, session)

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                # First GET to obtain the CSRF token cookie
                get_resp = await client.get("/syllabus")
                csrf_token = get_resp.cookies.get("csrf_token")
                assert csrf_token is not None

                # POST with matching token in both cookie and form
                resp = await client.post(
                    "/syllabus/generate",
                    data={
                        "organs": "I",
                        "level": "beginner",
                        "name": "test",
                        "csrf_token": csrf_token,
                    },
                    cookies={"csrf_token": csrf_token},
                    headers={"content-type": "application/x-www-form-urlencoded"},
                )
            # Should pass CSRF and render (200) -- not 403
            assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Tests: Content type assertions
# ---------------------------------------------------------------------------


class TestContentTypes:
    @pytest.mark.asyncio
    async def test_api_returns_json(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(scalar_value=0),
            MockResult(scalar_value=0),
            MockResult(scalar_value=0),
            MockResult(scalar_value=0),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats")
        assert "application/json" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_html_pages_return_html(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_feeds_return_atom_xml(self, app):
        session = _build_mock_session(execute_side_effects=[
            MockResult(rows=[]),
        ])
        _patch_db(app, session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/feeds/salons.xml")
        assert "application/atom+xml" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_health_returns_json(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert "application/json" in resp.headers.get("content-type", "")


# ===========================================================================
# Preserved: original import-and-structure checks
# ===========================================================================


def test_salon_routes_importable():
    from community_hub.routes import salons
    assert hasattr(salons, "router")
    assert hasattr(salons, "salon_list")
    assert hasattr(salons, "salon_detail")


def test_curricula_routes_importable():
    from community_hub.routes import curricula
    assert hasattr(curricula, "router")
    assert hasattr(curricula, "curricula_list")
    assert hasattr(curricula, "curriculum_detail")


def test_community_routes_importable():
    from community_hub.routes import community
    assert hasattr(community, "router")
    assert hasattr(community, "events_list")
    assert hasattr(community, "contributors_list")
    assert hasattr(community, "contributor_detail")
    assert hasattr(community, "stats")


def test_api_routes_importable():
    from community_hub.routes import api
    assert hasattr(api, "router")
    assert hasattr(api, "api_salons")
    assert hasattr(api, "api_curricula")
    assert hasattr(api, "api_taxonomy")
    assert hasattr(api, "api_stats")


def test_search_routes_importable():
    from community_hub.routes import search
    assert hasattr(search, "router")
    assert hasattr(search, "search_page")
    assert hasattr(search, "search_api")


def test_syllabus_routes_importable():
    from community_hub.routes import syllabus
    assert hasattr(syllabus, "router")
    assert hasattr(syllabus, "syllabus_form")
    assert hasattr(syllabus, "syllabus_generate")
    assert hasattr(syllabus, "syllabus_view")
    assert hasattr(syllabus, "api_syllabus_generate")


def test_feeds_routes_importable():
    from community_hub.routes import feeds
    assert hasattr(feeds, "router")
    assert hasattr(feeds, "feed_salons")
    assert hasattr(feeds, "feed_events")
    assert hasattr(feeds, "feed_curricula")


def test_live_routes_importable():
    from community_hub.routes import live
    assert hasattr(live, "router")
    assert hasattr(live, "salon_live")
    assert hasattr(live, "salon_ws")
    assert hasattr(live, "RoomManager")
    assert hasattr(live, "manager")


def test_syllabus_uses_shared_service():
    """syllabus.py should import from koinonia_db.syllabus_service, not define its own."""
    from community_hub.routes import syllabus
    source = inspect.getsource(syllabus)
    assert "from koinonia_db.syllabus_service import generate_learning_path" in source
    assert "_generate_path" not in source


def test_app_creates():
    from community_hub.app import create_app
    app = create_app()
    assert app.title == "ORGAN-VI Community Hub"
    assert app.version == "0.4.0"
    routes = [getattr(r, "path", getattr(r, "prefix", "")) for r in app.routes]
    assert "/" in routes


def test_app_has_all_routers():
    from community_hub.app import create_app
    app = create_app()
    def get_paths(routes, prefix=""):
        paths = []
        for r in routes:
            if type(r).__name__ == "_IncludedRouter":
                p = getattr(r.include_context, "prefix", "") or ""
                paths.extend(get_paths(r.original_router.routes, prefix + p))
            else:
                paths.append(prefix + getattr(r, "path", getattr(r, "prefix", "")))
        return paths
        
    routes = get_paths(app.routes)
    assert "/health" in routes
    assert "/salons" in routes or "/salons/" in routes
    assert "/search" in routes or "/search/" in routes


def test_logging_config_importable():
    from community_hub.logging_config import configure_logging, JSONFormatter
    assert callable(configure_logging)
    assert JSONFormatter is not None
