"""Offline publishing materials with bounded, SSRF-protected image downloads."""
import asyncio
import html
import io
import json
import time
import zipfile
from bs4 import BeautifulSoup
from app.seo_distribution import _download_wechat_image, sanitize_article_html, SeoDistributionError


async def build_publication_package(title, body, publication_id, source_version):
    if len(body) > 400000:
        raise ValueError("稿件过大，请先缩减正文")
    soup = BeautifulSoup(sanitize_article_html(body), "html.parser")
    images, records, downloaded = {}, [], {}
    deadline = time.monotonic() + 22
    total_bytes = 0
    for number, image in enumerate(soup.find_all("img"), 1):
        source = str(image.get("data-src") or image.get("src") or "").strip()
        image.attrs = {"alt": str(image.get("alt") or "")[:1000]}
        record = {"number":number,"source_url":source,"state":"failed"}
        try:
            if source in downloaded:
                filename = downloaded[source]
            else:
                remaining = deadline-time.monotonic()
                if number > 20 or total_bytes >= 12*1024*1024 or remaining <= 0:
                    raise ValueError("已达本次配图下载范围，请按清单补齐")
                name, data, _ = await asyncio.wait_for(_download_wechat_image(source,number,max_bytes=3*1024*1024),timeout=remaining)
                if total_bytes + len(data) > 12*1024*1024:
                    raise ValueError("配图合计超过 12MB，请按清单补齐")
                filename = "images/" + name
                images[filename] = data
                total_bytes += len(data)
                downloaded[source] = filename
            image["src"] = filename
            record.update(state="downloaded",filename=filename)
        except (ValueError, SeoDistributionError, TimeoutError) as exc:
            record["reason"] = "下载超时，请补传原图" if isinstance(exc, TimeoutError) else str(exc)
            image.replace_with(soup.new_string(f"[配图 {number} 未下载，请按清单补齐]"))
        records.append(record)
    # Offline HTML must never fetch remote resources automatically.
    for tag in soup.find_all(True):
        if tag.name != "img":
            tag.attrs.pop("src", None)
            tag.attrs.pop("data-src", None)
    manifest = {"publication_id":publication_id,"source_version":source_version,"title":title,
                "images":records,"downloaded":sum(r["state"]=="downloaded" for r in records),
                "missing":sum(r["state"]!="downloaded" for r in records)}
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(title)+'</title><body><h1>'+html.escape(title)+'</h1>'+str(soup)+'</body></html>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("article.html",page)
        archive.writestr("article.txt",title+'\n\n'+soup.get_text('\n',strip=True))
        archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2))
        archive.writestr("README.txt",f"任务 #{publication_id} / 版本 {source_version}\n已下载配图 {manifest['downloaded']} 张，需补齐 {manifest['missing']} 张。\n先查看 article.html，按 manifest.json 补齐缺失图片。正文和 images 目录可在平台上传；本材料包不会自动发布。\n图片只支持 JPG/PNG，每张最多 3MB，合计 12MB，最多处理 20 张。\n")
        for name, data in images.items():
            archive.writestr(name,data)
    return buffer.getvalue(), manifest
