"""Búsqueda vectorial con filtros contra pgvector real [R8, D3, D14]."""

from datetime import date

import pytest
from sqlalchemy import Engine, delete

from app.adapters.db.retriever import PgVectorRetriever
from app.adapters.db.session import session_factory_for
from app.adapters.db.tables import Document
from app.adapters.fake_providers import FakeEmbedder
from app.adapters.local_storage import LocalFileStorage
from app.adapters.pdfplumber_extractor import PdfplumberExtractor
from app.domain.chunking import ClauseChunker
from app.domain.retrieval import SearchFilters
from app.services.ingestion import IngestionService
from tests.integration.helpers import register_sample

pytestmark = pytest.mark.integration
CONDOR = "Transportes Cóndor Andino"
RAPIDO = "Rápido Austral Logística"
QUESTION = "plazo de reclamación por mercancía dañada"


@pytest.fixture(scope="module")
def retriever(migrated_engine: Engine, tmp_path_factory):
    sessions = session_factory_for(migrated_engine)
    storage = LocalFileStorage(tmp_path_factory.mktemp("uploads"))
    service = IngestionService(
        sessions, storage, PdfplumberExtractor(), ClauseChunker(), FakeEmbedder()
    )
    docs = [
        ("condor_andino_v1.pdf", CONDOR, "CA-2025", 1, date(2025, 1, 1)),
        ("condor_andino_v2.pdf", CONDOR, "CA-2025", 2, date(2026, 3, 1)),
        ("rapido_austral_v1.pdf", RAPIDO, "RA-2025", 1, date(2025, 6, 1)),
    ]
    for sample, carrier, code, version, effective in docs:
        doc_id = register_sample(
            sessions,
            storage,
            sample,
            carrier=carrier,
            contract_code=code,
            version=version,
            effective_from=effective,
        )
        service.ingest(doc_id)
    yield PgVectorRetriever(sessions)
    with sessions.begin() as s:
        s.execute(delete(Document))


def search(retriever, k: int = 6, **filters):
    [vector] = FakeEmbedder().embed([QUESTION])
    return retriever.search(vector, k, SearchFilters(**filters))


def test_best_result_is_the_claims_clause_of_current_version(retriever) -> None:
    results = search(retriever, carrier=CONDOR)
    assert results[0].section == "6. Reclamaciones"
    assert results[0].version == 2 and "diez (10) días" in results[0].content
    assert all(r.carrier == CONDOR and r.is_current for r in results)


def test_scores_are_sorted_and_k_is_respected(retriever) -> None:
    results = search(retriever, k=4)
    assert len(results) == 4
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)


def test_history_includes_previous_versions(retriever) -> None:
    versions = {r.version for r in search(retriever, k=20, carrier=CONDOR, only_current=False)}
    assert versions == {1, 2}


def test_filter_still_returns_k_results(retriever) -> None:
    # Con filtro selectivo, HNSW sin iterative_scan podría quedarse corto
    assert len(search(retriever, k=10, carrier=RAPIDO)) == 10


def test_known_carriers_lists_ready_documents(retriever) -> None:
    assert retriever.known_carriers() == sorted([CONDOR, RAPIDO])
