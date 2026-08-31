from app.seo_monitoring_jobs import backlink_present


def test_backlink_verification_normalizes_relative_and_tracking_urls() -> None:
    body = '<html><a href="/target/?utm_source=partner#section">Brand</a></html>'

    assert backlink_present(
        body,
        "https://partner.example/article",
        "https://partner.example/target",
    ) is True
    assert backlink_present(
        body,
        "https://partner.example/article",
        "https://brand.example/target",
    ) is False
