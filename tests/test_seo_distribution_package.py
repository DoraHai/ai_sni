import asyncio
import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from app.seo_distribution_package import build_publication_package
from app.seo_distribution import SeoDistributionError


def test_materials_deduplicate_images_and_remove_remote_resource_loading():
    download=AsyncMock(return_value=('article-1.png',b'\x89PNG\r\n\x1a\nimage','image/png'))
    body='<p>正文</p><img src="https://cdn.example/a.png"><img data-src="https://cdn.example/a.png"><script>bad()</script><div src="https://evil.example/a">资料</div>'
    with patch('app.seo_distribution_package._download_wechat_image',download):
        blob,manifest=asyncio.run(build_publication_package('标题',body,7,2))
    download.assert_awaited_once()
    assert manifest['downloaded']==2 and manifest['missing']==0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        page=z.read('article.html').decode()
        assert page.count('src="images/article-1.png"')==2
        assert 'src="https://' not in page and 'bad()' not in page
        assert len([n for n in z.namelist() if n.startswith('images/')])==1
        assert json.loads(z.read('manifest.json'))['source_version']==2


def test_partial_download_includes_missing_manifest_and_offline_placeholder():
    with patch('app.seo_distribution_package._download_wechat_image',new=AsyncMock(side_effect=SeoDistributionError('图片域名无法解析'))):
        blob,manifest=asyncio.run(build_publication_package('标题','<img src="https://cdn.example/b.png">',7,2))
    assert manifest['missing']==1 and manifest['downloaded']==0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert '未下载' in z.read('article.html').decode()
        assert 'src="https://' not in z.read('article.html').decode()


def test_materials_refuse_cross_tenant_and_stale_version_before_fetch():
    from app.api.seo import download_publication_materials, DistributionMaterialsRequest
    from fastapi import HTTPException
    ctx=SimpleNamespace(ensure_tenant=lambda _:None)
    row=SimpleNamespace(tenant_id=2,content_asset_id=3,source_version=2)
    session=SimpleNamespace(get=AsyncMock(return_value=row))
    request=DistributionMaterialsRequest(tenant_id=1,site_id=9,source_version=2)
    with patch('app.api.seo._seo_site',new=AsyncMock()),patch('app.seo_distribution_package.build_publication_package',new=AsyncMock()) as download:
        with pytest.raises(HTTPException) as exc:asyncio.run(download_publication_materials(7,request,session,ctx))
        assert exc.value.status_code==404
        row.tenant_id=1
        with patch('app.api.seo._distribution_content',new=AsyncMock(return_value=SimpleNamespace(version_count=3))):
            with pytest.raises(HTTPException) as exc:asyncio.run(download_publication_materials(7,request,session,ctx))
            assert exc.value.status_code==409
        download.assert_not_called()
