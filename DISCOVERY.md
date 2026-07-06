# Discovery — organvm/community-hub

**Status:** VALUE FOUND → promoted to ranked tier
**Discovered:** 2026-06-22 (auto-discovery sweep)
**Verdict:** Not archival. This is the estate's single most valuable *live, public-facing* asset.

## Value thesis

community-hub is ORGAN-VI's flagship: a production FastAPI application (v0.4.0,
122 tests, deployed live on Render at `community-hub-8p8t.onrender.com`) that is
the only deployed, public web surface in the estate. Its latent value is not just
the community portal it serves today (salon archives, reading curricula, taxonomy,
contributor profiles, full-text search, an adaptive-syllabus generator, and Atom
1.0 feeds) — it is that the repo already contains two estate-scale assets that
nothing else exposes. First, a **machine-readable discovery surface**: the
self-describing `/api/manifest` endpoint declares versioned endpoints and a
capability list explicitly "for ORGAN-IV orchestration registry," and the three
Atom feeds plus full-text search make this the natural *front door / aggregator*
for the whole eight-organ system — extend it to fan out across sibling organ
manifests and community-hub becomes the system-wide public index rather than a
single-organ portal. Second, a **reusable, production-hardened web scaffold**:
double-submit-cookie CSRF middleware (`csrf.py`), an in-process WebSocket
`RoomManager` with per-connection rate limiting and message-size caps (`live.py`),
slowapi per-IP rate limiting, dual HTML/JSON error handling, and a
database-free static-artifact generator (`data_export.py`) — patterns every other
estate web app would otherwise reinvent. The honest revenue/reach path is reach,
not direct revenue: it is the public face that makes the rest of the estate
discoverable and syndicatable. That is real, present value, so it belongs in the
ranked tier and build-out should follow.

## Highest latent value (ranked)

1. **Estate discovery/syndication front door** — `/api/manifest` + Atom feeds +
   full-text search already exist; turning them into a cross-organ aggregator
   makes community-hub the public index for all eight organs. (Capability the
   whole estate consumes.)
2. **Reusable web scaffold** — CSRF middleware, WebSocket `RoomManager`, rate
   limiting, dual HTML/JSON error handling, `data_export` artifact generator.
   Extractable into `koinonia-db` / a shared `koinonia-web` package.
3. **The live product itself** — the community portal: salons, curricula,
   adaptive syllabi, contributor profiles, feeds.

## Single best concrete first task

**Add a cross-organ aggregation endpoint + combined feed.** Build
`GET /api/estate` (and an aggregated Atom feed) that fans out over sibling/organ
`/api/manifest` endpoints — reusing the existing `ManifestOut` model, feed
generation, and search plumbing — so community-hub becomes the estate's
machine-readable public index instead of an ORGAN-VI-only portal. It is
low-risk (additive, builds on shipped patterns), high-leverage (every organ
gains a public discovery surface for free), and immediately demonstrates the
front-door thesis above.
