# DECISIONS

Registro de decisiones de arquitectura (formato ADR breve). Estado posible:
**Propuesta** → **Aceptada** → (si cambia) **Reemplazada por Dxx**.
Las referencias `[Rx]`, `[Fx]`, `[Sx]`, `[Qx]` apuntan a `docs/SPEC.md`.

---

## D0 — Arquitectura: hexagonal ligera (puertos y adaptadores)
**Estado:** Aceptada
**Contexto:** el enunciado exige sustituir LLM y embeddings por fakes deterministas [Q1] y una capa de abstracción del LLM [R10].
**Decisión:** `domain/` (modelos y reglas puras), `ports/` (Protocols), `adapters/` (implementaciones), `services/` (orquestación), `api/` y `worker/` como capas delgadas. Solo existe un puerto si tiene ≥2 implementaciones reales o si hace falta para testear.
**Alternativas descartadas:** monolito con monkeypatch (contratos implícitos); RAG avanzado con Docling + reranker (riesgo en 72 h, ver D1).
**Consecuencias:** ~15 % más código; fakes triviales; la tarea Celery se testea llamando al servicio.

## D1 — Extracción de PDF: pdfplumber
**Estado:** Aceptada
**Contexto:** [R4], [F1], [F2]. Los PDFs son nativos digitales (sintéticos).
**Decisión:** `pdfplumber` para texto por página y `extract_tables()` para tablas de tarifas. 0 caracteres extraíbles → `no_text_layer`.
**Alternativas descartadas:** Docling (mejor layout, pero arrastra torch y modelos: imagen de varios GB, lento en CPU, CI pesada); PyMuPDF (licencia AGPL).
**Pendiente:** medir tamaño de imagen y tiempo por PDF para justificar con números.

## D2 — Chunking: por cláusula + tablas como chunks propios
**Estado:** Aceptada (estrategia final según eval)
**Contexto:** contratos con cláusulas numeradas y anexos de tarifas [R13].
**Decisión:** dividir por encabezados de cláusula (`^\d+(\.\d+)*\s` / `Cláusula N`) con tamaño máximo y división secundaria por párrafo. Cada tabla se serializa a Markdown como chunk `kind=table`, repitiendo la cabecera cada N filas y con prefijo de contexto (transportista, anexo).
**Alternativa a comparar:** ventana fija (~800 tokens, solape 15 %).
**Validación:** `eval/run_eval.py --strategy clause|fixed` → recall@k y MRR en `eval/RESULTS.md`.

## D3 — Versiones: conservar histórico + filtro por vigencia
**Estado:** Aceptada
**Contexto:** [R8]; las cláusulas cambian por versión.
**Decisión:** cada versión es un documento con `contract_code`, `version`, `effective_from`, `is_current` (regla en SPEC §3). La búsqueda filtra `only_current=true` por defecto. Los metadatos se introducen en el formulario de subida (validados con Pydantic).
**Contradicción entre versiones:** se responde con la versión vigente. Si el usuario desactiva `only_current`, el prompt exige señalar la diferencia y citar ambas versiones.
**Alternativas descartadas:** reemplazar (pierde trazabilidad; las reclamaciones dependen de la fecha del envío); extraer metadatos con el LLM (frágil, trabajo futuro).

## D4 — Estado de procesamiento en PostgreSQL
**Estado:** Aceptada
**Contexto:** [R3], [R6], [F5], [F8].
**Decisión:** `documents.status` es la fuente de verdad. Celery con `acks_late=True`, `reject_on_worker_lost=True`, `visibility_timeout` reducido. Borrado e inserción de chunks en **una transacción**. Errores transitorios → `autoretry_for` + `retry_backoff` + `retry_jitter`, `max_retries=5`; permanentes → `FAILED`. Un *sweeper* periódico (Celery beat) reencola `PENDING` sin tarea y `PROCESSING` estancados.
**Alternativas descartadas:** resultado de Celery o Redis (volátil, no consultable con SQL).

## D5 — Idempotencia por sha256
**Estado:** Aceptada
**Decisión:** hash del contenido con `UNIQUE`. Una subida duplicada devuelve el documento existente (`200`, `duplicate=true`). La tarea sale sin hacer nada si el documento ya está `READY` [R5].

## D6 — Proveedor de modelos seleccionable; fake por defecto
**Estado:** Aceptada
**Contexto:** [R10], [R14], [Q1]. El evaluador puede no tener claves.
**Decisión:** `MODEL_PROVIDER=fake|gemini`. Real: LiteLLM con Gemini (LLM) y `text-embedding-004` (768 dim). Fake: embeddings por bolsa de palabras hasheada (determinista, la búsqueda sigue teniendo sentido) y LLM que cita el primer chunk.
**Consecuencias:** `EMBEDDING_DIM` queda fijo en la migración; cambiar de modelo exige migración y reingesta (limitación conocida). No se usa un modelo local: no sería determinista y obligaría a descargar GB en la CI.

## D7 — Streaming con salida estructurada al final
**Estado:** Aceptada
**Contexto:** [R1], [R9]. Hay que hacer streaming de tokens y además validar la salida estructurada del LLM (respuesta, citas, confianza).
**Decisión:** el LLM emite el texto (enviado como `token`), luego `<<<END_ANSWER>>>` y un JSON validado con `LLMStructuredOutput` en modo estricto. Las citas a chunks no recuperados se descartan. Si el JSON no es válido → degradar a «sin evidencia» [F9].
**Alternativas descartadas:** streaming de JSON (mala UX y parseo parcial frágil); dos llamadas al LLM (doble coste y latencia).

## D8 — Anti-alucinación en tres capas
**Estado:** Aceptada
**Decisión:** (1) `top_score < RELEVANCE_THRESHOLD` → «sin evidencia» sin llamar al LLM; (2) el prompt obliga a responder `SIN_EVIDENCIA` si el contexto no lo sostiene; (3) sin citas válidas tras validar → «sin evidencia».
**Validación:** el eval set incluye preguntas sin respuesta; se calibra el umbral con un barrido (precisión de «sin evidencia» frente a recall de las respondibles).

## D9 — SSE por POST con fetch
**Estado:** Aceptada
**Decisión:** `POST /api/chat` con `text/event-stream`; el frontend consume con `fetch` + `ReadableStream`. Desconexión → `request.is_disconnected()` cancela el LLM [F7].
**Por qué no GET + EventSource:** la pregunta viajaría en la URL y acabaría en los logs de proxies [S4].

## D10 — Trazas: dos flujos enlazados
**Estado:** Aceptada
**Contexto:** [Q2] pide una traza que atraviese HTTP, Celery, pgvector y LLM. Ingesta y chat son flujos distintos.
**Decisión:** traza de ingesta (HTTP → Celery → embeddings → BD), con contexto propagado por `opentelemetry-instrumentation-celery` y `trace_id` guardado en `documents`; traza de chat (HTTP → pgvector → LLM), con **span links** a la traza de ingesta de cada documento citado.
**Alternativa descartada:** procesar el chat en Celery (rompe el streaming).
**Depuración de una respuesta mala:** ver README (sección Observabilidad).

## D11 — Validación de archivos por magic bytes
**Estado:** Aceptada · [S1]. Cabecera `%PDF-` y límite de tamaño leído en streaming; no se confía en la extensión ni en el content-type.

## D12 — Mitigación de prompt injection
**Estado:** Aceptada · [S3]. Contexto delimitado como datos no confiables, instrucción explícita en el system prompt y validación de citas. Test con `samples/malicious_injection.pdf`.

## D13 — Logs y trazas sin contenido sensible
**Estado:** Aceptada · [S4]. Logs JSON; preguntas y chunks solo como hash y longitud; `OTEL_CAPTURE_CONTENT=false` por defecto.

## D14 — Acceso a datos: SQLAlchemy 2 síncrono + psycopg 3
**Estado:** Aceptada
**Decisión:** un único estilo (síncrono) compartido por API y worker. En los endpoints async (SSE), la recuperación se ejecuta con `run_in_threadpool`. Para filtros con HNSW se activa `hnsw.iterative_scan` (pgvector ≥ 0.8) para no devolver menos de k resultados al filtrar.
**Alternativa descartada:** SQLAlchemy async en la API y síncrono en el worker (dos estilos y dos sesiones para el mismo esquema).

---

## Uso de IA generativa
_Se completa al final:_ flujo spec → decisiones → tareas → implementación con Claude por porciones, revisión de cada diff, tests escritos antes o junto al código, y qué se dejó fuera de alcance conscientemente.
