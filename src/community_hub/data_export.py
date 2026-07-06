"""Generate static data artifacts for the community hub.

Produces:
  data/api-routes.json       — all FastAPI routes with methods and descriptions
  data/community-stats.json  — aggregated stats from seed data

No running server or database required.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).parent.parent.parent.parent / "koinonia-db" / "seed"


def extract_api_routes() -> list[dict[str, Any]]:
    """Inspect the FastAPI app to extract all registered routes."""
    from community_hub.app import create_app

    app = create_app()
    routes: list[dict[str, Any]] = []

    for route in app.routes:
        # Skip Mount entries (static files) and catch-all
        if not hasattr(route, "methods"):
            continue
        path = getattr(route, "path", "")
        route_methods = getattr(route, "methods", None)
        methods = sorted(route_methods - {"HEAD", "OPTIONS"}) if route_methods else []
        if not methods:
            continue
        name = getattr(route, "name", "")
        endpoint = getattr(route, "endpoint", None)
        description = ""
        if endpoint and endpoint.__doc__:
            description = endpoint.__doc__.strip().split("\n")[0]

        routes.append({
            "path": path,
            "methods": methods,
            "name": name,
            "description": description,
        })

    # Sort by path for deterministic output
    routes.sort(key=lambda r: r["path"])
    return routes


def build_community_stats(seed_dir: Path | None = None) -> dict[str, Any]:
    """Compute community stats from seed JSON files."""
    seed_dir = seed_dir or SEED_DIR
    stats: dict[str, Any] = {}

    # Sessions
    sessions_path = seed_dir / "sample_sessions.json"
    if sessions_path.exists():
        data = json.loads(sessions_path.read_text())
        sessions = data.get("sessions", [])
        stats["salon_count"] = len(sessions)
        stats["total_segments"] = sum(
            len(s.get("segments", [])) for s in sessions
        )
        stats["total_participants"] = sum(
            len(s.get("participants", [])) for s in sessions
        )
    else:
        stats["salon_count"] = 0
        stats["total_segments"] = 0
        stats["total_participants"] = 0

    # Curricula
    curricula_path = seed_dir / "curricula.json"
    if curricula_path.exists():
        data = json.loads(curricula_path.read_text())
        curricula = data.get("curricula", [])
        stats["curriculum_count"] = len(curricula)
        stats["total_curriculum_sessions"] = sum(
            len(c.get("sessions", [])) for c in curricula
        )
    else:
        stats["curriculum_count"] = 0
        stats["total_curriculum_sessions"] = 0

    # Reading lists
    readings_path = seed_dir / "reading_lists.json"
    if readings_path.exists():
        data = json.loads(readings_path.read_text())
        stats["reading_entry_count"] = len(data.get("entries", []))
    else:
        stats["reading_entry_count"] = 0

    # Taxonomy
    taxonomy_path = seed_dir / "taxonomy.json"
    if taxonomy_path.exists():
        data = json.loads(taxonomy_path.read_text())
        nodes = data.get("nodes", [])
        child_count = sum(len(n.get("children", [])) for n in nodes)
        stats["taxonomy_root_count"] = len(nodes)
        stats["taxonomy_total_nodes"] = len(nodes) + child_count
    else:
        stats["taxonomy_root_count"] = 0
        stats["taxonomy_total_nodes"] = 0

    # Community (events + contributors)
    community_path = seed_dir / "community.json"
    if community_path.exists():
        data = json.loads(community_path.read_text())
        stats["event_count"] = len(data.get("events", []))
        stats["contributor_count"] = len(data.get("contributors", []))
    else:
        stats["event_count"] = 0
        stats["contributor_count"] = 0

    return stats


def export_all(
    seed_dir: Path | None = None,
    output_dir: Path | None = None,
) -> list[Path]:
    """Generate all data artifacts and return output paths."""
    output_dir = output_dir or Path(__file__).parent.parent.parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    # api-routes.json
    routes = extract_api_routes()
    routes_path = output_dir / "api-routes.json"
    routes_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "route_count": len(routes),
        "routes": routes,
    }
    routes_path.write_text(json.dumps(routes_data, indent=2) + "\n")
    outputs.append(routes_path)

    # community-stats.json
    stats = build_community_stats(seed_dir)
    stats_path = output_dir / "community-stats.json"
    stats_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organ": "VI",
        "organ_name": "Koinonia",
        **stats,
    }
    stats_path.write_text(json.dumps(stats_data, indent=2) + "\n")
    outputs.append(stats_path)

    return outputs


def main() -> None:
    """CLI entry point for data export."""
    paths = export_all()
    for p in paths:
        print(f"Written: {p}")


if __name__ == "__main__":
    main()
