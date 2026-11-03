"""Proveedores reales vía LiteLLM (Gemini) [R10, D6].

Traducen las excepciones de LiteLLM a errores de dominio: el resto del código no conoce LiteLLM.
"""

from collections.abc import AsyncIterator

import litellm

from app.domain.errors import (
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.domain.llm import LLMEvent, LLMRequest, TextDelta, Usage

# Errores en los que reintentar tiene sentido (la red o el proveedor, no nuestra petición)
_TRANSIENT = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
)
# Errores de configuración (clave, modelo, petición): reintentar no los arregla
_CONFIG = (litellm.AuthenticationError, litellm.NotFoundError, litellm.BadRequestError)


class LiteLLMEmbedder:
    def __init__(
        self, model: str, dim: int, api_key: str, timeout_s: float, batch_size: int = 100
    ) -> None:
        self.model = model
        self.dim = dim
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            try:
                response = litellm.embedding(
                    model=self.model,
                    input=batch,
                    dimensions=self.dim,
                    api_key=self._api_key,
                    timeout=self._timeout_s,
                )
            except _TRANSIENT as exc:
                raise EmbeddingProviderError(type(exc).__name__) from exc
            except _CONFIG as exc:
                raise EmbeddingConfigurationError(type(exc).__name__) from exc
            vectors += [_vector(item) for item in response.data]
        if any(len(v) != self.dim for v in vectors):
            raise EmbeddingProviderError(f"el modelo no devolvió vectores de {self.dim} dim")
        return vectors


def _vector(item: object) -> list[float]:
    return item["embedding"] if isinstance(item, dict) else item.embedding  # type: ignore[attr-defined]


class LiteLLMChat:
    def __init__(self, model: str, api_key: str, timeout_s: float) -> None:
        self.model = model
        self._api_key = api_key
        self._timeout_s = timeout_s

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=[
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.user},
                ],
                stream=True,
                stream_options={"include_usage": True},
                temperature=0,  # respuestas lo más reproducibles posible
                api_key=self._api_key,
                timeout=self._timeout_s,
            )
            async for part in response:
                if part.choices and (text := part.choices[0].delta.content):
                    yield TextDelta(text)
                if usage := getattr(part, "usage", None):
                    yield Usage(usage.prompt_tokens or 0, usage.completion_tokens or 0)
        except litellm.Timeout as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except litellm.RateLimitError as exc:
            raise LLMRateLimitError(str(exc)) from exc
        except _TRANSIENT as exc:
            raise LLMUnavailableError(type(exc).__name__) from exc
        except _CONFIG as exc:
            raise LLMConfigurationError(type(exc).__name__) from exc
