from pathlib import Path


PITCH = Path(__file__).parents[1] / "docs" / "pitch" / "index.html"


def test_static_pitch_is_a_complete_fallback_surface() -> None:
    body = PITCH.read_text(encoding="utf-8")

    assert "<title>Community Hub — Koinonia</title>" in body
    assert "Open the live portal" in body
    assert "https://github.com/organvm/community-hub" in body
    assert "Under Construction" not in body
    assert "coming soon" not in body.lower()
    assert "{'type':" not in body
    assert "{'repo':" not in body
