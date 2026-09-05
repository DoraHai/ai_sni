"""Bounded public-network requests with DNS validation bound to the connection."""
import httpx

from app.geo.audit import _ensure_public_host, GeoAuditError


def development_mode():
    from app.config import get_settings
    return str(get_settings().app_env or '').lower() in {'dev', 'development', 'local', 'test'}


async def public_request(client, method, url, *, addresses=None, allow_http=False,
                         max_bytes=4 * 1024 * 1024, headers=None, **kwargs):
    original = httpx.URL(url)
    if original.scheme not in ({'https', 'http'} if allow_http else {'https'}) or original.userinfo:
        raise httpx.HTTPError('必须使用无内嵌凭证的公网 HTTPS 地址')
    try:
        ips = addresses or await _ensure_public_host(str(original))
    except GeoAuditError as exc:
        raise httpx.HTTPError('目标地址不允许访问') from exc
    if not ips:
        raise httpx.HTTPError('目标地址未通过公网校验')
    outgoing = {k: v for k, v in (headers or {}).items() if k.lower() not in {'host', 'connection'}}
    outgoing.update({'Host': original.netloc.decode('ascii'), 'Connection': 'close'})
    request = client.build_request(method, original.copy_with(host=ips[0]), headers=outgoing,
        extensions={'sni_hostname': original.raw_host.decode('ascii')}, **kwargs)
    response = await client.send(request, stream=True, follow_redirects=False)
    body = bytearray()
    try:
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise httpx.HTTPError('远端响应超过允许大小')
        decoded_headers = {k: v for k, v in response.headers.items()
                           if k.lower() not in {'content-encoding', 'content-length', 'transfer-encoding'}}
        return httpx.Response(response.status_code, headers=decoded_headers, content=bytes(body), request=request)
    finally:
        await response.aclose()
