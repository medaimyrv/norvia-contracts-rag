"""Configuración desde variables de entorno [S2].

No usa modo estricto: las variables de entorno siempre son texto y hay que convertirlas
("768" -> 768). El modo estricto se aplica a los modelos de dominio y de la API.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Calibrados con eval/run_eval.py priorizando «no inventar» (ver eval/RESULTS.md)
CALIBRATED_THRESHOLDS: dict[str, float] = {
    "gemini": 0.69,  # regla «no inventar»: rechaza todas las preguntas sin respuesta del eval
    "fake": 0.25,  # demo permisiva: el FakeLLM es extractivo y no puede inventar [D15]
}


class Settings(BaseSettings):
    # env_ignore_empty: «VAR=» en .env o compose cuenta como no definida (usa el valor por defecto)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # SecretStr: no aparece en repr() ni en logs [S4]; se lee con .get_secret_value()
    database_url: SecretStr
    redis_url: str = "redis://localhost:6379/0"

    model_provider: Literal["fake", "gemini"] = "fake"
    gemini_api_key: SecretStr | None = None
    llm_model: str = "gemini/gemini-3.5-flash-lite"
    embedding_model: str = "gemini/gemini-embedding-001"
    embedding_dim: int = Field(default=768, gt=0)
    llm_timeout_s: float = Field(default=30, gt=0)

    retrieval_k: int = Field(default=6, ge=1, le=20)
    # None -> el valor calibrado para el proveedor activo (eval/RESULTS.md) [R11, D8]
    relevance_threshold: float | None = Field(default=None, ge=0, le=1)

    max_upload_mb: int = Field(default=20, gt=0)
    upload_dir: str = "/data/uploads"

    otel_service_name: str = "norvia-rag"
    otel_exporter: Literal["console", "otlp"] = "console"
    otel_exporter_otlp_endpoint: str = "http://jaeger:4318"
    otel_capture_content: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def _gemini_requires_key(self) -> Self:
        # Fallar al arrancar es mejor que fallar en la primera pregunta del usuario
        if self.model_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("MODEL_PROVIDER=gemini requiere GEMINI_API_KEY")
        return self

    @property
    def effective_relevance_threshold(self) -> float:
        """Las puntuaciones dependen del modelo de embeddings: cada proveedor tiene su umbral."""
        if self.relevance_threshold is not None:
            return self.relevance_threshold
        return CALIBRATED_THRESHOLDS[self.model_provider]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # los campos requeridos vienen del entorno
