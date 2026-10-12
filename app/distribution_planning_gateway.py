"""Only the existing managed main gateway; never fall back to legacy direct HTTP."""
import json
import httpx
from contextlib import asynccontextmanager


@asynccontextmanager
async def planning_runtime(module,config):
    # A central worker can traverse SEO and GEO in one process. Do not inherit
    # another module's managed credential context; restore its caller afterward.
    token=config.current_settings.set(None)
    try:
        async with config.runtime_scope(module):yield
    finally:config.current_settings.reset(token)


class GatewayFailure(Exception):
    def __init__(self,code): self.code=code


async def suggest(snapshot,request_id):
    try:
        from app import api_metering as meter
        from app import api_connection_config as config
        from app.config import get_settings
    except ImportError:
        raise GatewayFailure('AI_GATEWAY_UNAVAILABLE') from None
    if not meter.enabled(): raise GatewayFailure('AI_METERING_REQUIRED')
    with meter.background_scope(tenant_id=snapshot['tenant_id'],module=snapshot['module'],
            operation='distribution_planning',user_id=snapshot['actor_id'],job_ref=str(request_id)):
        async with planning_runtime(snapshot['module'],config):
            settings=get_settings()
            dash=getattr(settings,'dashscope_api_key','')
            key=dash or getattr(settings,'deepseek_api_key','')
            if not key: raise GatewayFailure('AI_NOT_CONFIGURED')
            base=getattr(settings,'dashscope_base_url','') if dash else settings.deepseek_base_url
            model=getattr(settings,'dashscope_model','') if dash else settings.deepseek_model
            # Prompts contain only bounded authorized IDs, versions and allowed
            # times; no credentials, URLs, content body or arbitrary tools.
            prompt='只为给定队列提出顺序和候选时间。严格返回 {"items":[{"queue_id":字符串,"at":毫秒整数}]}；每项一次，不得新增或遗漏目标，时间不得早于 earliest_at。不调用工具，不发布。'
            payload={'model':model,'messages':[{'role':'system','content':prompt},
                {'role':'user','content':json.dumps(snapshot,ensure_ascii=False)}],
                'response_format':{'type':'json_object'},'temperature':0,'stream':False,'max_tokens':1500}
            async with httpx.AsyncClient(timeout=15) as client:
                try:
                    response=await meter.metered_request(client,'post',base.rstrip('/')+'/chat/completions',api_key=key,
                        model=model,operation='distribution_planning',json=payload,headers={'Authorization':'Bearer '+key})
                except httpx.TransportError as exc:
                    # The provider may have received and charged the request.
                    exc.provider_attempted=True
                    raise
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    exc.provider_attempted=True
                    raise
                data=response.json()
                content=data['choices'][0]['message']['content']
                if not isinstance(content,str) or len(content)>16000: raise GatewayFailure('AI_INVALID_OUTPUT')
                try: return json.loads(content)
                except (ValueError,TypeError): raise GatewayFailure('AI_INVALID_OUTPUT') from None
