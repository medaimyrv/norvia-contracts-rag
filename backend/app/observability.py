"""OpenTelemetry: trazas de ingesta y de chat [Q2, D10, D13].

- Consola (por defecto): un span por línea en JSON, en los logs del contenedor.
- OTLP (OTEL_EXPORTER=otlp): a Jaeger con `docker compose --profile observability up`.
Contenido de preguntas y respuestas solo con OTEL_CAPTURE_CONTENT=true [S4].
"""

import hashlib

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.settings import Settings

tracer = trace.get_tracer("norvia")
_configured = False


def setup_tracing(settings: Settings, component: str) -> None:
    """Idempotente. `component`: api | worker (aparece como service.name)."""
    global _configured
    if _configured:
        return
    _configured = True
    resource = Resource.create({"service.name": f"{settings.otel_service_name}-{component}"})
    provider = TracerProvider(resource=resource)
    if settings.otel_exporter == "otlp":
        exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
    else:
        exporter = ConsoleSpanExporter(formatter=lambda span: span.to_json(indent=None) + "\n")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    # Sin instrumentación genérica de SQLAlchemy: la oficial solo admite < 2.1 y forzarla rompe el
    # arranque (importa sqlalchemy.ext.asyncio, que exige greenlet). La consulta que importa, la
    # búsqueda vectorial, tiene su span manual pgvector.search (adapters/db/retriever.py).
    CeleryInstrumentor().instrument()  # propaga el contexto API -> tarea en las cabeceras


def text_attributes(prefix: str, text: str, capture: bool) -> dict[str, object]:
    """Por defecto solo longitud y huella: permite correlacionar sin guardar el contenido."""
    attrs: dict[str, object] = {
        f"{prefix}.length": len(text),
        f"{prefix}.sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
    }
    if capture:
        attrs[f"{prefix}.text"] = text
    return attrs


def current_span_ids() -> tuple[str | None, str | None]:
    """(trace_id, span_id) del span actual en hexadecimal, o (None, None) sin trazas."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None, None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


def link_to(trace_id: str | None, span_id: str | None) -> trace.Link | None:
    """Enlace a otra traza (p. ej. la ingesta del documento citado) [D10]."""
    if not trace_id or not span_id:
        return None
    context = trace.SpanContext(
        int(trace_id, 16), int(span_id, 16), is_remote=True, trace_flags=trace.TraceFlags(1)
    )
    return trace.Link(context)
