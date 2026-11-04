# SPEC — Asistente RAG de contratos (Norvia Freight)

> Fuente: enunciado de la prueba técnica TopDevCrew. Cada requisito tiene un ID
> estable. Commits, tests y DECISIONS.md lo referencian (`[R4]`, `[F3]`…).
> Estado: **aprobada 2026-11-02** · Entrega: 2026-11-05 23:21 UTC

## 0. Alcance

Operaciones sube contratos/anexos PDF → el sistema los procesa en segundo plano
→ se hacen preguntas en lenguaje natural → respuestas en streaming con citas
verificables (documento, versión, página) o «no encuentro evidencia».

**Fuera de alcance (MVP):** autenticación de usuarios, OCR, extracción automática
de metadatos del PDF, multi-tenant, edición/borrado de documentos desde la UI,
historial persistente de conversaciones.

## 1. Requisitos funcionales

| ID | Requisito | Criterios de aceptación |
|----|-----------|-------------------------|
| R1 | Modelos Pydantic v2 **estrictos** en entradas, salidas y salida estructurada del LLM | Todos los modelos usan `ConfigDict(strict=True, extra="forbid")`. Test: un campo extra o un tipo coaccionable (`"3"` por `3`) produce error de validación. |
| R2 | Endpoint de subida de documentos | `POST /api/documents` (multipart) → `202` con `document_id` y `status=PENDING`. Si el hash ya existe → `200` con el documento existente y `duplicate=true`. |
| R3 | Endpoint de estado de procesamiento | `GET /api/documents/{id}` devuelve `status`, `error_code`, `attempts`, `chunk_count`, `updated_at`. `404` si no existe. `GET /api/documents` lista todos. |
| R4 | Pipeline de ingesta asíncrono (Celery + Redis) | La tarea ejecuta: extracción → chunking → embeddings → escritura en PostgreSQL. La API nunca procesa el PDF en el hilo de la petición. |
| R5 | Idempotencia por hash | `sha256` del contenido con `UNIQUE`. Reejecutar la tarea sobre un documento `READY` no duplica chunks (test cuenta filas). |
| R6 | Reintentos con backoff | Errores transitorios (proveedor de embeddings, BD) → reintento exponencial con jitter, `max_retries=5`. Errores permanentes (PDF inválido) → `FAILED` sin reintentar. |
| R7 | pgvector con migraciones e índice | Esquema gestionado con Alembic. Índice **HNSW** (`vector_cosine_ops`) sobre `chunks.embedding`. `alembic upgrade head` desde cero funciona. |
| R8 | Búsqueda híbrida simple | Similitud vectorial + filtro por metadatos: `carrier` (opcional) y `only_current` (por defecto `true`). Devuelve top-k con score. |
| R9 | Chat con streaming SSE | `POST /api/chat` → `text/event-stream` con eventos `retrieval`, `token`, `citations`, `done`, `error` (ver §4). |
| R10 | Capa de abstracción del LLM | Puertos `LLM` y `Embedder` (Protocol). Adaptadores: `LiteLLM*` (real) y `Fake*` (determinista). Selección por `MODEL_PROVIDER`. |
| R11 | Política anti-alucinación | Umbral `RELEVANCE_THRESHOLD` configurable. Si ningún chunk lo supera → respuesta «No encuentro evidencia…» **sin llamar al LLM**, con la lista de transportistas disponibles. Validación documentada con preguntas sin respuesta en el eval set. |
| R12 | Frontend React | Subida de documentos con metadatos, vista de estado (polling), chat con streaming, citas clicables que muestran el fragmento original con documento, versión y rango de páginas. Campo de transportista con sugerencias al escribir, etiqueta «Filtrando por: …», botones de «¿Quisiste decir…?» (D16), aviso de «Modo demostración» si `MODEL_PROVIDER=fake` (D15), formulario pre-rellenado desde la portada del PDF (D19) y aviso de documentos por actualizar con otro modelo de embeddings (D6). |
| R13 | Evaluación de recuperación | 10–15 preguntas con respuesta esperada, archivo fuente y frase de evidencia (`eval/questions.yaml`). Script `eval/run_eval.py` reporta recall@1/@3/@k y MRR para B0/B1/B2 (D17). Resultados con embeddings reales en `eval/RESULTS.md`. |
| R14 | Un solo comando | `docker compose up --build` levanta API, worker, Redis, PostgreSQL+pgvector y frontend. Incluye PDFs sintéticos y funciona **sin claves** (`MODEL_PROVIDER=fake`). |

## 2. Requisitos de calidad

| ID | Requisito | Criterios de aceptación |
|----|-----------|-------------------------|
| Q1 | Tests automatizados | Unitarios: chunking, modelos Pydantic, política de evidencia, parser de salida del LLM. Integración: PostgreSQL+pgvector real (testcontainers). Tarea Celery: ejecución real de la tarea. **Ningún test usa red ni claves.** `make test` los ejecuta. |
| Q2 | OpenTelemetry | Traza de ingesta: `POST /api/documents` → `apply_async/ingest_document` → (worker) `run/ingest_document` → `ingest.extract` → `ingest.chunk` → `ingest.embed` → `ingest.store`. Traza de chat: `POST /api/chat` → `rag.chat` → `rag.embed_query` → `rag.retrieve` → `pgvector.search` → `llm.stream`. Atributos: latencia, `rag.k`, `rag.top_score`, `rag.threshold`, `llm.tokens.input/output`, `llm.time_to_first_token_ms`, `llm.model`. Span links del chat a la traza de ingesta de los documentos citados. Exportación a consola u OTLP local. |
| Q5 | CI | GitHub Actions: lint (ruff + eslint), tests backend, build de imágenes Docker. |

### Q3 — Manejo de fallos (cada caso con comportamiento definido y test)

| ID | Caso | Comportamiento esperado |
|----|------|-------------------------|
| F1 | PDF corrupto | `FAILED`, `error_code=invalid_pdf`, sin reintentos. |
| F2 | PDF escaneado sin texto | `FAILED`, `error_code=no_text_layer` (OCR fuera de alcance). |
| F3 | Timeout del LLM | Evento SSE `error` con `code=llm_timeout`; la conexión se cierra limpiamente. |
| F4 | Rate limit del LLM / embeddings | Chat: reintento con backoff acotado; si persiste, `error` `code=llm_rate_limited`. Ingesta: reintento Celery (R6). |
| F5 | Redis caído | Subida: el documento se guarda como `PENDING` y responde `202`; un *sweeper* reencola `PENDING`/`PROCESSING` estancados. `/health/ready` reporta Redis caído. |
| F6 | Base de datos caída | API responde `503` con error tipado; `/health/ready` falla; la tarea Celery reintenta (R6). |
| F7 | Cliente cierra el SSE a mitad | Se detecta la desconexión, se cancela el stream del LLM, el span registra `sse.client_disconnected=true`. Sin excepciones no controladas. |
| F8 | Worker muere a mitad de ingesta | Chunks escritos en una sola transacción → no quedan parciales. `acks_late` + sweeper → el documento se reprocesa. |
| F9 | Salida estructurada del LLM inválida | Se descarta y la respuesta se degrada a «sin evidencia» con `confidence=low`. |

### Q4 — Seguridad

| ID | Requisito | Criterios de aceptación |
|----|-----------|-------------------------|
| S1 | Validación de archivos | Solo PDF verificado por *magic bytes* (`%PDF-`). Tamaño máximo `MAX_UPLOAD_MB` (por defecto 20) → `413`. Tipo inválido → `415`. |
| S2 | Secretos | Solo por variables de entorno (`pydantic-settings`). `.env` en `.gitignore`; `.env.example` sin valores reales. |
| S3 | Prompt injection | El contexto va delimitado y marcado como datos no confiables; el system prompt prohíbe seguir instrucciones del contexto; las citas a chunks no recuperados se descartan. Test con PDF sintético malicioso. |
| S4 | Logs sin datos sensibles | Logs JSON estructurados. Preguntas y contenido de chunks no se registran: solo hash y longitud. `OTEL_CAPTURE_CONTENT=false` por defecto. |

## 3. Modelo de datos

```
documents
  id               uuid PK
  sha256           char(64) UNIQUE
  filename         text
  carrier          text            -- transportista (normalizado)
  contract_code    text            -- agrupa versiones de un mismo contrato
  version          int
  effective_from   date
  is_current       bool            -- recalculado al pasar a READY
  status           enum(PENDING, PROCESSING, READY, FAILED)
  error_code       text NULL
  attempts         int
  chunk_count      int             -- se escribe en la misma transacción que los chunks
  page_count       int NULL
  trace_id         text NULL       -- traza de ingesta (Q2)
  ingest_span_id   text NULL       -- span de ingesta: enlaces desde el chat (D10)
  embedding_model  text NULL       -- modelo con que se vectorizó; detecta desfasados (D6)
  created_at / updated_at / processing_started_at
  UNIQUE (carrier, contract_code, version)
  UNIQUE (carrier, contract_code) WHERE is_current   -- una sola versión vigente

chunks
  id               uuid PK
  document_id      uuid FK → documents ON DELETE CASCADE
  chunk_index      int
  kind             enum(text, table)
  section          text NULL       -- p. ej. "Cláusula 7.2"
  page_start       int
  page_end         int
  content          text
  embedding        vector(EMBEDDING_DIM)
  INDEX hnsw (embedding vector_cosine_ops)
```

**Regla de vigencia:** para cada `(carrier, contract_code)`, `is_current=true` en la
versión `READY` con mayor `version` cuya `effective_from <= hoy`.

## 4. Contratos de la API

```
POST /api/documents            multipart: file, carrier, contract_code, version, effective_from
  202 DocumentOut | 200 DocumentOut(duplicate=true) | 413 | 415 | 422 | 503
POST /api/documents/suggest    multipart: file → metadatos propuestos desde la portada (D19); no guarda nada
POST /api/documents/reindex    → {requeued}: reprocesa documentos de otro modelo de embeddings (D6)
GET  /api/documents            → list[DocumentOut]
GET  /api/documents/{id}       → DocumentOut | 404
GET  /api/chunks/{id}          → ChunkOut (fragmento original para la cita)
POST /api/chat                 json ChatRequest → text/event-stream
GET  /api/config               → {demo_mode, llm_model, embedding_model, carriers, stale_documents}
GET  /health/live              → 200
GET  /health/ready             → 200 | 503 (comprueba BD y Redis)
```

```
ChatRequest   { question: str(3..1000), carrier: str | None, only_current: bool = true, k: int(1..20) = 6 }

SSE:
  event: clarification data: { suggestions: [carrier] }   -- «¿Quisiste decir…?» (D16); termina el stream
  event: retrieval   data: { k, top_score, carrier_filter, chunks: [{chunk_id, score}] }
  event: token       data: { text }
  event: citations   data: { citations: [CitationOut], confidence, evidence: bool }
  event: done        data: { answer: str }
  event: error       data: { code, message }

CitationOut   { label, chunk_id, document_id, filename, carrier, version, page_start, page_end, snippet }
```

**Salida estructurada del LLM:** texto de respuesta, seguido de la línea
`<<<END_ANSWER>>>` y un JSON validado con `LLMStructuredOutput`:

```
LLMStructuredOutput { citations: list[{chunk_id: str}], confidence: "high" | "medium" | "low" }
```

## 5. Entregables (E)

| ID | Entregable |
|----|------------|
| E1 | Monorepo público: `backend/`, `frontend/`, `eval/`, `samples/`, `docker-compose.yml`, `.github/workflows/` |
| E2 | README: arranque desde cero, variables de entorno, hecho / no hecho, limitaciones, diagrama Mermaid |
| E3 | DECISIONS.md |
| E4 | Instrucciones de tests + `eval/RESULTS.md` |
| E5 | PDFs sintéticos en `samples/` (incluye corrupto, escaneado, malicioso y uno fuera de plantilla) |

## 6. Trazabilidad

Rutas relativas a `backend/` salvo indicación. Tests: `tests/unit/` (u) y `tests/integration/` (i).

| ID | Implementación | Tests |
|----|----------------|-------|
| R1 | `app/domain/models.py` (`StrictModel`) | u `test_models.py`, u `test_answer.py` |
| R2 | `app/api/documents.py`, `app/services/documents.py` | i `test_documents_api.py` |
| R3 | `GET /api/documents[/{id}]` en `app/api/documents.py` | i `test_get_and_list_documents` |
| R4 | `app/services/ingestion.py`, `app/worker/tasks.py`, `app/adapters/pdfplumber_extractor.py`, `app/domain/chunking/` | i `test_ingestion.py`, u `test_extractor.py`, u `test_chunking.py` |
| R5 | sha256 `UNIQUE`, `DocumentService.register`, `Outcome.ALREADY_READY` | i `test_ingest_is_idempotent`, i `test_same_file_same_metadata_is_idempotent` |
| R6 | `autoretry_for` + `retry_backoff` en `app/worker/tasks.py` | i `test_task_retries_*`, i `test_task_marks_failed_*` |
| R7 | `migrations/versions/0001…`, `0002…`, `app/adapters/db/tables.py` | i `test_schema.py` (incl. ORM == migración) |
| R8 | `app/adapters/db/retriever.py`, `app/domain/carriers.py` | i `test_retriever.py`, u `test_carriers.py` |
| R9 | `app/api/chat.py`, `app/services/chat.py` | u `test_chat.py` (incl. formato SSE) |
| R10 | `app/ports/`, `app/adapters/{fake,litellm}_providers.py`, `providers.py` | u `test_providers.py` |
| R11 | Umbral en `ChatService`, `app/domain/answer.py`, `CALIBRATED_THRESHOLDS` | u `test_low_score_skips_llm_*`, u `test_answer.py`, `eval/RESULTS.md` |
| R12 | `frontend/src/` | lint + tipos en CI; prueba manual |
| R13 | `eval/questions.yaml`, `eval/run_eval.py` | u `test_eval.py`, `eval/RESULTS.md` |
| R14 | `docker-compose.yml` (incl. `seed`) | prueba en limpio (T22) |
| Q1 | Fakes deterministas, testcontainers | `make test` (171) |
| Q2 | `app/observability.py`, spans en servicios | u `test_chat_trace_*`, i `test_ingestion_trace_*` |
| Q5 | `.github/workflows/ci.yml` | 4 jobs en verde |
| F1–F2 | `PdfplumberExtractor` + errores permanentes | u `test_extractor.py`, i `test_permanent_errors_mark_failed` |
| F3–F4 | `LiteLLMChat` (mapeo de errores), reintento en `ChatService` | u `test_timeout_*`, u `test_rate_limit_*`, u `test_chat_maps_provider_errors` |
| F5 | 202 + `PENDING`, sweeper, `/health/ready` | i `test_redis_down_*`, i `test_sweeper_*`, i `test_ready_*` |
| F6 | Handler de `OperationalError`, reintento de la tarea | i `test_database_down_returns_503` |
| F7 | `event_stream` + `aclosing` | u `test_client_disconnect_closes_llm_stream` |
| F8 | Transacción única + `acks_late` + sweeper + locks (D18) | i `test_rerun_after_crash_*`, i `test_concurrent_versions_*` |
| F9 | `parse_llm_output` / `finalize` | u `test_invalid_structured_output_degrades` |
| S1 | Magic bytes, límites de tamaño, nombre saneado | i `test_file_validation`, i `test_filename_cannot_escape_storage` |
| S2 | `pydantic-settings`, `SecretStr`, gitleaks en CI | u `test_secrets_do_not_leak_in_repr` |
| S3 | Evidencia delimitada, citas validadas | u `test_document_cannot_close_the_evidence_tag`, i `test_injected_instructions_*` |
| S4 | `app/logging_config.py`, `text_attributes` | u `test_logging.py`, u `test_question_text_is_not_in_spans_by_default` |
