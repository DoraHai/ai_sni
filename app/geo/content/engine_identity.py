"""Conservative, credential-free identity checks on saved request metadata."""
import re


def trusted_engine_source(engine, provider, model):
    engine = str(engine or '').strip().lower()
    provider = str(provider or '').strip().lower()
    model = str(model or '').strip().lower()
    if not model:
        return False
    prefixes = {
        'deepseek': ('deepseek',), 'qwen': ('qwen', 'qwq'),
        'doubao': ('doubao', 'ep-'), 'hunyuan': ('hunyuan',),
        'wenxin': ('ernie',), 'kimi': ('kimi', 'moonshot'),
        'chatgpt': ('gpt-', 'chatgpt-', 'o1', 'o3', 'o4'),
        'perplexity': ('sonar',),
    }
    providers = {engine}
    if engine == 'deepseek':
        providers |= {'dashscope:deepseek', 'dashscope'}
    if engine == 'chatgpt':
        providers.add('openai')
    if engine == 'wenxin':
        providers.add('qianfan')
    # A deployment ID is only acceptable with the dedicated doubao provider.
    # Never infer the platform from the requested engine alone.
    return (provider in providers and engine in prefixes
            and any(re.match(r'^' + re.escape(prefix), model) for prefix in prefixes[engine]))
