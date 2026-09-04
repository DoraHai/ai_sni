import asyncio
import json
import os
from unittest.mock import patch

# 导入 app.ai 会连带加载 app.ai.judge，后者在 import 期就实例化 Settings。
for _name, _value in {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "BAIDU_APP_ID": "test",
    "BAIDU_SECRET_KEY": "test",
    "BAIDU_DEFAULT_USERNAME": "test",
    "BAIDU_DEFAULT_UCID": "0",
    "BAIDU_SELF_ACCESS_TOKEN": "test",
    "BAIDU_SELF_TOKEN_EXPIRES_AT": "2099-01-01T00:00:00Z",
    "CRYPTO_MASTER_KEY_B64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "ADMIN_API_KEY": "test-admin-key",
}.items():
    os.environ.setdefault(_name, _value)

from app.ai import deepseek  # noqa: E402

OTHER_MODELS = (
    "deepseek-v4-flash",
    "qwen3.8-max",
    "doubao-seed-2-1-pro-260628",
    "hunyuan-turbos-latest",
    "ernie-5.1",
)


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": json.dumps({"ok": 1})}}]}


class _CapturingClient:
    payloads: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, **kwargs):
        _CapturingClient.payloads.append(kwargs["json"])
        return _FakeResponse()


def _payload_sent_for(model, call):
    _CapturingClient.payloads = []
    creds = ("platform-key", "https://example.test/v1", model)
    with (
        patch.object(deepseek, "_resolve_creds", return_value=creds),
        patch.object(deepseek.httpx, "AsyncClient", _CapturingClient),
    ):
        asyncio.run(call())
    return _CapturingClient.payloads[0]


def test_kimi_k2_is_pinned_to_the_only_temperature_moonshot_accepts():
    assert deepseek.normalize_temperature("kimi-k2.6", 0.3) == 1.0
    assert deepseek.normalize_temperature("Kimi-K2.6", 0.9) == 1.0


def test_other_models_keep_the_requested_temperature():
    for model in OTHER_MODELS:
        assert deepseek.normalize_temperature(model, 0.3) == 0.3
        assert deepseek.normalize_temperature(model, 0.9) == 0.9


def test_missing_model_keeps_the_requested_temperature():
    assert deepseek.normalize_temperature(None, 0.3) == 0.3
    assert deepseek.normalize_temperature("", 0.3) == 0.3


def test_chat_json_sends_temperature_1_for_kimi():
    payload = _payload_sent_for("kimi-k2.6", lambda: deepseek.chat_json("s", "u"))
    assert payload["temperature"] == 1.0


def test_chat_json_keeps_judgement_temperature_for_other_models():
    for model in OTHER_MODELS:
        payload = _payload_sent_for(model, lambda: deepseek.chat_json("s", "u"))
        assert payload["temperature"] == 0.3


def test_chat_json_still_honours_an_explicit_temperature_for_other_models():
    payload = _payload_sent_for(
        "deepseek-v4-flash", lambda: deepseek.chat_json("s", "u", temperature=0.8)
    )
    assert payload["temperature"] == 0.8


def test_chat_messages_normalizes_kimi_without_touching_other_models():
    messages = [{"role": "user", "content": "hi"}]
    kimi = _payload_sent_for(
        "kimi-k2.6", lambda: deepseek.chat_messages(messages, temperature=0.5)
    )
    assert kimi["temperature"] == 1.0

    other = _payload_sent_for(
        "deepseek-v4-flash", lambda: deepseek.chat_messages(messages, temperature=0.5)
    )
    assert other["temperature"] == 0.5
