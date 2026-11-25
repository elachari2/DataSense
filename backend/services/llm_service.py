"""
DataSense - Google Gemini LLM Service.
Handles client initialization, prompt dispatch, error handling, rate-limiting, and retries.
"""

import logging
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any

from google import genai
from google.genai import types
from google.genai.errors import APIError

from backend.config.settings import get_settings, Settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    text: str
    model: Optional[str]
    success: bool
    error: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    duration_seconds: float = 0.0
    error_code: Optional[str] = None
    provider_status: Optional[int] = None
    attempted_models: tuple[str, ...] = ()
    attempt_count: int = 0


@dataclass(frozen=True)
class _ProviderFailure:
    error_code: str
    provider_status: Optional[int]
    eligible_for_fallback: bool = False
    stop_all: bool = True
    retry_after_seconds: Optional[float] = None
    quota_period: Optional[str] = None
    quota_scope: Optional[str] = None


@dataclass
class _ModelHealth:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0


def _nested_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(
            f"{key} {_nested_text(item)}" for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return " ".join(_nested_text(item) for item in value)
    return str(value) if value is not None else ""


def _retry_delay_from_details(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().replace("_", "") in {"retrydelay"}:
                if isinstance(item, dict):
                    try:
                        seconds = float(item.get("seconds", 0) or 0)
                        nanos = float(item.get("nanos", 0) or 0)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    delay = seconds + nanos / 1_000_000_000
                    if math.isfinite(delay):
                        return max(0.0, delay)
                match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(item))
                if match:
                    return float(match.group(1))
            found = _retry_delay_from_details(item)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _retry_delay_from_details(item)
            if found is not None:
                return found
    return None


def _retry_after_seconds(error: Exception) -> Optional[float]:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    try:
        retry_after = headers.get("retry-after") if headers is not None else None
    except (AttributeError, TypeError):
        retry_after = None
    if retry_after is not None and str(retry_after).strip():
        try:
            delay = float(retry_after)
            if math.isfinite(delay):
                return max(0.0, delay)
        except (TypeError, ValueError):
            try:
                retry_time = parsedate_to_datetime(str(retry_after))
                if retry_time.tzinfo is None:
                    retry_time = retry_time.replace(tzinfo=timezone.utc)
                delay = (retry_time - datetime.now(timezone.utc)).total_seconds()
                if math.isfinite(delay):
                    return max(0.0, delay)
            except (TypeError, ValueError, OverflowError):
                pass
    return _retry_delay_from_details(getattr(error, "details", None))


def _quota_period(error_text: str) -> Optional[str]:
    with_word_boundaries = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])",
        " ",
        error_text,
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", with_word_boundaries.lower())
    if re.search(r"\b(daily|rpd|per day|per 24 hours?|requests per day)\b", normalized):
        return "daily"
    if re.search(r"\b(rpm|requests per minute)\b", normalized):
        return "rpm"
    if re.search(r"\b(tpm|tokens per minute)\b", normalized):
        return "tpm"
    if re.search(r"\bper minute\b", normalized):
        return "short"
    return None


def _quota_scope(error_text: str) -> Optional[str]:
    with_word_boundaries = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])",
        " ",
        error_text,
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", with_word_boundaries.lower())
    if re.search(r"\b(project wide|project level|per project|project quota)\b", normalized):
        return "project"
    if re.search(r"\b(model specific|per model|model quota)\b", normalized):
        return "model"
    return None


def _is_model_specific_compatibility_error(error_text: str) -> bool:
    normalized = error_text.lower().replace("_", "").replace("-", "")
    unsupported = any(
        phrase in normalized
        for phrase in (
            "not supported",
            "does not support",
            "doesn't support",
            "unsupported",
        )
    )
    model_feature = "model" in normalized and any(
        marker in normalized
        for marker in ("responsemimetype", "structured output", "json mode")
    )
    return unsupported and model_feature


def _classify_api_error(error: APIError) -> _ProviderFailure:
    raw_status = getattr(error, "code", None)
    try:
        status = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status = None

    error_text = " ".join(
        (
            str(getattr(error, "status", "") or ""),
            str(getattr(error, "message", "") or ""),
            _nested_text(getattr(error, "details", None)),
        )
    )

    if status in {401, 403}:
        return _ProviderFailure("GEMINI_AUTHENTICATION_FAILED", status)
    if status == 400:
        if _is_model_specific_compatibility_error(error_text):
            return _ProviderFailure(
                "GEMINI_MODEL_INCOMPATIBLE",
                status,
                eligible_for_fallback=True,
                stop_all=False,
            )
        return _ProviderFailure("GEMINI_API_ERROR", status)
    if status == 404:
        return _ProviderFailure(
            "GEMINI_MODEL_UNAVAILABLE",
            status,
            eligible_for_fallback=True,
            stop_all=False,
        )
    if status == 429:
        scope = _quota_scope(error_text)
        if scope == "project":
            return _ProviderFailure(
                "GEMINI_PROJECT_RATE_LIMITED",
                status,
                quota_period=_quota_period(error_text),
                quota_scope=scope,
            )
        return _ProviderFailure(
            "GEMINI_RATE_LIMITED",
            status,
            eligible_for_fallback=True,
            stop_all=scope == "project",
            retry_after_seconds=_retry_after_seconds(error),
            quota_period=_quota_period(error_text),
            quota_scope=scope,
        )
    if status == 408:
        return _ProviderFailure(
            "GEMINI_TIMEOUT",
            status,
            eligible_for_fallback=True,
            stop_all=False,
            retry_after_seconds=_retry_after_seconds(error),
        )
    if status in {500, 502, 503, 504}:
        return _ProviderFailure(
            "GEMINI_PROVIDER_UNAVAILABLE",
            status,
            eligible_for_fallback=True,
            stop_all=False,
            retry_after_seconds=_retry_after_seconds(error),
        )
    if status is not None and status >= 400:
        return _ProviderFailure("GEMINI_API_ERROR", status)
    return _ProviderFailure("GEMINI_REQUEST_ERROR", status)


def _supports_sampling_parameters(model: str) -> bool:
    match = re.match(r"^gemini-(\d+)(?:\.(\d+))?", model.lower())
    if not match:
        return True
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    return major < 4 and not (major == 3 and minor >= 5)


def _valid_response(text: str, response_mime_type: Optional[str]) -> bool:
    if not text.strip():
        return False
    if response_mime_type != "application/json":
        return True
    try:
        return isinstance(json.loads(text), dict)
    except (TypeError, json.JSONDecodeError):
        return False


def _is_timeout_exception(error: Exception) -> bool:
    if isinstance(error, TimeoutError):
        return True
    return any(
        "timeout" in parent.__name__.lower()
        and parent.__module__.startswith(
            ("httpx", "httpx2", "httpcore", "requests")
        )
        for parent in type(error).__mro__
    )


def gemini_error_message(
    error_code: Optional[str],
    provider_status: Optional[int] = None,
) -> str:
    status_text = f"HTTP {provider_status}" if provider_status else "erreur fournisseur"
    messages = {
        "GEMINI_API_KEY_MISSING": (
            "La clé API Gemini n'est pas configurée. Vérifiez la variable "
            "LLM_API_KEY sans afficher sa valeur."
        ),
        "GEMINI_AUTHENTICATION_FAILED": (
            f"Gemini a refusé l'authentification ({status_text}). Vérifiez "
            "la configuration et les droits de la clé."
        ),
        "GEMINI_MODEL_UNAVAILABLE": (
            f"Le modèle Gemini configuré n'est pas disponible ({status_text}). "
            "Vérifiez GEMINI_PRIMARY_MODEL et l'accès au modèle."
        ),
        "GEMINI_MODEL_INCOMPATIBLE": (
            "Le modèle Gemini ne prend pas en charge un format requis par cette requête. "
            "Vérifiez la compatibilité des modèles configurés."
        ),
        "GEMINI_RATE_LIMITED": (
            f"Gemini a limité les requêtes ({status_text}). Un autre modèle peut "
            "avoir des quotas différents, sans garantie de capacité supplémentaire."
        ),
        "GEMINI_PROJECT_RATE_LIMITED": (
            f"Le quota Gemini du projet est atteint ({status_text}). Changer de "
            "modèle ne garantit pas de capacité supplémentaire; vérifiez les quotas."
        ),
        "GEMINI_PROVIDER_UNAVAILABLE": (
            f"Gemini est indisponible côté fournisseur ({status_text}). "
            "Les modèles configurés ont été essayés; réessayez plus tard."
        ),
        "GEMINI_TIMEOUT": (
            "Le délai d'attente de Gemini est dépassé. Les modèles configurés "
            "n'ont pas répondu à temps."
        ),
        "GEMINI_INVALID_RESPONSE": (
            "Les modèles Gemini configurés n'ont pas fourni de réponse au format attendu."
        ),
        "GEMINI_MODELS_COOLDOWN": (
            "Les modèles Gemini configurés sont temporairement en pause après "
            "des erreurs récentes. Réessayez après leur période de récupération."
        ),
        "GEMINI_API_ERROR": (
            f"Gemini a refusé la requête ({status_text}). Vérifiez la configuration."
        ),
    }
    return messages.get(
        error_code or "",
        "La requête Gemini n'a pas abouti. Vérifiez la connexion au service.",
    )


class LLMServiceError(RuntimeError):
    """Safe, structured failure returned by the Gemini service."""

    def __init__(self, error_code: str, provider_status: Optional[int] = None):
        self.error_code = error_code
        self.provider_status = provider_status
        super().__init__(gemini_error_message(error_code, provider_status))


class GeminiLLMService:
    """Service wrapping Google GenAI SDK for Gemini models."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.llm.api_key
        self.model = self.settings.llm.model
        self.fallback_models = tuple(
            model
            for model in self.settings.llm.fallback_models
            if model and model != self.model
        )
        self.fallback_enabled = self.settings.llm.fallback_enabled
        self.temperature = self.settings.llm.temperature
        self.max_output_tokens = self.settings.llm.max_output_tokens
        self.max_retries_per_model = self.settings.llm.max_retries_per_model
        self.model_cooldown_seconds = self.settings.llm.model_cooldown_seconds
        self.daily_quota_cooldown_seconds = (
            self.settings.llm.daily_quota_cooldown_seconds
        )
        self.max_retry_delay_seconds = self.settings.llm.max_retry_delay_seconds
        self._client: Optional[genai.Client] = None
        self._model_health: dict[str, _ModelHealth] = {}
        self._health_lock = threading.Lock()

        if not self.api_key:
            logger.warning("GeminiLLMService initialized without an API key.")

    @property
    def client(self) -> genai.Client:
        """Lazily instantiates the Gemini Client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("LLM_API_KEY is not configured in the environment.")
            timeout_ms = self.settings.llm.request_timeout_seconds * 1000
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    timeout=timeout_ms,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._client

    def test_connectivity(self) -> Dict[str, Any]:
        """Check connectivity through the same bounded model-selection path."""
        response = self.generate(
            prompt="ping",
            temperature=0.0,
            max_output_tokens=5,
        )
        return {
            "success": response.success,
            "model": response.model if response.success else None,
            "duration_seconds": round(response.duration_seconds, 3),
            "error_code": response.error_code,
            "provider_status": response.provider_status,
            "error": response.error,
            "attempted_models": response.attempted_models,
            "attempt_count": response.attempt_count,
        }

    def _candidate_models(self) -> tuple[str, ...]:
        candidates = [self.model]
        if self.fallback_enabled:
            candidates.extend(self.fallback_models)
        return tuple(dict.fromkeys(model for model in candidates if model))

    def _is_cooling_down(self, model: str) -> bool:
        now = time.monotonic()
        with self._health_lock:
            health = self._model_health.get(model)
            if health is None:
                return False
            if health.cooldown_until and health.cooldown_until <= now:
                health.cooldown_until = 0.0
                health.consecutive_failures = 0
            return health.cooldown_until > now

    def _record_failure(
        self,
        model: str,
        cooldown_seconds: int = 0,
    ) -> int:
        with self._health_lock:
            health = self._model_health.setdefault(model, _ModelHealth())
            health.consecutive_failures += 1
            if cooldown_seconds or health.consecutive_failures >= 2:
                duration = cooldown_seconds or self.model_cooldown_seconds
                health.cooldown_until = max(
                    health.cooldown_until,
                    time.monotonic() + duration,
                )
            return health.consecutive_failures

    def _record_success(self, model: str) -> None:
        with self._health_lock:
            self._model_health[model] = _ModelHealth()

    def _make_config(
        self,
        model: str,
        temperature: Optional[float],
        max_output_tokens: Optional[int],
        system_instruction: Optional[str],
        response_mime_type: Optional[str],
    ) -> types.GenerateContentConfig:
        config_kwargs: Dict[str, Any] = {
            "max_output_tokens": (
                max_output_tokens
                if max_output_tokens is not None
                else self.max_output_tokens
            ),
        }
        selected_temperature = (
            temperature if temperature is not None else self.temperature
        )
        if _supports_sampling_parameters(model):
            config_kwargs["temperature"] = selected_temperature
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        return types.GenerateContentConfig(**config_kwargs)

    def _retry_delay(
        self,
        failure: _ProviderFailure,
        retry_index: int,
    ) -> Optional[float]:
        if failure.error_code == "GEMINI_RATE_LIMITED":
            if failure.quota_period not in {"short", "rpm", "tpm"}:
                return None
            delay = failure.retry_after_seconds
            if delay is None:
                return None
        elif failure.retry_after_seconds is not None:
            delay = failure.retry_after_seconds
        else:
            delay = min(0.5 * (2**retry_index), self.max_retry_delay_seconds)

        if delay > self.max_retry_delay_seconds:
            return None
        return max(0.0, delay)

    def _failure_response(
        self,
        error_code: str,
        provider_status: Optional[int],
        attempted_models: list[str],
        attempt_count: int,
        start_time: float,
    ) -> LLMResponse:
        logger.error(
            "Gemini model attempts exhausted: category=%s provider_status=%s "
            "attempted_model_count=%s attempt_count=%s",
            error_code,
            provider_status,
            len(attempted_models),
            attempt_count,
        )
        return LLMResponse(
            text="",
            model=None,
            success=False,
            error=gemini_error_message(error_code, provider_status),
            duration_seconds=time.perf_counter() - start_time,
            error_code=error_code,
            provider_status=provider_status,
            attempted_models=tuple(attempted_models),
            attempt_count=attempt_count,
        )

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        response_mime_type: Optional[str] = None
    ) -> LLMResponse:
        """Generate content with bounded per-model retries and ordered failover."""
        if not self.api_key:
            return LLMResponse(
                text="",
                model=None,
                success=False,
                error=gemini_error_message("GEMINI_API_KEY_MISSING"),
                error_code="GEMINI_API_KEY_MISSING",
            )

        start_time = time.perf_counter()
        attempted_models: list[str] = []
        attempt_count = 0
        last_failure: Optional[_ProviderFailure] = None
        candidates = self._candidate_models()

        for model in candidates:
            if self._is_cooling_down(model):
                logger.info("Gemini model skipped during cooldown: model=%s", model)
                continue

            if attempted_models or model != self.model:
                logger.warning(
                    "Gemini fallback selected: from_model=%s to_model=%s "
                    "reason=%s attempts=%s",
                    attempted_models[-1] if attempted_models else self.model,
                    model,
                    last_failure.error_code if last_failure else "MODEL_COOLDOWN",
                    attempt_count,
                )
            attempted_models.append(model)
            logger.info("Gemini request model selected: model=%s", model)

            for retry_index in range(self.max_retries_per_model + 1):
                attempt_count += 1
                logger.info(
                    "Gemini request started: model=%s attempt=%s",
                    model,
                    attempt_count,
                )
                try:
                    response = self.client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=self._make_config(
                            model,
                            temperature,
                            max_output_tokens,
                            system_instruction,
                            response_mime_type,
                        ),
                    )
                    text_content = response.text or ""
                    if not _valid_response(text_content, response_mime_type):
                        last_failure = _ProviderFailure(
                            "GEMINI_INVALID_RESPONSE",
                            None,
                            eligible_for_fallback=True,
                            stop_all=False,
                        )
                        self._record_failure(model)
                        logger.warning(
                            "Gemini response rejected: category=%s model=%s",
                            last_failure.error_code,
                            model,
                        )
                        break

                    self._record_success(model)
                    finish_reason = None
                    if response.candidates:
                        finish_reason = getattr(
                            response.candidates[0], "finish_reason", None
                        )
                    duration = time.perf_counter() - start_time
                    logger.info(
                        "Gemini request succeeded: model=%s attempted_models=%s "
                        "attempt_count=%s",
                        model,
                        len(attempted_models),
                        attempt_count,
                    )
                    return LLMResponse(
                        text=text_content,
                        model=model,
                        success=True,
                        finish_reason=(
                            str(finish_reason) if finish_reason else None
                        ),
                        duration_seconds=duration,
                        attempted_models=tuple(attempted_models),
                        attempt_count=attempt_count,
                    )
                except APIError as error:
                    last_failure = _classify_api_error(error)
                    logger.warning(
                        "Gemini request failed: category=%s provider_status=%s "
                        "quota_period=%s quota_scope=%s model=%s attempt=%s",
                        last_failure.error_code,
                        last_failure.provider_status,
                        last_failure.quota_period,
                        last_failure.quota_scope,
                        model,
                        attempt_count,
                    )
                    if last_failure.error_code == "GEMINI_PROJECT_RATE_LIMITED":
                        project_cooldown = (
                            self.daily_quota_cooldown_seconds
                            if last_failure.quota_period == "daily"
                            else self.model_cooldown_seconds
                        )
                        for candidate in candidates:
                            self._record_failure(
                                candidate,
                                cooldown_seconds=project_cooldown,
                            )
                    if (
                        last_failure.stop_all
                        or not last_failure.eligible_for_fallback
                    ):
                        return self._failure_response(
                            last_failure.error_code,
                            last_failure.provider_status,
                            attempted_models,
                            attempt_count,
                            start_time,
                        )
                    cooldown = 0
                    if last_failure.quota_period == "daily":
                        cooldown = self.daily_quota_cooldown_seconds
                    elif last_failure.error_code in {
                        "GEMINI_RATE_LIMITED",
                        "GEMINI_MODEL_UNAVAILABLE",
                        "GEMINI_MODEL_INCOMPATIBLE",
                    }:
                        cooldown = self.model_cooldown_seconds
                    self._record_failure(model, cooldown_seconds=cooldown)
                    delay = (
                        self._retry_delay(last_failure, retry_index)
                        if retry_index < self.max_retries_per_model
                        else None
                    )
                    if delay is not None:
                        logger.info(
                            "Gemini retry scheduled: model=%s delay_seconds=%.2f "
                            "category=%s",
                            model,
                            delay,
                            last_failure.error_code,
                        )
                        time.sleep(delay)
                        continue
                    break
                except Exception as error:
                    if not _is_timeout_exception(error):
                        logger.warning(
                            "Gemini request failed: category=GEMINI_REQUEST_ERROR "
                            "exception=%s model=%s attempt=%s",
                            type(error).__name__,
                            model,
                            attempt_count,
                        )
                        return self._failure_response(
                            "GEMINI_REQUEST_ERROR",
                            None,
                            attempted_models,
                            attempt_count,
                            start_time,
                        )

                    last_failure = _ProviderFailure(
                        "GEMINI_TIMEOUT",
                        None,
                        eligible_for_fallback=True,
                        stop_all=False,
                    )
                    logger.warning(
                        "Gemini request timed out: model=%s attempt=%s",
                        model,
                        attempt_count,
                    )
                    self._record_failure(model)
                    if retry_index < self.max_retries_per_model:
                        delay = min(
                            0.5 * (2**retry_index),
                            self.max_retry_delay_seconds,
                        )
                        logger.info(
                            "Gemini retry scheduled: model=%s delay_seconds=%.2f "
                            "category=%s",
                            model,
                            delay,
                            last_failure.error_code,
                        )
                        time.sleep(delay)
                        continue
                    break

        if last_failure is None:
            last_failure = _ProviderFailure(
                "GEMINI_MODELS_COOLDOWN",
                None,
            )
        return self._failure_response(
            last_failure.error_code,
            last_failure.provider_status,
            attempted_models,
            attempt_count,
            start_time,
        )


_llm_service_instance: Optional[GeminiLLMService] = None


def get_llm_service() -> GeminiLLMService:
    """Returns singleton GeminiLLMService instance."""
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = GeminiLLMService()
    return _llm_service_instance
