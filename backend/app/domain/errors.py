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
