"""El script de evaluación funciona y sus métricas son correctas [R13, D17]."""

import importlib.util
import sys

from scripts.generate_samples import ROOT

spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
sys.modules["run_eval"] = run_eval
spec.loader.exec_module(run_eval)


def test_metrics() -> None:
    rows = [
        {"answerable": True, "rank": 1, "top_score": 0.9},
        {"answerable": True, "rank": 2, "top_score": 0.8},
        {"answerable": True, "rank": None, "top_score": 0.4},
        {"answerable": False, "rank": None, "top_score": 0.5},
    ]
    m = run_eval.metrics(rows)
    assert m["recall@1"] == 1 / 3 and m["recall@3"] == 2 / 3
    assert m["MRR"] == (1 + 0.5) / 3


def test_threshold_prioritizes_not_inventing() -> None:
    separable = [
        {"answerable": True, "rank": 1, "top_score": 0.8},
        {"answerable": False, "rank": None, "top_score": 0.6},
    ]
    assert run_eval.calibrate_threshold(separable) == (0.7, 0)
    overlapping = separable + [{"answerable": True, "rank": 1, "top_score": 0.55}]
    assert run_eval.calibrate_threshold(overlapping) == (0.61, 1)


def test_gemini_cache_covers_every_text() -> None:
    # La caché versionada permite reproducir las cifras publicadas sin clave
    def no_network():
        raise AssertionError("faltan vectores en eval/embeddings_cache.json")

    embedder = run_eval.CachedEmbedder(
        "gemini/gemini-embedding-001", ROOT / "eval" / "embeddings_cache.json", no_network
    )
    for strategy, context in run_eval.STRATEGIES.values():
        chunks = run_eval.build_index(strategy, context, embedder)
        embedder.embed([c.embedding_text for c in chunks])
    assert embedder.misses == 0
