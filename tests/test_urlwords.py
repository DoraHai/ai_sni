from unittest.mock import patch

from app.urlwords import extract_words


def test_extract_words_filters_common_english_navigation_noise() -> None:
    with patch(
        "app.urlwords.jieba.analyse.extract_tags",
        return_value=["home", "About", "contact", "read", "NORDAC", "BU0000"],
    ):
        words = extract_words("NORDAC BU0000", "ignored")

    assert "home" not in words
    assert "About" not in words
    assert "contact" not in words
    assert "read" not in words
    assert words == ["NORDAC", "BU0000"]
