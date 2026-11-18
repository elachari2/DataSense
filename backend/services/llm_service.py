"""
DataSense - Google Gemini LLM Service.
Handles client initialization, prompt dispatch, error handling, rate-limiting, and retries.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from backend.config.settings import get_settings, Settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    text: str
    model: str
    success: bool
    error: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    duration_seconds: float = 0.0


class GeminiLLMService:
    """Service wrapping Google GenAI SDK for Gemini models."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.llm.api_key
        self.model = self.settings.llm.model
        self.temperature = self.settings.llm.temperature
        self.max_output_tokens = self.settings.llm.max_output_tokens
        self.max_retries = self.settings.llm.max_retries
        self._client: Optional[genai.Client] = None

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
                http_options=types.HttpOptions(timeout=timeout_ms)
            )
        return self._client

    def test_connectivity(self) -> Dict[str, Any]:
        """Runs a lightweight health-check request to verify API credentials and model."""
        try:
            start = time.time()
            res = self.client.models.generate_content(
                model=self.model,
                contents="ping",
                config=types.GenerateContentConfig(
                    max_output_tokens=5,
                    temperature=0.0
                )
            )
            duration = time.time() - start
            return {
                "success": True,
                "model": self.model,
                "duration_seconds": round(duration, 3),
                "response": (res.text or "").strip()
            }
        except APIError as e:
            return {
                "success": False,
                "model": self.model,
                "error": f"Gemini API Error [{getattr(e, 'code', 'unknown')}]: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "model": self.model,
                "error": f"Unexpected error: {str(e)}"
            }

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        response_mime_type: Optional[str] = None
    ) -> LLMResponse:
        """
        Sends a prompt to Gemini with exponential backoff for transient errors.
        Never retries indefinitely on quota exhaustion (HTTP 429) or invalid requests (4xx).
        """
        if not self.api_key:
            return LLMResponse(
                text="",
                model=self.model,
                success=False,
                error="LLM_API_KEY is not configured."
            )

        temp = temperature if temperature is not None else self.temperature
        max_tokens = max_output_tokens if max_output_tokens is not None else self.max_output_tokens

        config_kwargs: Dict[str, Any] = {
            "temperature": temp,
            "max_output_tokens": max_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type

        config = types.GenerateContentConfig(**config_kwargs)

        last_error = ""
        backoff_delay = 1.0
        start_time = time.time()

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config
                )

                duration = time.time() - start_time
                text_content = response.text or ""

                finish_reason = None
                if response.candidates:
                    finish_reason = getattr(response.candidates[0], "finish_reason", None)

                return LLMResponse(
                    text=text_content,
                    model=self.model,
                    success=True,
                    finish_reason=str(finish_reason) if finish_reason else None,
                    duration_seconds=duration
                )

            except ClientError as e:
                # 4xx error (e.g. 400 Bad Request, 404 Model Not Found, 403 Forbidden)
                # Client errors should NOT be retried
                code = getattr(e, "code", 400)
                msg = str(e)
                if code == 429:
                    # Rate limit or quota exhaustion
                    return LLMResponse(
                        text="",
                        model=self.model,
                        success=False,
                        error=f"Gemini API Quota Exceeded (HTTP 429): {msg}",
                        duration_seconds=time.time() - start_time
                    )
                return LLMResponse(
                    text="",
                    model=self.model,
                    success=False,
                    error=f"Gemini Client Error (HTTP {code}): {msg}",
                    duration_seconds=time.time() - start_time
                )

            except ServerError as e:
                # 5xx error (e.g. 503 High Demand, 500 Internal Error)
                last_error = f"Gemini Server Error (HTTP {getattr(e, 'code', 500)}): {str(e)}"
                if attempt < self.max_retries:
                    time.sleep(backoff_delay)
                    backoff_delay *= 2.0
                else:
                    break

            except Exception as e:
                last_error = f"Unexpected Gemini error: {str(e)}"
                if attempt < self.max_retries:
                    time.sleep(backoff_delay)
                    backoff_delay *= 2.0
                else:
                    break

        return LLMResponse(
            text="",
            model=self.model,
            success=False,
            error=f"Max retries ({self.max_retries}) exceeded. Last error: {last_error}",
            duration_seconds=time.time() - start_time
        )


_llm_service_instance: Optional[GeminiLLMService] = None


def get_llm_service() -> GeminiLLMService:
    """Returns singleton GeminiLLMService instance."""
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = GeminiLLMService()
    return _llm_service_instance
