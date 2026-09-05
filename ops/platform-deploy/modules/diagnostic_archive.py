"""Validate diagnostic release members before privileged extraction."""
import sys
import tarfile
from pathlib import PurePosixPath


def validate(path):
    seen = set()
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = member.name.rstrip("/")
            parts = PurePosixPath(name).parts
            if not parts or parts[0] != "diagnostic-release" or ".." in parts:
                raise ValueError("archive path outside diagnostic-release")
            if not (member.isfile() or member.isdir()):
                raise ValueError("links and special files are forbidden")
            if name in seen:
                raise ValueError("duplicate archive member")
            seen.add(name)
            if any(p == ".env" or p.endswith(".env") for p in parts):
                raise ValueError("environment files are forbidden")
            allowed = (
                name in {"diagnostic-release", "diagnostic-release/MANIFEST",
                         "diagnostic-release/backend", "diagnostic-release/frontend",
                         "diagnostic-release/backend/requirements.txt"}
                or name.startswith("diagnostic-release/backend/app/")
                or name == "diagnostic-release/backend/app"
                or name.startswith("diagnostic-release/frontend/")
            )
            if not allowed:
                raise ValueError("unexpected release member")
            total += member.size
            if total > 500 * 1024 * 1024 or len(seen) > 20000:
                raise ValueError("expanded archive limit exceeded")


if __name__ == "__main__":
    validate(sys.argv[1])
