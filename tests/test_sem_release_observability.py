from pathlib import Path

from app.release import read_release_commit


VALID_SHA = "8b8521cf6bdddbecf3e1e26ce7c5cab0fa515eee"


def test_release_commit_accepts_only_full_lowercase_git_sha(tmp_path: Path) -> None:
    (tmp_path / "RELEASE_COMMIT").write_text(f"{VALID_SHA}\n", encoding="utf-8")

    assert read_release_commit(tmp_path) == VALID_SHA


def test_release_commit_is_absent_when_marker_is_missing(tmp_path: Path) -> None:
    assert read_release_commit(tmp_path) is None


def test_release_commit_rejects_untrusted_marker_content(tmp_path: Path) -> None:
    for value in (
        "8b8521cf6bdd",
        VALID_SHA.upper(),
        f"{VALID_SHA}\nsecret=value",
        "../current",
    ):
        (tmp_path / "RELEASE_COMMIT").write_text(value, encoding="utf-8")
        assert read_release_commit(tmp_path) is None



def test_health_exposes_only_validated_release_commit_and_keeps_guard() -> None:
    main_source = Path("app/main.py").read_text(encoding="utf-8")
    assert '"release_commit": read_release_commit()' in main_source
    assert "enforce_production_secrets(settings, hard_fail=True)" in main_source
