from __future__ import annotations

import re
from pathlib import Path


_FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DEFAULT_RELEASE_ROOT = Path(__file__).resolve().parent.parent


def read_release_commit(release_root: Path | None = None) -> str | None:
    """Return the platform-managed release SHA without exposing arbitrary data."""
    commit_path = (release_root or _DEFAULT_RELEASE_ROOT) / "RELEASE_COMMIT"
    try:
        value = commit_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    return value if _FULL_GIT_SHA.fullmatch(value) else None
