"""Bounded, static HTML image evidence. No fetching or semantic AI judgment."""

from urllib.parse import urljoin, urlsplit

MAX_IMAGE_DETAILS = 200


def image_alt_evidence(soup, page_url):
    images = soup.select("img")
    counts = {"missing": 0, "empty": 0, "whitespace": 0}
    items = []
    base = soup.find("base", href=True)
    try:
        base_url = urljoin(page_url, str(base["href"])) if base else page_url
    except ValueError:
        base_url = page_url
    for position, image in enumerate(images, 1):
        alt = image.get("alt")
        if alt is not None and str(alt).strip():
            continue
        state = "missing" if alt is None else "empty" if alt == "" else "whitespace"
        counts[state] += 1
        if len(items) >= MAX_IMAGE_DETAILS:
            continue
        source_attribute = next((key for key in ("data-src", "data-original", "src") if str(image.get(key) or "").strip()), None)
        source = str(image.get(source_attribute) or "").strip() if source_attribute else ""
        # Store text only; never fetch images or expose executable/credential URLs.
        try:
            resolved = urljoin(base_url, source) if source else None
            parsed = urlsplit(resolved or "")
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                resolved = None
        except ValueError:
            resolved = None
        section = image.find_parent(["header", "nav", "main", "article", "aside", "footer"])
        items.append({
            "position": position,
            "section": section.name if section else "未标记区域",
            "element_id": str(image.get("id") or "")[:200],
            "source_url": resolved[:2048] if resolved else None,
            "source_url_truncated": bool(resolved and len(resolved) > 2048),
            "source_attribute": source_attribute,
            "srcset": str(image.get("srcset") or image.get("data-srcset") or "")[:1000],
            "alt_state": state,
            "in_link": image.find_parent("a") is not None,
            "role": str(image.get("role") or "")[:80],
        })
    total = sum(counts.values())
    return {"version": 1, "images_count": len(images), "candidate_count": total,
            "counts": counts, "items": items, "truncated": total > len(items),
            "limit": MAX_IMAGE_DETAILS, "source": "static_html"}
