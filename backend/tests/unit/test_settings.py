import pytest
from pydantic import ValidationError

from app.settings import Settings

DB_URL = "postgresql+psycopg://user:s3cr3t@localhost:5432/db"


def make(**overrides: object) -> Settings:
    # _env_file=None: el test no depende de un .env local
    return Settings(_env_file=None, database_url=DB_URL, **overrides)  # type: ignore[arg-type]


def test_defaults_run_without_keys() -> None:
    s = make()
    assert s.model_provider == "fake"
    assert s.gemini_api_key is None


def test_env_strings_are_converted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("EMBEDDING_DIM", "384")
    monkeypatch.setenv("RELEVANCE_THRESHOLD", "0.5")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.embedding_dim == 384
    assert s.relevance_threshold == 0.5


def test_gemini_without_key_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        make(model_provider="gemini")


@pytest.mark.parametrize(
    "field,value",
    [("relevance_threshold", 1.5), ("retrieval_k", 0), ("max_upload_mb", 0)],
)
def test_out_of_range_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_secrets_do_not_leak_in_repr() -> None:
    s = make(model_provider="gemini", gemini_api_key="AIza-very-secret")
    text = repr(s) + str(s.model_dump())
    assert "s3cr3t" not in text
    assert "AIza-very-secret" not in text
    assert s.database_url.get_secret_value() == DB_URL


def test_max_upload_bytes() -> None:
    assert make(max_upload_mb=2).max_upload_bytes == 2 * 1024 * 1024


def test_thresholds_are_per_provider_and_question_kind() -> None:
    assert make(model_provider="gemini", gemini_api_key="k").effective_relevance_thresholds == (
        0.70,
        0.63,
    )
    assert make(relevance_threshold=0.5).effective_relevance_thresholds == (0.5, 0.5)
