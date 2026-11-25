"""Unit tests for GeminiLLMService with mocks and client tests."""

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import ClientError, ServerError

from backend.config.settings import LLMSettings, Settings
from backend.services.llm_service import (
    GeminiLLMService,
    _classify_api_error,
    gemini_error_message,
    _supports_sampling_parameters,
)


def _service(
    fallback_models=("gemini-fallback-a", "gemini-fallback-b"),
    max_retries_per_model=1,
    daily_quota_cooldown_seconds=3600,
):
    llm_settings = replace(
        LLMSettings(),
        api_key="unit-test-key",
        model="gemini-primary",
        fallback_models=fallback_models,
        fallback_enabled=True,
        max_retries_per_model=max_retries_per_model,
        model_cooldown_seconds=60,
        daily_quota_cooldown_seconds=daily_quota_cooldown_seconds,
        max_retry_delay_seconds=1,
    )
    service = GeminiLLMService(Settings(llm=llm_settings))
    service._client = MagicMock()
    return service


def test_llm_service_missing_api_key():
    with patch("backend.services.llm_service.get_settings") as mock_settings:
        mock_settings.return_value.llm.api_key = None
        mock_settings.return_value.llm.model = "gemini-3.1-flash-lite"
        service = GeminiLLMService()
        service.api_key = None
        res = service.generate("Hello")
        assert res.success is False
        assert res.error_code == "GEMINI_API_KEY_MISSING"
        assert "LLM_API_KEY" in res.error


def _error(error_type, status, message="private-provider-payload", details=None):
    return error_type(
        status,
        {
            "error": {
                "code": status,
                "status": "RESOURCE_EXHAUSTED" if status == 429 else "FAILED",
                "message": message,
                "details": details or [],
            }
        },
    )


def _response(text='{"answer":"ok"}'):
    response = MagicMock()
    response.text = text
    response.candidates = []
    return response


def test_llm_service_successful_mock_generate():
    service = _service(fallback_models=())
    service.client.models.generate_content.return_value = _response(
        '{"status":"success","sql":"SELECT 1"}'
    )

    res = service.generate("Generate query")
    assert res.success is True
    assert res.model == "gemini-primary"
    assert "SELECT 1" in res.text
    assert res.attempted_models == ("gemini-primary",)
    assert res.attempt_count == 1


def test_primary_429_falls_back_without_repeating_quota_exhausted_model(caplog):
    service = _service(max_retries_per_model=2)
    service.client.models.generate_content.side_effect = [
        _error(
            ClientError,
            429,
            details=[{"quotaId": "GenerateRequestsPerModelPerDay"}],
        ),
        _response(),
    ]

    result = service.generate("same task", response_mime_type="application/json")

    assert result.success is True
    assert result.model == "gemini-fallback-a"
    assert result.attempted_models == ("gemini-primary", "gemini-fallback-a")
    assert result.attempt_count == 2
    assert service.client.models.generate_content.call_count == 2
    assert "private-provider-payload" not in caplog.text
    assert "unit-test-key" not in caplog.text


def test_primary_503_falls_back_after_bounded_retry():
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = [
        _error(ServerError, 503),
        _response(),
    ]

    result = service.generate(
        "same task",
        system_instruction="same instruction",
        response_mime_type="application/json",
    )

    assert result.success is True
    assert result.model == "gemini-fallback-a"
    assert result.attempt_count == 2
    calls = service.client.models.generate_content.call_args_list
    assert [call.kwargs["contents"] for call in calls] == [
        "same task",
        "same task",
    ]
    assert [
        call.kwargs["config"].response_mime_type for call in calls
    ] == ["application/json", "application/json"]
    assert [
        call.kwargs["config"].system_instruction for call in calls
    ] == ["same instruction", "same instruction"]


def test_short_rate_limit_retries_once_after_retry_after(monkeypatch):
    service = _service(
        fallback_models=("gemini-fallback-a",),
        max_retries_per_model=1,
    )
    rate_limit = _error(
        ClientError,
        429,
        message="requests per minute quota exceeded",
    )
    rate_limit.response = MagicMock()
    rate_limit.response.headers = {"retry-after": "0.25"}
    service.client.models.generate_content.side_effect = [rate_limit, _response()]
    sleep = MagicMock()
    monkeypatch.setattr("backend.services.llm_service.time.sleep", sleep)

    result = service.generate("same task")

    assert result.success is True
    assert result.model == "gemini-primary"
    assert result.attempt_count == 2
    sleep.assert_called_once_with(0.25)


def test_server_retry_after_is_respected_when_within_configured_bound(monkeypatch):
    service = _service(
        fallback_models=(),
        max_retries_per_model=1,
    )
    unavailable = _error(ServerError, 503)
    unavailable.response = MagicMock()
    unavailable.response.headers = {"retry-after": "0.5"}
    service.client.models.generate_content.side_effect = [
        unavailable,
        _response(),
    ]
    sleep = MagicMock()
    monkeypatch.setattr("backend.services.llm_service.time.sleep", sleep)

    result = service.generate("same task")

    assert result.success is True
    assert result.attempt_count == 2
    sleep.assert_called_once_with(0.5)


def test_timeout_falls_back_to_next_configured_model():
    service = _service(
        fallback_models=("gemini-fallback-a",),
        max_retries_per_model=0,
    )
    service.client.models.generate_content.side_effect = [
        TimeoutError("private timeout detail"),
        _response(),
    ]

    result = service.generate("same task")

    assert result.success is True
    assert result.model == "gemini-fallback-a"
    assert result.error is None


def test_fallback_continues_through_multiple_models():
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = [
        _error(ServerError, 503),
        _error(ClientError, 404),
        _response(),
    ]

    result = service.generate("same task")

    assert result.success is True
    assert result.model == "gemini-fallback-b"
    assert result.attempted_models == (
        "gemini-primary",
        "gemini-fallback-a",
        "gemini-fallback-b",
    )
    assert result.attempt_count == 3


def test_all_models_failing_returns_controlled_error():
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = [
        _error(ServerError, 503),
        _error(ServerError, 502),
        _error(ServerError, 504),
    ]

    result = service.generate("same task")

    assert result.success is False
    assert result.model is None
    assert result.error_code == "GEMINI_PROVIDER_UNAVAILABLE"
    assert result.attempted_models == (
        "gemini-primary",
        "gemini-fallback-a",
        "gemini-fallback-b",
    )
    assert result.attempt_count == 3


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_stop_without_model_switching(status):
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = _error(ClientError, status)

    result = service.generate("same task")

    assert result.error_code == "GEMINI_AUTHENTICATION_FAILED"
    assert result.provider_status == status
    assert result.attempted_models == ("gemini-primary",)
    assert service.client.models.generate_content.call_count == 1


def test_arbitrary_bad_request_does_not_fall_back():
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = _error(
        ClientError,
        400,
        message="Malformed request field",
    )

    result = service.generate("same task")

    assert result.error_code == "GEMINI_API_ERROR"
    assert result.attempted_models == ("gemini-primary",)
    assert service.client.models.generate_content.call_count == 1


def test_model_specific_response_format_incompatibility_can_fall_back():
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = [
        _error(
            ClientError,
            400,
            message="This model does not support response_mime_type application/json",
        ),
        _response(),
    ]

    result = service.generate("same task", response_mime_type="application/json")

    assert result.success is True
    assert result.model == "gemini-fallback-a"


def test_invalid_json_response_falls_back_to_next_model():
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = [
        _response("not-json"),
        _response(),
    ]

    result = service.generate("same task", response_mime_type="application/json")

    assert result.success is True
    assert result.model == "gemini-fallback-a"


def test_circuit_breaker_skips_model_after_repeated_transient_failures():
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = [
        _error(ServerError, 503),
        _response(),
        _error(ServerError, 503),
        _response(),
        _response(),
    ]

    service.generate("first")
    service.generate("second")
    third = service.generate("third")

    assert third.success is True
    assert third.model == "gemini-fallback-a"
    called_models = [
        call.kwargs["model"]
        for call in service.client.models.generate_content.call_args_list
    ]
    assert called_models == [
        "gemini-primary",
        "gemini-fallback-a",
        "gemini-primary",
        "gemini-fallback-a",
        "gemini-fallback-a",
    ]


def test_daily_quota_cooldown_expires_and_model_is_retried(monkeypatch):
    service = _service(
        fallback_models=("gemini-fallback-a",),
        max_retries_per_model=0,
        daily_quota_cooldown_seconds=100,
    )
    now = [1000.0]
    monkeypatch.setattr("backend.services.llm_service.time.monotonic", lambda: now[0])
    service.client.models.generate_content.side_effect = [
        _error(
            ClientError,
            429,
            details=[{"quotaId": "GenerateRequestsPerModelPerDay"}],
        ),
        _response(),
        _response(),
        _response(),
    ]

    first = service.generate("first")
    second = service.generate("second")
    now[0] += 101
    third = service.generate("third")

    assert first.model == "gemini-fallback-a"
    assert second.model == "gemini-fallback-a"
    assert third.model == "gemini-primary"


def test_explicit_project_quota_does_not_spend_quota_on_other_models():
    service = _service(max_retries_per_model=1)
    service.client.models.generate_content.side_effect = _error(
        ClientError,
        429,
        message="project-wide daily requests quota exhausted",
    )

    result = service.generate("same task")
    subsequent = service.generate("another task")

    assert result.error_code == "GEMINI_PROJECT_RATE_LIMITED"
    assert result.attempted_models == ("gemini-primary",)
    assert subsequent.error_code == "GEMINI_MODELS_COOLDOWN"
    assert service.client.models.generate_content.call_count == 1


def test_fallback_disabled_uses_only_primary_model():
    service = _service(max_retries_per_model=0)
    service.fallback_enabled = False
    service.client.models.generate_content.side_effect = _error(ServerError, 503)

    result = service.generate("same task")

    assert result.success is False
    assert result.attempted_models == ("gemini-primary",)
    assert service.client.models.generate_content.call_count == 1


def test_connectivity_reports_only_the_model_that_succeeded():
    service = _service(max_retries_per_model=0)
    service.client.models.generate_content.side_effect = [
        _error(ServerError, 503),
        _response("pong"),
    ]

    status = service.test_connectivity()

    assert status["success"] is True
    assert status["model"] == "gemini-fallback-a"
    assert status["attempted_models"] == (
        "gemini-primary",
        "gemini-fallback-a",
    )


def test_client_disables_sdk_retries_so_fallback_attempts_are_bounded():
    service = _service()
    with patch("backend.services.llm_service.genai.Client") as client_factory:
        service._client = None
        _ = service.client

    retry_options = client_factory.call_args.kwargs["http_options"].retry_options
    assert retry_options.attempts == 1


def test_newer_model_sampling_parameters_are_omitted():
    assert _supports_sampling_parameters("gemini-3.1-flash-lite") is True
    assert _supports_sampling_parameters("gemini-3.5-flash-lite") is False
    assert _supports_sampling_parameters("gemini-4-hydrogen") is False


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (401, "GEMINI_AUTHENTICATION_FAILED"),
        (403, "GEMINI_AUTHENTICATION_FAILED"),
        (404, "GEMINI_MODEL_UNAVAILABLE"),
        (429, "GEMINI_RATE_LIMITED"),
        (503, "GEMINI_PROVIDER_UNAVAILABLE"),
    ],
)
def test_gemini_provider_errors_are_classified_without_details(status, expected_code):
    error_type = ServerError if status >= 500 else ClientError
    error = _error(error_type, status, message="sensitive provider response")

    failure = _classify_api_error(error)
    message = gemini_error_message(failure.error_code, failure.provider_status)

    assert failure.error_code == expected_code
    assert failure.provider_status == status
    assert "sensitive provider response" not in message
