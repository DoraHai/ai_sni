import asyncio

import httpx

from app import api_metering
from app.geo import ai_client
from app.geo.ai_client import _chat_json_payload, _provider_http_error


def response_error(status: int, body):
    request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
    response = httpx.Response(status, request=request, json=body)
    return httpx.HTTPStatusError("raw provider detail must not escape", request=request, response=response)


def test_model_not_found_is_definitive_and_safe():
    error = _provider_http_error(response_error(404, {
        "error": {"code": "model_not_found", "message": "secret upstream diagnostics"}
    }))
    assert error.category == "model_not_found"
    assert error.status_code == 404
    assert error.code == "model_not_found"
    assert "secret" not in str(error)


def test_provider_http_categories_do_not_collapse_to_unknown():
    cases = [(401, "authentication"), (429, "rate_limit"),
             (400, "invalid_request"), (503, "provider_unavailable")]
    for status, category in cases:
        error = _provider_http_error(response_error(status, {"error": {"type": "provider_error"}}))
        assert error.category == category
        assert error.status_code == status


def test_optional_generation_fields_are_absent_by_default_and_bounded_when_requested():
    default = _chat_json_payload("system", "user", "other-model")
    assert "enable_thinking" not in default
    assert "max_tokens" not in default
    onsite = _chat_json_payload("system", "user", "deepseek-v4-flash-0731",
                                enable_thinking=False, max_tokens=8192)
    assert onsite["enable_thinking"] is False
    assert onsite["max_tokens"] == 8192
    strict = {"type": "json_schema", "json_schema": {"name": "test", "schema": {}}}
    custom = _chat_json_payload("system", "user", "supported-model",
                                response_format=strict)
    assert custom["response_format"] == strict


def test_geo_client_uses_shared_metering_with_onsite_background_identity(monkeypatch):
    captured = {}

    async def metered(_client, method, url, **kwargs):
        captured.update(
            scope=api_metering.scope.get(), method=method, url=url,
            model=kwargs.get("model"), operation=kwargs.get("operation"),
        )
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": '{"items": []}'}}],
        })

    monkeypatch.setattr(ai_client, "metered_request", metered)

    async def run():
        with api_metering.background_scope(
            tenant_id=3, user_id=7, module="geo", operation="onsite.ai_proposal",
            job_ref="geo-onsite-ai:11:request",
        ):
            return await ai_client.chat_json(
                "system", "user", api_key="safe-test-key",
                base_url="https://provider.test/v1", model="model-test",
            )

    assert asyncio.run(run()) == {"items": []}
    assert captured["method"] == "post"
    assert captured["url"] == "https://provider.test/v1/chat/completions"
    assert captured["model"] == "model-test"
    assert captured["operation"] == "chat.completions"
    assert captured["scope"] == api_metering.MeterScope(
        tenant_id=3, user_id=7, origin="job", module="geo",
        operation="onsite.ai_proposal", job_ref="geo-onsite-ai:11:request",
    )
