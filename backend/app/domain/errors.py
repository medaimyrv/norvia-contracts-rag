"""Errores de ingesta con código estable (se guarda en documents.error_code) [R6, F1, F2].

permanent=True: reintentar no cambia el resultado (el archivo está mal). La tarea Celery
marca FAILED sin reintentar. permanent=False: fallo transitorio, se reintenta con backoff.
"""


class IngestionError(Exception):
    code: str = "ingestion_error"
    permanent: bool = False


class InvalidPdfError(IngestionError):
    code = "invalid_pdf"
    permanent = True


class NoTextLayerError(IngestionError):
    code = "no_text_layer"
    permanent = True


class FileMissingError(IngestionError):
    """El PDF no está en el almacenamiento (volumen perdido o borrado)."""

    code = "file_missing"
    permanent = True


class EmbeddingProviderError(IngestionError):
    """El proveedor de embeddings falló (timeout, rate limit, caída): se reintenta [R6, F4]."""

    code = "embedding_provider_error"


class EmbeddingConfigurationError(IngestionError):
    """Clave inválida o modelo inexistente: reintentar no lo arregla."""

    code = "embedding_misconfigured"
    permanent = True


# --- Chat: no son de ingesta; el endpoint SSE los convierte en un evento `error` [F3, F4] ---


class LLMError(Exception):
    code: str = "llm_error"


class LLMTimeoutError(LLMError):
    code = "llm_timeout"


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"


class LLMConfigurationError(LLMError):
    code = "llm_misconfigured"


class DocumentConflictError(Exception):
    """La subida choca con un documento existente [D5]. La API responde 409."""

    def __init__(self, code: str, message: str, existing_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.existing_id = existing_id


class ConfigurationError(Exception):
    """Configuración incoherente detectada al arrancar: el proceso no debe iniciarse."""
