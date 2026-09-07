"""Contracts for the public portal entry into the authenticated cockpit."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_portal_points_to_the_real_acquisition_cockpit():
    portal = _read("frontend/public/deal-sniper-prototype/index.html")

    assert '<a class="hubcard" href="/workspace/cockpit" target="_top">' in portal
    assert "G-Snipers 获客工作台" in portal
    assert "AI 对话" in portal
    assert "数据总览" in portal
    assert "紧急事项" in portal
    assert "行动台账" in portal
    assert "进入获客工作台 →" in portal


def test_public_portal_drops_the_retired_platform_names():
    portal = _read("frontend/public/deal-sniper-prototype/index.html")

    assert "SEM · SEO · GEO 智能获客平台" in portal
    assert "全域层" not in portal
    assert "全域驾驶舱" not in portal
    assert "进入全域层" not in portal
    assert "原型 Demo" not in portal
    assert "静态原型" not in portal
    assert 'href="hub/dashboard.html' not in portal


def test_public_portal_keeps_all_four_module_entries():
    portal = _read("frontend/public/deal-sniper-prototype/index.html")

    assert '<a class="module sem"' in portal
    assert '<a class="module seo"' in portal
    assert '<a class="module geo"' in portal
    assert 'class="module content-c"' in portal
    assert "SEM 模块" in portal
    assert "SEO 模块" in portal
    assert "GEO 模块" in portal
    assert "诊断中心" in portal
