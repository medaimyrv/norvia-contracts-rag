"""Elige los proveedores según MODEL_PROVIDER y valida la configuración al arrancar [D6]."""

from dataclasses import dataclass

from app.adapters.db.tables import EMBEDDING_DIM
from app.adapters.fake_providers import FakeEmbedder, FakeLLM
from app.adapters.litellm_providers import LiteLLMChat, LiteLLMEmbedder
from app.domain.errors import ConfigurationError
from app.ports.embedder import Embedder
from app.ports.llm import LLM
from app.settings import Settings


@dataclass(frozen=True)
class Providers:
    embedder: Embedder
    llm: LLM
    is_fake: bool  # la web muestra el aviso «Modo demostración» [D15]


def build_providers(settings: Settings) -> Providers:
    if settings.embedding_dim != EMBEDDING_DIM:
        # Fallar al arrancar con un mensaje claro, no en la primera inserción con un error SQL
        raise ConfigurationError(
            f"EMBEDDING_DIM={settings.embedding_dim} no coincide con el esquema "
            f"({EMBEDDING_DIM}); cambiarlo exige una migración nueva y reingesta"
        )
    if settings.model_provider == "fake":
        return Providers(FakeEmbedder(settings.embedding_dim), FakeLLM(), is_fake=True)

    if settings.gemini_api_key is None:  # Settings ya lo impide; se comprueba por tipado
        raise ConfigurationError("MODEL_PROVIDER=gemini requiere GEMINI_API_KEY")
    key = settings.gemini_api_key.get_secret_value()
    return Providers(
        embedder=LiteLLMEmbedder(
            settings.embedding_model, settings.embedding_dim, key, settings.llm_timeout_s
        ),
        llm=LiteLLMChat(settings.llm_model, key, settings.llm_timeout_s),
        is_fake=False,
    )
