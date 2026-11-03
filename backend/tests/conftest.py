"""Configuración común de los tests."""

import os

# LiteLLM ejecuta load_dotenv() al importarse salvo en modo PRODUCTION: cargaría el .env del
# desarrollador (con su clave) en os.environ. Los tests no deben depender de claves locales [Q1].
os.environ["LITELLM_MODE"] = "PRODUCTION"
os.environ.pop("GEMINI_API_KEY", None)
# Importar la app (p. ej. la tarea Celery) lee Settings; ningún test se conecta a esta URL:
# los de integración usan la del contenedor de testcontainers
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/unused")
