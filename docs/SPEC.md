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
| R11 | Política anti-alucinación | Umbral `RELEVANCE_THRESHOLD` configurable. Si ningún chunk lo supera → respuesta «No encuentro evidencia…» **sin llamar al LLM**. Validación documentada con preguntas sin respuesta en el eval set. |
| R12 | Frontend React | Subida de documentos con metadatos, vista de estado (polling), chat con streaming, citas clicables que muestran el fragmento original con documento, versión y página. |
| R13 | Evaluación de recuperación | 10–15 preguntas con respuesta esperada y fuente (`eval/questions.yaml`). Script `eval/run_eval.py` reporta recall@k y MRR, por estrategia de chunking. Resultados en `eval/RESULTS.md`. |
| R14 | Un solo comando | `docker compose up --build` levanta API, worker, Redis, PostgreSQL+pgvector y frontend. Incluye PDFs sintéticos y funciona **sin claves** (`MODEL_PROVIDER=fake`). |

## 2. Requisitos de calidad

| ID | Requisito | Criterios de aceptación |
|----|-----------|-------------------------|
| Q1 | Tests automatizados | Unitarios: chunking, modelos Pydantic, política de evidencia, parser de salida del LLM. Integración: PostgreSQL+pgvector real (testcontainers). Tarea Celery: ejecución real de la tarea. **Ningún test usa red ni claves.** `make test` los ejecuta. |
| Q2 | OpenTelemetry | Traza de ingesta: `HTTP POST /documents` → `celery.ingest_document` → `extract` → `chunk` → `embed` → `db.insert_chunks`. Traza de chat: `HTTP POST /chat` → `retrieval.pgvector` → `llm.stream`. Atributos: latencia, `rag.k`, `rag.top_score`, `llm.tokens.input/output`, `llm.model`. Span links del chat a la traza de ingesta de los documentos citados. Exportación a consola u OTLP local. |
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
GET  /api/documents            → list[DocumentOut]
GET  /api/documents/{id}       → DocumentOut | 404
GET  /api/chunks/{id}          → ChunkOut (fragmento original para la cita)
POST /api/chat                 json ChatRequest → text/event-stream
GET  /health/live              → 200
GET  /health/ready             → 200 | 503 (comprueba BD y Redis)
```

```
ChatRequest   { question: str(3..1000), carrier: str | None, only_current: bool = true, k: int(1..20) = 6 }

SSE:
  event: retrieval   data: { k, top_score, chunks: [{chunk_id, score}] }
  event: token       data: { text }
  event: citations   data: { citations: [CitationOut], confidence, evidence: bool }
  event: done        data: { answer: str }
  event: error       data: { code, message }

CitationOut   { chunk_id, document_id, filename, carrier, version, page_start, page_end, snippet }
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
| E5 | PDFs sintéticos en `samples/` (incluye corrupto, escaneado y malicioso) |

## 6. Trazabilidad (se completa al implementar)

| ID | Implementación | Test |
|----|----------------|------|
| R1 | | |
| … | | |
