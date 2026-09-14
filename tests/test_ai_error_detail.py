import httpx

from app.ai.deepseek import DeepSeekError, safe_ai_error_detail, safe_ai_error_message


def test_timeout_error_is_nonempty_and_structured():
    cause = httpx.ReadTimeout("")
    try:
        raise DeepSeekError("AI 调用/解析失败: ") from cause
    except DeepSeekError as exc:
        detail = safe_ai_error_detail(exc, provider="doubao")
        message = safe_ai_error_message(exc, provider="doubao")

    assert detail == {
        "provider": "doubao",
        "exception_class": "ReadTimeout",
        "http_status": None,
        "message": "provider request timed out",
    }
    assert message == (
        "provider=doubao; exception=ReadTimeout; message=provider request timed out"
    )


def test_http_error_reports_status_without_response_body_or_headers():
    request = httpx.Request(
        "POST",
        "https://provider.example/chat/completions",
        headers={"Authorization": "Bearer secret-key"},
    )
    response = httpx.Response(
        429,
        request=request,
        text='{"error":"sensitive provider response"}',
    )
    exc = httpx.HTTPStatusError("status", request=request, response=response)

    detail = safe_ai_error_detail(exc, provider="kimi")
    rendered = str(detail)

    assert detail["http_status"] == 429
    assert detail["exception_class"] == "HTTPStatusError"
    assert detail["message"] == "provider returned HTTP 429"
    assert "secret-key" not in rendered
    assert "sensitive provider response" not in rendered
