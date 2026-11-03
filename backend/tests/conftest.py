"""Configuración común de los tests."""

import os

# LiteLLM ejecuta load_dotenv() al importarse salvo en modo PRODUCTION: cargaría el .env del
# desarrollador (con su clave) en os.environ. Los tests no deben depender de claves locales [Q1].
os.environ["LITELLM_MODE"] = "PRODUCTION"
os.environ.pop("GEMINI_API_KEY", None)
# Importar la app (p. ej. la tarea Celery) lee Settings; ningún test se conecta a esta URL:
# los de integración usan la del contenedor de testcontainers
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/unused")


# Trazas en memoria para poder comprobar spans y atributos [Q2]
import pytest  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

_EXPORTER = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
trace.set_tracer_provider(_provider)


@pytest.fixture
def spans() -> InMemorySpanExporter:
    _EXPORTER.clear()
    return _EXPORTER
