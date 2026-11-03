"""Evaluación de recuperación B0/B1/B2 [R13, D17].

Uso (desde la raíz):  make eval            # Gemini (usa la caché; la clave solo si falta algo)
                      make eval-fake       # proveedor falso: comprueba el script, no es semántico

Búsqueda en memoria con coseno exacto y los mismos filtros que el sistema: versión vigente y
transportista resuelto con resolve_carrier [D16]. Con ~80 chunks, exacto y HNSW coinciden.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import yaml  # noqa: E402

from app.adapters.fake_providers import FakeEmbedder  # noqa: E402
from app.adapters.litellm_providers import LiteLLMEmbedder  # noqa: E402
from app.adapters.pdfplumber_extractor import PdfplumberExtractor  # noqa: E402
from app.domain.carriers import Match, resolve_carrier  # noqa: E402
from app.domain.chunking import ClauseChunker, FixedChunker, build_embedding_text  # noqa: E402
from app.domain.errors import EmbeddingProviderError  # noqa: E402

EVAL = ROOT / "eval"
SAMPLES = ROOT / "samples"
K = 6
BATCH = 50
WAIT_S = 60
MAX_WAITS = 5
STRATEGIES = {
    "B0": ("fixed", False),  # ventanas fijas, sin cabecera de contexto
    "B1": ("clause", False),  # estructural, sin cabecera
    "B2": ("clause", True),  # estructural + cabecera (la del sistema)
}


@dataclass(frozen=True)
class IndexedChunk:
    file: str
    carrier: str
    is_current: bool
    content: str
    embedding_text: str


class CachedEmbedder:
    """Vectores por (modelo, texto) guardados en un JSON versionado: el eval es reproducible
    sin clave. Solo llama al proveedor para los textos que falten."""

    def __init__(self, model: str, path: Path, provider_factory) -> None:
        self.model = model
        self.path = path
        self.cache: dict[str, list[float]] = (
            json.loads(path.read_text()).get(model, {}) if path.exists() else {}
        )
        self._factory = provider_factory
        self.misses = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [_key(t) for t in texts]
        missing = list(dict.fromkeys(t for t, k in zip(texts, keys, strict=True) if k not in self.cache))
        # Cuota gratuita de Gemini: 100 textos/minuto. Tandas pequeñas, guardando el progreso
        for start in range(0, len(missing), BATCH):
            batch = missing[start : start + BATCH]
            for attempt in range(MAX_WAITS + 1):
                try:
                    vectors = self._factory().embed(batch)
                    break
                except EmbeddingProviderError:
                    if attempt == MAX_WAITS:
                        raise
                    print(f"rate limit: espero {WAIT_S} s…", file=sys.stderr)
                    time.sleep(WAIT_S)
            for text, vector in zip(batch, vectors, strict=True):
                self.cache[_key(text)] = [round(x, 5) for x in vector]
            self.misses += len(batch)
            self.save()
        return [self.cache[key] for key in keys]

    def save(self) -> None:
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        data[self.model] = dict(sorted(self.cache.items()))
        self.path.write_text(json.dumps(data, separators=(",", ":")) + "\n")


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def gemini_embedder() -> LiteLLMEmbedder:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("Faltan vectores en la caché y no hay GEMINI_API_KEY para calcularlos.")
    return LiteLLMEmbedder("gemini/gemini-embedding-001", 768, key, timeout_s=60)


def build_index(strategy: str, with_context: bool, embedder) -> list[IndexedChunk]:
    manifest = [m for m in json.loads((SAMPLES / "manifest.json").read_text()) if m["seed"]]
    current = _current_files(manifest)
    chunker = FixedChunker() if strategy == "fixed" else ClauseChunker()
    extractor = PdfplumberExtractor()
    chunks: list[IndexedChunk] = []
    for meta in manifest:
        for draft in chunker.chunk(extractor.extract((SAMPLES / meta["file"]).read_bytes())):
            text = (
                build_embedding_text(
                    draft,
                    carrier=meta["carrier"],
                    contract_code=meta["contract_code"],
                    version=meta["version"],
                )
                if with_context
                else draft.content
            )
            chunks.append(
                IndexedChunk(meta["file"], meta["carrier"], meta["file"] in current, draft.content, text)
            )
    return chunks


def _current_files(manifest: list[dict]) -> set[str]:
    """Misma regla que el sistema: mayor versión ya en vigor por contrato [D3]."""
    best: dict[tuple[str, str], dict] = {}
    for m in manifest:
        if date.fromisoformat(m["effective_from"]) > date.today():
            continue
        key = (m["carrier"], m["contract_code"])
        if key not in best or m["version"] > best[key]["version"]:
            best[key] = m
    return {m["file"] for m in best.values()}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def evaluate(questions: list[dict], chunks: list[IndexedChunk], embedder) -> list[dict]:
    vectors = embedder.embed([c.embedding_text for c in chunks])
    query_vectors = embedder.embed([q["question"] for q in questions])
    carriers = sorted({c.carrier for c in chunks})
    rows = []
    for q, qv in zip(questions, query_vectors, strict=True):
        resolution = resolve_carrier(q["question"], carriers)
        carrier = resolution.carriers[0] if resolution.match is Match.EXACT else None
        candidates = [
            (cosine(qv, v), c)
            for c, v in zip(chunks, vectors, strict=True)
            if c.is_current and (carrier is None or c.carrier == carrier)
        ]
        top = sorted(candidates, key=lambda s: -s[0])[:K]
        rank = None
        if q.get("answerable", True):
            evidence = normalize(q["evidence"])
            rank = next(
                (
                    i
                    for i, (_, c) in enumerate(top, start=1)
                    if c.file == q["file"] and evidence in normalize(c.content)
                ),
                None,
            )
        rows.append(
            {
                "id": q["id"],
                "answerable": q.get("answerable", True),
                "carrier_filter": carrier,
                "rank": rank,
                "top_score": top[0][0] if top else 0.0,
            }
        )
    return rows


def metrics(rows: list[dict]) -> dict[str, float]:
    answerable = [r for r in rows if r["answerable"]]
    ranks = [r["rank"] for r in answerable]

    def recall(k: int) -> float:
        return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)

    return {
        "recall@1": recall(1),
        "recall@3": recall(3),
        f"recall@{K}": recall(K),
        "MRR": sum(1 / r for r in ranks if r) / len(ranks),
    }


def calibrate_threshold(rows: list[dict]) -> tuple[float, int]:
    """Prioridad «no inventar» [D8]: rechazar todas las preguntas sin respuesta.

    Si los grupos se separan, punto medio; si no, justo por encima de la peor sin respuesta.
    Devuelve (umbral, preguntas con respuesta que quedarían rechazadas).
    """
    hits = [r["top_score"] for r in rows if r["answerable"] and r["rank"] is not None]
    unanswerable = [r["top_score"] for r in rows if not r["answerable"]]
    highest_bad = max(unanswerable)
    lowest_good = min(hits)
    threshold = (highest_bad + lowest_good) / 2 if lowest_good > highest_bad else highest_bad + 0.01
    threshold = round(threshold, 2)
    return threshold, sum(1 for s in hits if s < threshold)


def report(provider: str, model: str, results: dict[str, list[dict]]) -> str:
    lines = [
        f"## Proveedor `{provider}` · modelo `{model}`",
        "",
        f"Corpus: PDFs `seed=true` de `samples/` · solo versiones vigentes · k={K} · "
        "filtro de transportista con `resolve_carrier`.",
        "",
        f"| Estrategia | recall@1 | recall@3 | recall@{K} | MRR | umbral único | "
        "umbral con transportista | umbral general | respondibles rechazadas (2 umbrales) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, rows in results.items():
        m = metrics(rows)
        single, _ = calibrate_threshold(rows)
        # Dos grupos: la pregunta nombra un transportista (filtro detectado) o es general [D8]
        named, lost_named = calibrate_threshold([r for r in rows if r["carrier_filter"]])
        general, lost_general = calibrate_threshold([r for r in rows if not r["carrier_filter"]])
        lines.append(
            f"| {name} {STRATEGIES[name]} | {m['recall@1']:.2f} | {m['recall@3']:.2f} | "
            f"{m[f'recall@{K}']:.2f} | {m['MRR']:.2f} | {single:.2f} | {named:.2f} | "
            f"{general:.2f} | {lost_named + lost_general} |"
        )
    lines += ["", "Rango del primer resultado relevante por pregunta (— = no está en el top-k):", ""]
    lines.append("| Pregunta | filtro | " + " | ".join(results) + " | top score (B2) |")
    lines.append("|---|---|" + "---|" * len(results) + "---|")
    for i, row in enumerate(results["B2"]):
        ranks = [
            "sin resp." if not r[i]["answerable"] else str(r[i]["rank"] or "—")
            for r in results.values()
        ]
        lines.append(
            f"| {row['id']} | {row['carrier_filter'] or '—'} | "
            + " | ".join(ranks)
            + f" | {row['top_score']:.3f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["gemini", "fake"], default="gemini")
    parser.add_argument("--write", type=Path, help="guarda el informe en este archivo")
    args = parser.parse_args()

    questions = yaml.safe_load((EVAL / "questions.yaml").read_text(encoding="utf-8"))
    if args.provider == "fake":
        model, embedder = "fake (léxico)", FakeEmbedder()
    else:
        model = "gemini/gemini-embedding-001"
        embedder = CachedEmbedder(model, EVAL / "embeddings_cache.json", gemini_embedder)

    results = {
        name: evaluate(questions, build_index(strategy, context, embedder), embedder)
        for name, (strategy, context) in STRATEGIES.items()
    }
    text = report(args.provider, model, results)
    print(text)
    if args.write:
        args.write.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
