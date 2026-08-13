"""W3 skip preview: dry-run engine resolve under monitoring_stance."""

from types import SimpleNamespace

from app.geo.content.monitoring_stance import (
    build_skip_preview,
    preview_engine_skip,
)


def test_real_only_skips_persona_engine():
    r = preview_engine_skip(
        monitoring_stance="real_only",
        sample_mode="mock_persona",
        api_key_configured=False,
        has_base_url=False,
        has_model=False,
        enabled=True,
    )
    assert r["will_skip"] is True
    assert r["will_run"] is False
    assert "persona" in (r["reason"] or "")


def test_real_only_runs_ready_compat():
    r = preview_engine_skip(
        monitoring_stance="real_only",
        sample_mode="openai_compat",
        api_key_configured=True,
        has_base_url=True,
        has_model=True,
        enabled=True,
    )
    assert r["will_run"] is True
    assert r["will_skip"] is False
    assert r["sample_mode_effective"] == "openai_compat"


def test_hybrid_persona_still_runs():
    r = preview_engine_skip(
        monitoring_stance="hybrid",
        sample_mode="mock_persona",
        api_key_configured=False,
        has_base_url=False,
        has_model=False,
        enabled=True,
    )
    assert r["will_run"] is True
    assert r["will_skip"] is False
    assert r["sample_mode_effective"] == "mock_persona"


def test_build_skip_preview_counts():
    engines = [
        SimpleNamespace(
            engine_key="a",
            display_name="A",
            enabled=True,
            sample_mode="mock_persona",
            api_key_encrypted=None,
            api_base_url=None,
            model=None,
        ),
        SimpleNamespace(
            engine_key="b",
            display_name="B",
            enabled=True,
            sample_mode="openai_compat",
            api_key_encrypted="enc",
            api_base_url="https://x",
            model="m",
        ),
        SimpleNamespace(
            engine_key="c",
            display_name="C",
            enabled=False,
            sample_mode="openai_compat",
            api_key_encrypted=None,
            api_base_url=None,
            model=None,
        ),
    ]
    out = build_skip_preview(engines, monitoring_stance="real_only")
    assert out["enabled_will_skip"] == 1  # a
    assert out["enabled_will_run"] == 1  # b
    assert len(out["items"]) == 3
