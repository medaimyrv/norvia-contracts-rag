"""Configuración común de los tests."""

import os

# LiteLLM ejecuta load_dotenv() al importarse salvo en modo PRODUCTION: cargaría el .env del
# desarrollador (con su clave) en os.environ. Los tests no deben depender de claves locales [Q1].
os.environ["LITELLM_MODE"] = "PRODUCTION"
os.environ.pop("GEMINI_API_KEY", None)
