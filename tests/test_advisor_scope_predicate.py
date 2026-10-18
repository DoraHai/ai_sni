"""Role-side fixtures from schema-plan §7.2; account gates remain separate."""
from types import SimpleNamespace

import pytest

from app.security.advisor_scope import is_advisor


SEO = {"seo.site": "edit", "seo.content": "edit"}
GEO = {"geo.assets": "edit", "geo.content": "edit"}


@pytest.mark.parametrize("name,system,permissions,expected", [
    ("管理员", True, {}, False),
    ("管理员", True, SEO, False),
    ("arbitrary custom name", False, SEO, True),
    ("管理员", False, SEO, True),
    ("GEO only", False, GEO, True),
    ("both", False, SEO | GEO, True),
    ("settings registered", False, SEO | {"settings.accounts": "edit"}, False),
    ("settings unknown SEO", False, SEO | {"settings.future": "edit"}, False),
    ("settings unknown GEO", False, GEO | {"settings.future": "edit"}, False),
    ("settings empty suffix", False, SEO | {"settings.": "edit"}, False),
    ("settings view", False, SEO | {"settings.future": "view"}, True),
    ("settings wrong case", False, SEO | {"settings.future": "EDIT"}, True),
    ("settings nested value", False, SEO | {"settings.future": {"level": "edit"}}, True),
    ("brand read only", False, {k: "view" for k in SEO | GEO}, False),
    ("SEM only", False, {"optimize.keywords": "edit"}, False),
    ("SEO one edit", False, {"seo.site": "edit"}, False),
    ("SEO mixed", False, {"seo.site": "edit", "seo.content": "view"}, False),
    ("GEO one edit", False, {"geo.assets": "edit"}, False),
    ("cross combination", False, {"seo.site": "edit", "geo.content": "edit"}, False),
    ("null JSON", False, None, False),
    ("array JSON", False, [SEO], False),
    ("string JSON", False, "seo.site=edit,seo.content=edit", False),
    ("number JSON", False, 1, False),
    ("boolean JSON", False, True, False),
], ids=lambda value: value if isinstance(value, str) else None)
def test_schema_7_2_role_fixtures(name, system, permissions, expected):
    # Non-object JSON is ineligible here; the backfill preflight must block it.
    role = SimpleNamespace(name=name, is_system=system, permissions=permissions)
    assert is_advisor(role) is expected


def test_no_role_is_not_advisor():
    assert is_advisor(None) is False
