"""GEO article-import extraction and preview tests."""

import unittest

from app.geo.content.article_import import (
    ArticleImportError,
    preview_html_document,
    preview_text_document,
    source_word_count,
)
from app.geo.content.schemas import ArticleImportCreateTaskRequest


class GeoArticleImportTests(unittest.TestCase):
    def test_create_task_request_requires_import_source_fields(self):
        request = ArticleImportCreateTaskRequest(
            tenant_id=1,
            prompt_id=2,
            title="Imported article",
            body_markdown="Imported article body.",
            source_type="url",
            source_url="https://example.com/article",
            target_channels=["website"],
        )

        self.assertEqual(request.source_type, "url")
        self.assertEqual(request.target_channels, ["website"])

    def test_paste_import_allows_empty_source_url(self):
        request = ArticleImportCreateTaskRequest(
            tenant_id=1,
            prompt_id=2,
            title="Pasted article",
            body_markdown="Pasted body.",
            source_type="paste",
            source_url=None,
        )

        self.assertEqual(request.source_type, "paste")
        self.assertIsNone(request.source_url)

    def test_markdown_preview_uses_heading_and_counts_words(self):
        preview = preview_text_document(
            filename="guide.md",
            raw=b"# Product import\n\nThis is an article for preview.",
        )

        self.assertEqual(preview["title"], "Product import")
        self.assertEqual(preview["body_markdown"], "This is an article for preview.")
        self.assertEqual(preview["source_type"], "file")
        self.assertEqual(preview["source_url"], "guide.md")
        self.assertEqual(preview["word_count"], 6)

    def test_plain_text_preview_falls_back_to_filename_title(self):
        preview = preview_text_document(
            filename="product-notes.txt",
            raw=b"First paragraph.\n\nSecond paragraph.",
        )

        self.assertEqual(preview["title"], "product-notes")
        self.assertEqual(preview["body_markdown"], "First paragraph.\n\nSecond paragraph.")
        self.assertEqual(source_word_count(preview["body_markdown"]), 4)

    def test_html_preview_uses_article_content_and_document_title(self):
        preview = preview_html_document(
            html=(
                "<html><head><title>Imported page</title></head><body>"
                "<nav>Ignore navigation</nav><article><h1>Imported page</h1>"
                "<p>Useful article content.</p></article></body></html>"
            ),
            source_url="https://example.com/article",
        )

        self.assertEqual(preview["title"], "Imported page")
        self.assertEqual(preview["body_markdown"], "Imported page\n\nUseful article content.")
        self.assertEqual(preview["source_type"], "url")
        self.assertEqual(preview["source_url"], "https://example.com/article")

    def test_unsupported_file_type_is_rejected(self):
        with self.assertRaises(ArticleImportError):
            preview_text_document(filename="archive.zip", raw=b"not a document")

    def test_empty_document_is_rejected(self):
        with self.assertRaises(ArticleImportError):
            preview_text_document(filename="empty.txt", raw=b" \n\t ")


if __name__ == "__main__":
    unittest.main()
