"""GEO 事实 CSV 导入单测。"""

import unittest

from app.geo.content.imports import parse_csv_rows, validate_fact_row, validate_prompt_row


class GeoFactImportTests(unittest.TestCase):
    def test_parse_csv_rows(self):
        raw = "title,statement,source_name\nProduct A,Supports on-prem,Whitepaper\n".encode("utf-8")
        rows = parse_csv_rows(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Product A")

    def test_validate_fact_row_ok(self):
        data = validate_fact_row(
            {
                "title": "Product",
                "statement": "Supports on-prem",
                "source_name": "Whitepaper",
                "fact_type": "product",
                "trust_level": "needs_review",
            }
        )
        self.assertEqual(data["title"], "Product")

    def test_validate_fact_row_missing_source(self):
        with self.assertRaises(ValueError):
            validate_fact_row(
                {
                    "title": "Product",
                    "statement": "Supports on-prem",
                    "source_name": "",
                    "trust_level": "verified",
                }
            )

    def test_validate_prompt_row(self):
        data = validate_prompt_row({"question": "Which platform is best", "priority": "2", "tags": "a,b"})
        self.assertEqual(data["priority"], 2)
        self.assertEqual(data["tags"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
