# CLAUDE.md

Prueba técnica: asistente RAG de contratos. Fuente de verdad: `docs/SPEC.md` (requisitos con ID),
`DECISIONS.md` (ADRs), `docs/TASKS.md` (orden de trabajo).

## Reglas de trabajo
- Trabajar **una tarea de TASKS.md por vez**. No adelantar trabajo de otras tareas.
- Antes de codificar: indicar qué requisito(s) cubre y qué test lo demostrará.
- Diffs pequeños (< ~200 líneas). Si crece, proponer cómo partir la tarea.
- **No añadir dependencias sin aprobación explícita.**
- Si algo contradice SPEC o DECISIONS, parar y preguntar; no decidir en silencio.
- Tests sin red ni claves: usar `FakeEmbedder` / `FakeLLM`.
- Nunca registrar en logs el contenido de preguntas o chunks (S4). Nunca escribir secretos en el repo.
- Commits en español con el ID: `feat(ingest): idempotencia por sha256 [R5]`. Solo cuando el usuario lo pida.

## Convenciones
- Python 3.12, FastAPI, Pydantic v2 (`strict=True`, `extra="forbid"`), SQLAlchemy 2 síncrono + psycopg 3, Alembic, Celery + Redis, pgvector.
- Código e identificadores en inglés; documentación en español.
- Arquitectura: `domain/` sin I/O · `ports/` Protocols · `adapters/` · `services/` · `api/` y `worker/` delgados.
- Frontend: Vite + React + TypeScript.
