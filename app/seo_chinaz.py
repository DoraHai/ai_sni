"""SEO-only guarded entry to the existing Chinaz parsers and metering."""
import asyncio
import httpx

from app.geo import chinaz
from app.api_connection_config import managed_runtime
from app import seo_automation_boundary as boundary


class GuardedClient(httpx.AsyncClient):
    async def get(self,url,**kwargs):
        async def send(client,method,target,**params):
            return await super(GuardedClient,self).get(target,**params)
        return await boundary.provider_call(send,self,'get',url,**kwargs)


@managed_runtime('seo')
async def fetch_index(url):
    async with GuardedClient() as client:
        return await chinaz.fetch_baidu_index_count(url,client=client,
            **({} if chinaz.get_settings().chinaz_api_enabled else {'api_key':''}))


@managed_runtime('seo')
async def fetch_metrics(url):
    # Reuse all original provider/parser/cache paths; only the client gets a gate.
    async with GuardedClient() as client:
        options={'client':client}
        if not chinaz.get_settings().chinaz_api_enabled: options['api_key']=''
        values=await asyncio.gather(*(fn(url,**options) for fn in (
            chinaz.fetch_baidu_index_count,chinaz.fetch_baidu_pc_keywords,chinaz.fetch_baidu_mobile_keywords,
            chinaz.fetch_comprehensive_weight,chinaz.fetch_whois)))
    return dict(zip(('baidu_index','baidu_pc_keywords','baidu_mobile_keywords','comprehensive_weight','whois'),values))
