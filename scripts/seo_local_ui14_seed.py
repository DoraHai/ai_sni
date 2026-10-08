"""Explicit, append-only UI14 fixtures for the one approved local database."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

import seo_local_acceptance as runner
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import async_sessionmaker

TAG = "UI14-20261008"
CONTENT_KINDS = ("planned", "drafting", "review", "pending", "approved", "rejected", "stale", "archived")
TABLES = ("seo_content_assets", "seo_tasks", "seo_keyword_assets", "seo_site_pages",
          "seo_page_captures", "seo_content_confirmations")


def plans():
    return {
        "contents": [{"number": i + 1, "kind": CONTENT_KINDS[i % 8]} for i in range(60)],
        "keywords": [{"number": i + 1, "status": ("active", "paused", "archived")[i % 3]} for i in range(45)],
        "tasks": [{"number": i + 1, "status": ("open", "in_progress", "cancelled")[i % 3]} for i in range(45)],
    }


async def fingerprint(session, limits):
    result = {}
    for table, maximum in limits.items():
        assert table in TABLES
        rows = (await session.execute(text(f"SELECT row_to_json(t)::text FROM public.{table} t WHERE id<=:maximum"),
                                      {"maximum": maximum})).scalars().all()
        result[table] = hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()
    return result


async def seed():
    state = runner.read_state()
    if state.get("phase") != "verified_0105" or state["migration_hashes"] != runner.migration_hashes():
        raise ValueError("Expected unchanged, verified local migration lifecycle")
    if state.get("ui14_seed"):
        print(json.dumps({"already_seeded": True, "manifest": state["ui14_seed"]}))
        return
    url = runner.database_url()
    settings = runner.configure(url)
    if settings.seo_scheduler_enabled or settings.seo_external_actions_enabled or settings.seo_page_capture_enabled:
        raise ValueError("External actions and schedulers must remain disabled")
    from app.models.seo import SeoContentAsset, SeoKeywordAsset, SeoSitePage, SeoContentConfirmation
    from app.models.seo_cockpit import SeoTask
    from app.models.seo_page_capture import SeoPageCapture
    from app.models.module_workspace import SeoSite
    from app.api.seo import _content_confirmation_hash
    from app.seo_page_capture import capture_storage_path
    from PIL import Image, ImageDraw

    engine = runner.engine_for(url)
    data = plans()
    scope = state["seed"]["primary"]
    users = state["seed"]["users"]
    if scope != {"tenant_id": 1, "site_id": 1}:
        raise ValueError("UI14 is restricted to this lifecycle's primary synthetic tenant/site 1/1")
    media_root = runner.STATE_DIR / "ui14-media"
    media_root.mkdir(exist_ok=True)
    key = uuid4().hex + ".png"
    image_path = capture_storage_path(str(media_root), key)
    image = Image.new("RGB", (640, 240), "#eaf4fa")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 619, 219), outline="#126080", width=4)
    draw.text((45, 75), "UI14 SYNTHETIC IMAGE FIXTURE", fill="#123344")
    draw.text((45, 120), "Not a real page capture or publication proof.", fill="#123344")
    image.save(image_path)
    committed = False
    try:
        await runner.preflight(engine)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with session.begin():
                await session.execute(text("SELECT pg_advisory_xact_lock(14082026)"))
                site = await session.get(SeoSite, scope["site_id"])
                if not site or site.tenant_id != scope["tenant_id"] or site.domain != "seo12-primary.invalid":
                    raise ValueError("Synthetic site ownership mismatch")
                existing = await session.scalar(select(func.count()).select_from(SeoContentAsset).where(
                    SeoContentAsset.title.like(TAG + "%")))
                if existing:
                    raise ValueError("UI14 tag already exists without lifecycle receipt; reconcile, never replay")
                limits = {table: int((await session.execute(text(f"SELECT coalesce(max(id),0) FROM public.{table}"))).scalar_one())
                          for table in TABLES}
                before = await fingerprint(session, limits)
                now = datetime.now(timezone.utc)
                page = SeoSitePage(**scope, url=f"https://seo12-primary.invalid/{TAG}/image-fixture",
                                   title=TAG + " synthetic media holder", status="pending")
                session.add(page)
                await session.flush()
                captures = []
                for success in (True, False):
                    capture = SeoPageCapture(**scope, relation_type="site_page", relation_id=page.id,
                        source_url=page.url, status="succeeded" if success else "failed", source="manual",
                        uploaded_by=users["advisor"], uploaded_at=now, captured_at=now,
                        redirect_chain=[], warnings={"synthetic": True, "fixture_batch": TAG,
                            "not_publication_evidence": True}, content_type="image/png",
                        viewport_width=640, viewport_height=240,
                        image_width=640 if success else None, image_height=240 if success else None,
                        storage_key=key if success else None,
                        sha256=hashlib.sha256(image_path.read_bytes()).hexdigest() if success else None,
                        error_code=None if success else "fixture_missing_image")
                    session.add(capture)
                    await session.flush()
                    captures.append(capture.id)
                urls = [f"/api/v1/seo/site/page-captures/{ident}/image?tenant_id=1" for ident in captures]
                keywords = []
                for item in data["keywords"]:
                    row = SeoKeywordAsset(**scope, keyword=f"{TAG} keyword {item['number']:02d}",
                        status=item["status"], priority=f"P{(item['number'] - 1) % 4}", source="manual",
                        notes=TAG + " synthetic fixture; no ranking collection")
                    session.add(row)
                    await session.flush()
                    keywords.append(row.id)
                contents = []
                for item in data["contents"]:
                    kind, number = item["kind"], item["number"]
                    status = "ready" if kind in {"pending", "approved", "rejected", "stale"} else kind
                    body = (f'<h2>{TAG} synthetic draft {number:02d}</h2><p>No real business claims.</p>'
                            f'<img src="{urls[0]}" alt="Synthetic preview success">'
                            f'<img src="{urls[1]}" alt="Synthetic preview unavailable">')
                    row = SeoContentAsset(**scope, title=f"{TAG} draft {number:02d} [{kind}]", status=status,
                        content_type="article", draft=body, version_count=2 if kind == "stale" else 1,
                        keyword_id=keywords[(number - 1) % 45], keyword_ids=[keywords[(number - 1) % 45]],
                        created_by=users["advisor"], source_text=TAG + ": seeded state, not real review evidence",
                        review_note=TAG + " synthetic workflow state", updated_at=now.replace(tzinfo=None))
                    session.add(row)
                    await session.flush()
                    if kind in {"approved", "rejected", "stale"}:
                        session.add(SeoContentConfirmation(**scope, content_asset_id=row.id,
                            content_version=1, content_hash=_content_confirmation_hash(row),
                            decision="reject" if kind == "rejected" else "approve", actor_mode="customer_direct",
                            actor_user_id=users["customer"], actor_role_name="UI14 synthetic fixture",
                            note=TAG + ": seeded confirmation for UI only; no customer decision taken"))
                    contents.append({"id": row.id, "kind": kind, "status": status})
                tasks = []
                for item in data["tasks"]:
                    content = contents[item["number"] - 1]
                    task = SeoTask(**scope, module="seo", action_type="content_delivery",
                        title=f"{TAG} task {item['number']:02d}", status=item["status"],
                        created_by=str(users["advisor"]), assignee_role="advisor", completion_evidence=None,
                        baseline={}, params={"synthetic": True, "fixture_batch": TAG, "fixture_only": True,
                            "content_id": content["id"], "phase": "fixture_not_executed", "blocker": "synthetic_fixture",
                            "history": [], "source_version": 1})
                    session.add(task)
                    await session.flush()
                    tasks.append({"id": task.id, "status": task.status})
                if await fingerprint(session, limits) != before:
                    raise ValueError("Existing rows changed; rolling back all UI14 inserts")
                receipt = {"batch": TAG, "scope": scope, "contents": contents, "tasks": tasks,
                    "keyword_ids": keywords, "page_id": page.id, "capture_ids": captures, "image_paths": urls,
                    "image_file": str(image_path), "existing_rows_unchanged": before,
                    "content_kind_counts": dict(Counter(x["kind"] for x in contents)),
                    "task_status_counts": dict(Counter(x["status"] for x in tasks)),
                    "keyword_status_counts": dict(Counter(x["status"] for x in data["keywords"])),
                    "automation": "disabled; fixtures must not be executed", "created_at": now.isoformat()}
            committed = True
        state["ui14_seed"] = receipt
        runner.write_state(state)
        (runner.STATE_DIR / "ui14-fixtures.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt))
    finally:
        await engine.dispose()
        if not committed:
            image_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except Exception as exc:
        print(json.dumps({"status": "stopped", "error_type": type(exc).__name__,
                          "message": str(exc) if type(exc) is ValueError else "Inspect isolated lifecycle; no automatic replay"}))
        raise SystemExit(1)
