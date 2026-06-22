# Value Discovery — organvm/community-hub

**Status:** RANKED (promoted from dark) · **Verdict:** Real, high latent value · **Date:** 2026-06-22

## Value Thesis

community-hub is not a stub or an archive — it is a **live, deployed, 122-test FastAPI
flagship** (v0.5.0, serving at `community-hub-8p8t.onrender.com`) that already does real
work: it renders the public face of ORGAN-VI Koinonia as both HTML pages and a JSON API,
covering salon archives, reading curricula, taxonomy, community events, contributor
profiles, full-text search, Atom 1.0 syndication feeds, and WebSocket-powered live salon
rooms — all with production hygiene already in place (double-submit-cookie CSRF, per-IP
rate limiting, WebSocket message-size limits, HTML-escaped broadcasts, structured logging,
Alembic-on-boot via the Docker entrypoint). Its single **highest latent value is the
`/api/manifest` + adaptive-syllabus capability pair**: the manifest endpoint already
publishes a machine-readable contract (endpoints + a ten-item `capabilities` list) designed
for ORGAN-IV orchestration, and the syllabus engine turns a set of organ codes + a level
into a persisted, sequenced learning path — meaning community-hub is the estate's
**community-facing read API and personalization surface**, the one repo that can expose any
other organ's content (salons, curricula, taxonomy) to humans *and* to sibling agents
through one authenticated, rate-limited, self-describing gateway. The reusable asset the
rest of the estate can immediately consume is this manifest-driven API + the
`community-data-export` console script, which renders the full route table and aggregate
community stats to static JSON **with no server or database required** — a drop-in way for
any sibling (koinonia-db, salon-archive, reading-group-curriculum,
adaptive-personal-syllabus) or the ORGAN-IV registry to discover and wire up ORGAN-VI's
surface deterministically. This repo is revenue-/product-adjacent (it *is* the public
portal) and infrastructurally load-bearing; it should never have been dark.

## Highest-Value Concrete First Task

**Wire `/api/manifest` into the ORGAN-IV orchestration registry as the canonical ORGAN-VI
descriptor, and add a CI step that runs `community-data-export` and publishes
`data/api-routes.json` + `data/community-stats.json` as build artifacts** — so the manifest
and the static export stay in lockstep with the live route table and any sibling/agent can
consume ORGAN-VI's surface without booting the app. (The export path is already
DB-free and tested in `tests/test_data_export.py`; this is plumbing, not new product.)

## Why not archival

Archival was never on the table: the app is deployed, versioned (v0.5.0), actively
dependency-maintained (recent Dependabot merges), test-covered, and security-hardened. The
only reason it carried *no ranked value* was that it had not been discovered — corrected here.
