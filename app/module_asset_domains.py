from urllib.parse import urlparse

from fastapi import HTTPException


def canonical_domain(value: str) -> tuple[str, str]:
    """Normalize a module asset domain while preserving the submitted URL."""
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(400, "请填写网站域名")
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower().strip(".")
    if not host or "." not in host:
        raise HTTPException(400, "网站域名格式不正确")
    if host.startswith("www."):
        host = host[4:]
    return host, candidate
