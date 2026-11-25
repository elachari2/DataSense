# Gemini model fallback

## Integration point

`GeminiLLMService.generate()` is the only application path that calls
`google-genai`'s `models.generate_content()`. Intent classification,
NL2SQL generation, answer synthesis, and the Streamlit connectivity check all
use that service. The same prompt, system instruction, output token limit, and
response MIME type are used for each model candidate.

The shared Gemini client is reused; each request selects a model through its
`model` argument. SDK-level retries are disabled so that the service can bound
retry counts and decide when to switch models.

## Model configuration

Configure the ordered chain in `.env`:

```ini
GEMINI_PRIMARY_MODEL=gemini-3.1-flash-lite
GEMINI_FALLBACK_MODELS=gemini-3.5-flash-lite,gemini-3.6-flash
GEMINI_FALLBACK_ENABLED=true
GEMINI_MAX_RETRIES_PER_MODEL=1
GEMINI_MODEL_COOLDOWN_SECONDS=60
GEMINI_DAILY_QUOTA_COOLDOWN_SECONDS=86400
GEMINI_MAX_RETRY_DELAY_SECONDS=2
LLM_TIMEOUT_SECONDS=30
```

The existing `LLM_MODEL` variable remains a compatibility alias when
`GEMINI_PRIMARY_MODEL` is not set. `GEMINI_FALLBACK_MODELS` is a comma-separated
ordered list; duplicates and the primary model are ignored. Set the list empty
or set `GEMINI_FALLBACK_ENABLED=false` to use only the primary model.
If `GEMINI_MAX_RETRIES_PER_MODEL` is unset, the older `LLM_MAX_RETRIES`
variable is honored; retry counts are restricted to 0 through 3.

The repository example uses `gemini-3.5-flash-lite` and `gemini-3.6-flash` as
candidates because the current Google model catalog lists both as stable
text-output models with structured-output support. The generic
[GenerateContent API](https://ai.google.dev/api/generate-content) is used by
the existing client. The
[model reference](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite)
and [Gemini 3.6 Flash reference](https://aistudio.google.com/docs/models/gemini-3.6-flash),
along with Google's [structured-output guide](https://aistudio.google.com/docs/structured-output),
document those capabilities. This does **not** prove either model is enabled
for a particular AI Studio project or has available quota. Confirm project
access in Google AI Studio before relying on these candidates.

The candidates may have different pricing and quota policies. Review Google's
current pricing and the project's quota before enabling live failover; an
automatic switch can cause billable requests.

Gemini 3.5 and newer models deprecate sampling parameters in their current
guidance. The service omits `temperature` for those model generations while
preserving the prompt and required output format.

## Retry and fallback policy

- HTTP 500, 502, 503, 504 and timeouts are retried at most
  `GEMINI_MAX_RETRIES_PER_MODEL` times per model, then the next configured
  candidate is tried.
- A short RPM/TPM 429 is retried only when Google provides a retry delay within
  `GEMINI_MAX_RETRY_DELAY_SECONDS`. Daily quota errors are not retried on the
  same model. Clearly project-scoped quota exhaustion stops the chain; a
  model-scoped or unscoped limit may try the next candidate once.
- A 404 model-unavailable response and a specifically identified model response
  format incompatibility can move to the next model. Arbitrary 400 errors,
  authentication errors (401/403), and other non-retryable errors stop the
  chain.
- Empty or invalid JSON responses can move to the next candidate. Each JSON
  response must be an object; service-specific fields are still validated by
  the existing NL2SQL and question-orchestration code.
- The SDK itself is configured for one HTTP attempt. This prevents its default
  internal retries from multiplying the explicitly bounded fallback attempts.

Fallback is not a quota bypass. Google quotas may be shared at project level,
and trying another model does not guarantee extra capacity. The service logs
the model, safe error category, provider status, attempt count, fallback
decision, and successful model. It never logs API keys, prompts, SQL results,
or customer review text.

Each process keeps an in-memory circuit breaker. After two consecutive eligible
transient failures, a model is skipped for
`GEMINI_MODEL_COOLDOWN_SECONDS`. A detected daily quota limit immediately
quarantines that model for `GEMINI_DAILY_QUOTA_COOLDOWN_SECONDS`. Success resets
the model's failure state; cooldowns expire and are not persisted across
application restarts. This is a local health signal, not Google's quota state.
A clearly project-scoped 429 pauses every configured model for the applicable
local cooldown instead of spending more requests on the same project limit.

Fallback repeats the same request context to another configured Google model.
If organizational policy does not allow sending the same data to that model,
disable fallback.

The Streamlit sidebar labels the configured primary model. Its **Tester Gemini**
button displays the model that actually succeeded for that health-check request;
it does not claim a model succeeded when all candidates failed.

## Tests and optional live check

Run mocked tests without consuming Gemini quota:

```powershell
python -m pytest -q tests/test_llm_service.py tests/test_settings.py tests/test_nl2sql_service.py tests/test_question_orchestrator.py tests/test_app.py
```

To make an opt-in live connectivity check after setting a valid key locally,
start from the repository root and run:

```powershell
@'
from backend.services.llm_service import get_llm_service
result = get_llm_service().test_connectivity()
print({
    "success": result["success"],
    "model": result["model"],
    "error_code": result["error_code"],
    "provider_status": result["provider_status"],
    "attempt_count": result["attempt_count"],
})
'@ | python -
```

This sends a small `ping` request and may try multiple configured models, so it
can consume quota. Do not paste the key into a command, chat, logs, or source
control. A successful mocked test does not establish live model availability.
