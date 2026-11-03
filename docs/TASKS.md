# TASKS

Porciones verticales pequeñas. Cada una: requisito(s), test que la demuestra y commit atómico.
Marca `[x]` solo cuando el test pasa **y** puedes explicar el diff.

## Día 1 — Base y datos
- [x] T01 Esqueleto del monorepo, `pyproject` (uv, ruff, pytest), `.env.example`, Makefile · E1, S2
- [x] T02 docker-compose: postgres(pgvector), redis, api, worker; healthchecks (el servicio frontend se añade en T15) · R14
- [x] T03 Settings con pydantic-settings + modelos de dominio estrictos + tests · R1
- [x] T04 Alembic: tablas `documents`/`chunks`, índice HNSW + test de integración (testcontainers) · R7
- [x] T20 GitHub Actions: lint + tests (adelantada; el build de imágenes se añade en T21) · Q5
- [x] T05 Generador de PDFs sintéticos (3 transportistas, 2 versiones, tablas, corrupto, escaneado, malicioso) · E5
- [x] T06 Extractor pdfplumber + errores `invalid_pdf` / `no_text_layer` + tests · R4, F1, F2
- [x] T07 Chunkers `clause` (fallback, tablas por presupuesto y continuación entre páginas) y `fixed`; `build_embedding_text`; PDF fuera de plantilla en samples/; tests (incl. «no se pierde texto») · R4, D2, E5
- [x] T08 Puertos + `FakeEmbedder` / `FakeLLM` extractivo + adaptadores LiteLLM · R10, D15
- [x] T09 Servicio `ingest_document` (transacción única, idempotente) + tarea Celery con reintentos + tests · R4, R5, R6, F8
- [x] T10 `POST /api/documents` + `GET /api/documents[/{id}]` + validación de archivo + tests · R2, R3, S1

## Día 2 — RAG y producto
- [x] T11 Repositorio vectorial: búsqueda con filtros + `resolve_carrier` + tests · R8, D16
- [x] T12 Eval set (frase de evidencia) + `run_eval.py` B0/B1/B2 con embeddings reales → `RESULTS.md` · R13, D2, D17
- [x] T13 Política de evidencia (lista de transportistas en «sin evidencia») + parser de salida estructurada + tests · R11, D7, F9
- [x] T14 `POST /api/chat` SSE + evento `clarification` + manejo de desconexión, timeout y rate limit + tests · R9, F3, F4, F7, D16
- [x] T15 Frontend: Vite + servicio en compose + subida + lista de estado (polling) · R12, R14
- [x] T16 Frontend: chat en streaming + panel de cita + desplegable/«Filtrando por»/«¿Quisiste decir?» + aviso modo demo · R12, D15, D16

## Día 3 — Calidad y entrega
- [ ] T17 OpenTelemetry: instrumentación, spans manuales, atributos, span links · Q2, D10
- [ ] T18 Sweeper + `/health/ready` + tests de Redis/BD caídos · F5, F6
- [ ] T19 Logs JSON sin contenido + test de prompt injection + escáner de secretos en CI (pendiente de aprobar dependencia) · S2, S3, S4
- [ ] T21 CI: build de imágenes · README (Mermaid, arranque, hecho/no hecho), completar DECISIONS y trazabilidad · E2, E3, E4
- [ ] T22 Prueba en limpio: clonar en otra carpeta → `docker compose up --build` → flujo completo
- [ ] T23 **Entregar con ≥ 4 h de margen**
