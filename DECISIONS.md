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

## D2 — Chunking estructural con fallback + contexto solo para el embedding
**Estado:** Aceptada (revisada 2026-11-03; estrategia final según eval)
**Contexto:** el enunciado describe contratos «con tablas y cláusulas» [R13]. Medido en `samples/`: cláusulas de 119–463 caracteres, una cláusula repartida entre dos páginas (`condor_andino_v1`, cláusula 8), texto extraído sin líneas en blanco (no hay párrafos detectables) y tablas de ~720 caracteres.
**Decisión:**
- Encabezados reconocidos: `1.` / `1.1`, `Cláusula N`, `Artículo N`, ordinales (`PRIMERA.-`, `SEGUNDA.`), `Anexo …`. Un chunk por cláusula; si supera el presupuesto (`max_chars`), se divide por apartado y después por ventana dura. Sin encabezados → ventanas. Nada del texto se pierde (invariante con test).
- Tablas: bloques de filas completas por presupuesto (`table_max_chars`), cabecera repetida en cada bloque, `section` = encabezado anterior (p. ej. «Anexo I. Tarifas»). Una tabla en la página siguiente con el mismo número de columnas y sin cabecera se trata como continuación y reutiliza la cabecera anterior.
- Procedencia: cada chunk declara `page_start`–`page_end`; un chunk multipágina se cita como rango, nunca como una sola página.
- `content` (texto fuente, el que se cita) se guarda tal cual. `embedding_text` = cabecera determinista (transportista · contrato vN · sección) + contenido; se calcula con una función de dominio compartida por ingesta y eval y **no se persiste**.
**Alternativa de referencia:** ventanas fijas de 800 caracteres con 15 % de solape; tablas como texto plano.
**Validación:** eval B0 (fixed sin cabecera) · B1 (estructural sin cabecera) · B2 (estructural con cabecera), con embeddings reales; ver D17.
**Descartado:** chunking o contextualización con LLM, rerankers, BM25, recuperación jerárquica (sin necesidad demostrada en este corpus); segmentos de procedencia por frase (las cláusulas son cortas y la cita muestra el fragmento completo); división por párrafo (el extractor no los produce).
**Limitaciones:** corpus sintético generado por nosotros (riesgo de sobreajuste, mitigado con patrones genéricos, fallback y un PDF fuera de plantilla); maquetación a varias columnas y tablas sin bordes no se tratan bien (requeriría un parser de layout como Docling). Cambiar la cabecera del embedding exige reingesta.

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
**Decisión:** `MODEL_PROVIDER=fake|gemini`. Real: LiteLLM con Gemini (LLM) y `gemini-embedding-001` reducido a 768 dim (`dimensions=768`; `text-embedding-004` está deprecado). Fake: embeddings por bolsa de palabras hasheada (determinista; compara palabras, no significados) y LLM extractivo (ver D15).
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

## D15 — Modo sin claves: extractivo, visible y documentado
**Estado:** Aceptada · [R14]. Sin `GEMINI_API_KEY` el sistema debe arrancar y ser útil.
**Decisión:** (1) README explica cómo obtener una clave gratuita y activarla en `.env`; (2) el `FakeLLM` es **extractivo**: devuelve la(s) frase(s) del contexto con más solapamiento con la pregunta, con su cita (determinista, no puede alucinar); (3) la web muestra un aviso «Modo demostración» cuando `MODEL_PROVIDER=fake`; (4) `eval/RESULTS.md` publica las métricas medidas con embeddings reales.
**Descartado:** Ollama con modelos locales (varios GB, lento en CPU, modelos pequeños rompen el formato de salida → muchas degradaciones F9); demo desplegada con nuestra clave (coste, abuso de cuota, fuera de plazo). Nunca se publica una clave en el repositorio [S2].

## D16 — Resolución del transportista: filtrar solo si es casi exacto, preguntar si es parecido
**Estado:** Aceptada · [R8]. El enunciado pide filtro por transportista y preguntas en lenguaje natural.
**Decisión:** `resolve_carrier(question, known_carriers)` con `difflib` (sin dependencias) sobre los transportistas existentes en BD:
- coincidencia ≥ 0,9 → filtro automático, visible en la UI («Filtrando por: …»);
- 0,6–0,9 → evento SSE `clarification` («¿Quisiste decir …?») con botones; **no se llama al LLM**; el botón reenvía la misma pregunta con el filtro (sin estado en servidor);
- dos o más transportistas o ninguno → sin filtro (pregunta comparativa o general);
- la respuesta «sin evidencia» lista los transportistas disponibles.
El usuario puede fijar el transportista a mano con un desplegable; el filtro explícito tiene prioridad.
**Principio:** ante una ambigüedad se pregunta en vez de adivinar (misma filosofía que «sin evidencia»).
**Descartado:** resolución de entidades con LLM o agentes; detectar nombres de transportistas desconocidos (no hay forma fiable de saber que una palabra es un nombre).

## D17 — Evaluación de recuperación
**Estado:** Aceptada · [R13].
**Decisión:** cada pregunta guarda el archivo y una **frase de evidencia** esperada; un chunk es relevante si viene de ese archivo y contiene la frase (referencia estable entre estrategias, no IDs de chunk). Se reportan recall@1, recall@3, recall@k y MRR para B0/B1/B2 con corpus, preguntas, modelo, filtros (`only_current=true`) y k constantes. Incluye preguntas sin filtro de transportista y al menos una sobre el PDF fuera de plantilla. Las métricas publicadas se miden con **embeddings reales**; con el fake (léxico) B2 ganaría de forma trivial, así que en CI el eval solo se ejecuta como prueba del script. La abstención («sin evidencia») se evalúa aparte al calibrar el umbral (T13).
**Limitación:** B0 frente a B1 mezcla dos cambios (segmentación y tablas). Corpus pequeño: recall@k alto puede saturarse.

---

## Uso de IA generativa
_Se completa al final:_ flujo spec → decisiones → tareas → implementación con Claude por porciones, revisión de cada diff, tests escritos antes o junto al código, y qué se dejó fuera de alcance conscientemente.
