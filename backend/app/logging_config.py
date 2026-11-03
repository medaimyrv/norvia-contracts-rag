"""Logs JSON de una línea, correlacionados con la traza activa [S4, Q2].

Regla del proyecto: nunca se registra el texto de preguntas, respuestas ni fragmentos;
solo identificadores, contadores y códigos.
"""

import json
import logging
from datetime import UTC, datetime

from opentelemetry import trace

# Atributos estándar de LogRecord: lo que no esté aquí son los «extra» del mensaje
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            # Con el trace_id se salta del log a la traza en Jaeger
            entry["trace_id"] = format(context.trace_id, "032x")
            entry["span_id"] = format(context.span_id, "016x")
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # LiteLLM registra prompts y respuestas en DEBUG: nunca por debajo de WARNING [S4]
    for noisy in ("LiteLLM", "litellm", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
