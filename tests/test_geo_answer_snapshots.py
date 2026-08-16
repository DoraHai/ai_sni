"""GEO Wave B / B3 answer snapshot helpers."""

from datetime import datetime, timezone
import unittest

from app.geo.content.snapshots import (
    apply_brand_mention_tags,
    clear_brand_missing_tag,
    domain_matches,
    ensure_brand_missing_tag,
    extract_cited_domain,
    extract_cited_domains,
    extract_cited_urls_from_text,
    infer_citation_format,
    needs_recheck,
    normalize_brand_position,
    normalize_citation_accuracy,
    normalize_citation_format,
    normalize_cited_urls,
    normalize_competitors,
    normalize_sentiment,
    resolve_citation_format,
    visibility_mention_rate,
)


class SnapshotHelpersTests(unittest.TestCase):
    def test_clear_brand_missing(self):
        self.assertEqual(
            clear_brand_missing_tag(["high_demand", "brand_missing", "demo"]),
            ["high_demand", "demo"],
        )
        self.assertEqual(clear_brand_missing_tag(["high_demand"]), ["high_demand"])
        self.assertEqual(clear_brand_missing_tag(None), [])
        self.assertEqual(clear_brand_missing_tag([]), [])

    def test_ensure_brand_missing(self):
        self.assertEqual(
            ensure_brand_missing_tag(["high_demand"]),
            ["high_demand", "brand_missing"],
        )
        self.assertEqual(
            ensure_brand_missing_tag(["brand_missing"]),
            ["brand_missing"],
        )
        self.assertEqual(ensure_brand_missing_tag(None), ["brand_missing"])

    def test_apply_brand_mention_tags_symmetric(self):
        self.assertEqual(
            apply_brand_mention_tags(["high_demand", "brand_missing"], mentions_brand=True),
            ["high_demand"],
        )
        self.assertEqual(
            apply_brand_mention_tags(["high_demand"], mentions_brand=False),
            ["high_demand", "brand_missing"],
        )
        self.assertEqual(
            apply_brand_mention_tags(["brand_missing"], mentions_brand=False),
            ["brand_missing"],
        )

    def test_needs_recheck(self):
        t0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
        t1 = datetime(2026, 7, 2, tzinfo=timezone.utc)
        self.assertFalse(
            needs_recheck(
                has_published_task=False,
                task_updated_at=t1,
                last_snapshot_at=None,
            )
        )
        self.assertTrue(
            needs_recheck(
                has_published_task=True,
                task_updated_at=t1,
                last_snapshot_at=None,
            )
        )
        self.assertTrue(
            needs_recheck(
                has_published_task=True,
                task_updated_at=t1,
                last_snapshot_at=t0,
            )
        )
        self.assertFalse(
            needs_recheck(
                has_published_task=True,
                task_updated_at=t0,
                last_snapshot_at=t1,
            )
        )

    def test_normalize_cited_urls(self):
        urls = normalize_cited_urls(
            [" https://a.com ", "https://a.com", "", "https://b.com"]
        )
        self.assertEqual(urls, ["https://a.com", "https://b.com"])
        self.assertEqual(normalize_cited_urls(None), [])

    def test_extract_cited_domain(self):
        self.assertEqual(extract_cited_domain("https://www.Zhihu.com/question/1"), "zhihu.com")
        self.assertEqual(extract_cited_domain("zhuanlan.zhihu.com/p/1"), "zhuanlan.zhihu.com")
        self.assertEqual(extract_cited_domain("not a url :::"), None)
        self.assertEqual(extract_cited_domain(""), None)
        self.assertEqual(
            extract_cited_domains(
                [
                    "https://www.zhihu.com/q/1",
                    "https://zhihu.com/q/2",
                    "https://toutiao.com/a/1",
                    "",
                ]
            ),
            ["zhihu.com", "toutiao.com"],
        )
        self.assertTrue(domain_matches("mp.weixin.qq.com", "qq.com"))
        self.assertFalse(domain_matches("example.com", "ample.com"))

    def test_extract_cited_urls_from_text(self):
        text = (
            "可参考 https://www.zhihu.com/question/1 。"
            "另见（https://toutiao.com/a/2）。"
            "重复 https://www.zhihu.com/question/1 与 ftp://ignore.me/x"
        )
        self.assertEqual(
            extract_cited_urls_from_text(text),
            ["https://www.zhihu.com/question/1", "https://toutiao.com/a/2"],
        )
        self.assertEqual(extract_cited_urls_from_text("没有链接"), [])
        self.assertEqual(extract_cited_urls_from_text(""), [])

    def test_normalize_competitors(self):
        self.assertEqual(
            normalize_competitors([" A ", "A", "", "B"]),
            ["A", "B"],
        )
        self.assertEqual(normalize_competitors(None), [])

    def test_normalize_position_sentiment(self):
        self.assertEqual(normalize_brand_position("first"), "first")
        self.assertEqual(normalize_brand_position("alternative"), "alternative")
        self.assertEqual(normalize_brand_position("备选"), "alternative")
        self.assertEqual(normalize_brand_position("nope"), "unknown")
        self.assertEqual(normalize_sentiment("NEGATIVE"), "negative")
        self.assertEqual(normalize_sentiment(""), "unknown")

    def test_citation_format_and_accuracy(self):
        self.assertEqual(normalize_citation_format("link"), "linked")
        self.assertEqual(normalize_citation_format("纯文本"), "plaintext")
        self.assertEqual(normalize_citation_format("bogus"), "unknown")
        self.assertEqual(normalize_citation_accuracy("ok"), "accurate")
        self.assertEqual(normalize_citation_accuracy("wrong"), "inaccurate")
        self.assertEqual(
            infer_citation_format(
                cited_urls=["https://a.com"],
                raw_text="见 https://a.com",
                mentions_brand=True,
            ),
            "linked",
        )
        self.assertEqual(
            infer_citation_format(
                cited_urls=[],
                raw_text="推荐某某品牌",
                mentions_brand=True,
            ),
            "plaintext",
        )
        self.assertEqual(
            infer_citation_format(
                cited_urls=["https://a.com"],
                raw_text="推荐某某品牌",
                mentions_brand=True,
            ),
            "mixed",
        )
        self.assertEqual(
            infer_citation_format(cited_urls=[], raw_text="无关", mentions_brand=False),
            "none",
        )
        self.assertEqual(
            resolve_citation_format(
                "plaintext",
                cited_urls=["https://a.com"],
                raw_text="见 https://a.com",
                mentions_brand=True,
            ),
            "plaintext",
        )
        self.assertEqual(
            resolve_citation_format(
                "unknown",
                cited_urls=[],
                raw_text="推荐品牌",
                mentions_brand=True,
            ),
            "plaintext",
        )

    def test_visibility_mention_rate(self):
        self.assertIsNone(
            visibility_mention_rate(total_snapshots=0, mention_snapshots=0)
        )
        self.assertEqual(
            visibility_mention_rate(total_snapshots=4, mention_snapshots=1),
            0.25,
        )


if __name__ == "__main__":
    unittest.main()
