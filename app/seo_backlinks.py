"""Public-page backlink evidence. A mention or inaccessible page is not a lost link."""
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from app.seo_serp import canonical_url


async def fetch_backlink_page(url):
    import asyncio
    from app.seo_crawler import fetch_url
    try:
        return await asyncio.wait_for(fetch_url(url), timeout=22)
    except TimeoutError:
        from types import SimpleNamespace
        return SimpleNamespace(body="", final_url=url, status_code=None, error_type="timeout")


async def discover_backlinks(session, tenant_id, site_id, source_url, domain):
    from sqlalchemy.dialects.postgresql import insert
    from app.models.seo import SeoBacklink
    if belongs_to_site(source_url, domain):
        return {"state": "internal", "reason": "same_site", "checked_at": datetime.utcnow().isoformat(), "found": 0, "created": 0, "links": []}
    result = await fetch_backlink_page(source_url)
    evidence = page_evidence(result)
    evidence["checked_at"] = datetime.utcnow().isoformat()
    links = extract_site_links(result.body, result.final_url, domain) if evidence["state"] == "readable" else []
    ids = []
    observed_at = datetime.utcnow()
    for link in links:
        observation = {**evidence, "state": "found", "rel": link["rel"]}
        observation["history"] = [dict(observation)]
        # Concurrent discoveries are idempotent; existing assets are verified separately.
        value = await session.scalar(insert(SeoBacklink).values(
            tenant_id=tenant_id, site_id=site_id, source_url=source_url,
            target_url=link["target_url"], source_domain=urlparse(source_url).hostname,
            anchor_text=link["anchor_text"], status="active", missing_checks=0,
            first_seen_at=observed_at, last_seen_at=observed_at,
            last_checked_at=observed_at, verification=observation,
        ).on_conflict_do_nothing(constraint="uq_seo_backlink_site_source_target").returning(SeoBacklink.id))
        if value is not None:
            ids.append(value)
    evidence.update(found=len(links), created=len(ids), links=links)
    return evidence


async def discover_published_backlinks():
    """Bounded recovery job also covers imported/API/manual publication records."""
    from sqlalchemy import select, or_, and_
    from app.database import async_session_factory
    from app.models.seo import SeoContentPublication, SeoContentAsset
    from app.models.module_workspace import SeoSite
    from app.module_scope import list_active_module_tenants
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    retry_cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    async with async_session_factory() as session:
        tenants = [row.id for row in await list_active_module_tenants(session, "seo")]
        if not tenants:
            return {"checked": 0}
        candidates = list((await session.execute(select(SeoContentPublication.id, SeoContentPublication.page_url,
            SeoContentPublication.tenant_id, SeoContentAsset.site_id, SeoSite.canonical_domain)
            .select_from(SeoContentPublication)
            .join(SeoContentAsset, SeoContentAsset.id == SeoContentPublication.content_asset_id)
            .join(SeoSite, SeoSite.id == SeoContentAsset.site_id)
            .where(SeoContentPublication.tenant_id.in_(tenants), SeoContentAsset.tenant_id == SeoContentPublication.tenant_id,
                   SeoSite.tenant_id == SeoContentPublication.tenant_id, SeoSite.status == "active",
                   SeoContentPublication.status == "published", SeoContentPublication.page_url.is_not(None),
                   or_(SeoContentPublication.link_discovery["checked_at"].astext.is_(None), SeoContentPublication.link_discovery["checked_at"].astext < cutoff,
                       and_(SeoContentPublication.link_discovery["state"].astext.in_(["unreachable", "blocked"]), SeoContentPublication.link_discovery["checked_at"].astext < retry_cutoff)))
            .order_by(SeoContentPublication.link_discovery["checked_at"].astext.asc().nullsfirst(), SeoContentPublication.id)
            .limit(20))).all())
    checked = 0
    for candidate in candidates:
        try:
            async with async_session_factory() as session:
                evidence = await discover_backlinks(session, candidate.tenant_id, candidate.site_id, candidate.page_url, candidate.canonical_domain)
                row = await session.get(SeoContentPublication, candidate.id, with_for_update=True)
                if row is None or row.page_url != candidate.page_url or row.status != "published":
                    await session.rollback()
                    continue
                row.link_discovery = evidence
                await session.commit()
                checked += 1
        except Exception:
            import logging
            logging.getLogger(__name__).exception("SEO publication discovery failed id=%s", candidate.id)
    return {"checked": checked}


def belongs_to_site(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    domain = domain.lower().rstrip(".").removeprefix("www.")
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def extract_site_links(body: str, source_url: str, domain: str) -> list[dict]:
    """Extract real HTTP anchors only; retain rel so nofollow is never sold as authority."""
    if belongs_to_site(source_url, domain):
        return []
    soup = BeautifulSoup(body, "html.parser")
    for element in soup.select("script,style,template,noscript"):
        element.decompose()
    base = soup.find("base", href=True)
    base_url = urljoin(source_url, str(base["href"])) if base else source_url
    links = {}
    for anchor in soup.select("a[href]"):
        target = urljoin(base_url, str(anchor["href"]))
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not belongs_to_site(target, domain):
            continue
        target = canonical_url(target)
        rel = sorted({str(value).lower() for value in anchor.get("rel", [])})
        links.setdefault(target, {"target_url": target, "anchor_text": anchor.get_text(" ", strip=True)[:1000], "rel": rel})
        if len(links) >= 100:
            break
    return list(links.values())


def page_evidence(result) -> dict:
    status = getattr(result, "status_code", None)
    error = getattr(result, "error_type", None)
    if error or not result.body or (status is not None and status != 200):
        return {"state": "unreachable", "http_status": status, "reason": error or ("http_error" if status else "empty_response"), "final_url": result.final_url}
    # Common challenge/login pages must not count toward the missing-link threshold.
    soup = BeautifulSoup(result.body, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if any(word in title.lower() for word in ("验证码", "安全验证", "访问验证", "登录", "sign in", "captcha", "just a moment")):
        return {"state": "blocked", "http_status": status, "reason": "login_or_challenge", "final_url": result.final_url}
    return {"state": "readable", "http_status": status, "final_url": result.final_url}


def apply_backlink_evidence(row, result, now=None) -> dict:
    now = now or datetime.utcnow()
    evidence = page_evidence(result)
    evidence["checked_at"] = now.isoformat()
    previous = getattr(row, "verification", None) or {}
    row.last_checked_at = now
    if evidence["state"] == "readable":
        domain = urlparse(row.target_url).hostname or ""
        links = extract_site_links(result.body, result.final_url, domain)
        match = next((link for link in links if canonical_url(link["target_url"]) == canonical_url(row.target_url)), None)
        if match:
            evidence.update(state="found", rel=match["rel"])
            row.anchor_text = match["anchor_text"]
            row.status = "active"
            row.first_seen_at = getattr(row, "first_seen_at", None) or now
            row.last_seen_at = now
            row.missing_checks = 0
        else:
            evidence["state"] = "missing"
            # Repeated button clicks are one observation, not independent loss evidence.
            last_missing = previous.get("last_missing_at")
            try:
                sufficiently_later = not last_missing or now - datetime.fromisoformat(last_missing) >= timedelta(hours=20)
            except (TypeError, ValueError):
                sufficiently_later = True
            if sufficiently_later:
                row.missing_checks = (row.missing_checks or 0) + 1
                last_missing = now.isoformat()
            evidence["last_missing_at"] = last_missing
            if row.missing_checks >= 2:
                row.status = "lost"
    elif previous.get("last_missing_at"):
        evidence["last_missing_at"] = previous["last_missing_at"]
    history = list(previous.get("history", []))[-19:]
    history.append({key: value for key, value in evidence.items() if key != "history"})
    evidence["history"] = history
    row.verification = evidence
    return evidence
