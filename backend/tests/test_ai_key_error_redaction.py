"""Connection test errors must not echo credentials or raw provider responses."""

from backend.services import ai_service, llm_config


def test_http_error_context_removes_url_credentials_query_and_fragment():
    class Request:
        method = "POST"
        url = "https://user:password@api.example.test/v1/chat/completions?api_key=query-secret#fragment-secret"

    class Response:
        request = Request()

    class HttpError(Exception):
        response = Response()
        status_code = 401

    context = ai_service._http_request_ctx(HttpError())

    assert context == "POST https://api.example.test/v1/chat/completions → HTTP 401"
    assert "password" not in context
    assert "query-secret" not in context
    assert "fragment-secret" not in context


def test_generic_provider_exception_is_not_returned_to_the_client(monkeypatch):
    class FailingModel:
        def invoke(self, _messages):
            raise RuntimeError("provider echoed sensitive-test-value")

    monkeypatch.setattr(llm_config, "build_llm", lambda _cfg: FailingModel())
    cfg = llm_config.LLMConfig(base_url="https://api.example.test/v1", model="test", api_key="test-only-key")

    success, message = ai_service.test_key(cfg)

    assert success is False
    assert message == "连接失败。请检查接口地址、模型名和服务状态。"
    assert "sensitive-test-value" not in message
