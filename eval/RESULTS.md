# Resultados de la evaluación de recuperación

Fecha: 2026-11-03 · Script: [`run_eval.py`](run_eval.py) · Preguntas: [`questions.yaml`](questions.yaml)
Detalle completo: [`results_gemini.md`](results_gemini.md) (embeddings reales) y
[`results_fake.md`](results_fake.md) (proveedor falso, solo como prueba del script).

## Cómo se mide [D17]

- **Corpus:** los 5 PDFs `seed=true` de `samples/`, incluido uno fuera de plantilla (`vientos_sur_v1.pdf`).
- **Preguntas:** 12 con respuesta (2 sin transportista, 2 sobre tablas, 2 sobre el PDF fuera de
  plantilla, 1 paráfrasis sin las palabras del contrato) y 3 sin respuesta.
- **Relevancia:** un resultado acierta si viene del archivo esperado y contiene la frase de
  evidencia. Así la referencia no depende de cómo se trocee.
- **Constantes:** mismo corpus, preguntas, modelo (`gemini-embedding-001`, 768 dim), k = 6, solo
  versiones vigentes y transportista resuelto con `resolve_carrier` como en el sistema real.
- **Búsqueda:** coseno exacto en memoria (con ~80 chunks coincide con HNSW).
- **Reproducible sin clave:** los vectores están en `embeddings_cache.json`; `make eval` no llama a
  Gemini si la caché está completa.

## Resultados con embeddings reales

| Estrategia | recall@1 | recall@3 | recall@6 | MRR |
|---|---|---|---|---|
| B0 · ventanas fijas (800, solape 15 %) | 0,42 | 1,00 | 1,00 | 0,71 |
| B1 · estructural (cláusula + tablas) | 0,50 | 1,00 | 1,00 | 0,74 |
| **B2 · estructural + cabecera de contexto** | **0,92** | 0,92 | 1,00 | **0,94** |

**Decisión:** el sistema usa **B2** (D2 confirmada).

- Las tres estrategias encuentran la evidencia dentro del top 6: con un corpus tan pequeño,
  recall@6 se satura. La diferencia está en **la posición**: B2 pone la evidencia la primera en
  11 de 12 preguntas, frente a 5 y 6 de B0 y B1.
- La cabecera (transportista · contrato · sección) ayuda porque el texto de una cláusula no nombra
  al transportista ni a su sección: «6.1 El plazo de reclamación…» es casi igual en todos los
  contratos.
- La paráfrasis q11 («¿cuánto tiempo tengo para quejarme si la carga llega rota?») queda primera
  con B2: la búsqueda es semántica, no léxica.
- **Caso en contra:** q07 (fila de la tabla de Vientos del Sur) queda 4.ª con B2 y 1.ª con B0. Los
  bloques de tabla comparten cabecera y sección, así que la cabecera de contexto no los distingue.
- B0 frente a B1 mezcla dos cambios (segmentación y tratamiento de tablas); no se separan.

## Umbral de relevancia [R11, D8]

Puntuación del mejor resultado con B2, separando si la pregunta **nombra un transportista**:

| Grupo | Con respuesta | Sin respuesta |
|---|---|---|
| Nombra un transportista | 0,706 · 0,723 · 0,776 · 0,777 · 0,793 · 0,793 · 0,794 · 0,796 · 0,827 · 0,851 · 0,864 | 0,666 (u02) · 0,683 (u03) |
| General o comparativa | 0,670 (q09) · 0,706 (q10) | 0,599 (u01) |

Con **un único umbral** no hay separación: u03 («¿director general de Transportes Cóndor
Andino?») puntúa 0,683 solo por repetir el nombre, que también está en la cabecera de B2, y
q09 («¿qué transportista no acepta mercancías de clase 7?») puntúa 0,670 porque no nombra a
ninguno. La regla «no inventar» daba 0,69 y perdía q09 y las preguntas comparativas
(«¿quién entrega más rápido?» puntúa 0,680).

**Decisión: dos umbrales**, uno por grupo, ambos con la regla «no inventar». Cada grupo se separa
perfectamente: **0,70** si la pregunta nombra un transportista y **0,63** si es general.
Ninguna pregunta sin respuesta pasa la capa 1 y ninguna con respuesta se pierde.

El criterio es si el **texto de la pregunta** nombra a un transportista (así se midió), no si
hay filtro: con el transportista elegido en el desplegable y sin nombrarlo, la puntuación se
comporta como la de una pregunta general.

| Proveedor | Con transportista | General | Motivo |
|---|---|---|---|
| `gemini` | **0,70** | **0,63** | Calibrados con la regla «no inventar» por grupo |
| `fake` (demo sin clave) | **0,25** | **0,25** | Permisivo a propósito: el FakeLLM es extractivo y no puede inventar |

`RELEVANCE_THRESHOLD` fija el mismo valor para los dos. **Riesgo:** calibrado con 15
preguntas; con preguntas reales habría que recalibrar.

Aunque una pregunta sin respuesta superara el umbral, quedan dos capas: el LLM debe responder
`SIN_EVIDENCIA` y se descartan las respuestas sin citas válidas.

## Proveedor falso

El `FakeEmbedder` compara palabras, no significados: sus cifras **no miden calidad semántica** y no
se usan para decidir. En CI el eval se ejecuta con él solo para comprobar que el script funciona.
Con él, B2 no mejora: la cabecera añade el nombre del transportista y beneficia por igual a las
preguntas sin respuesta que lo mencionan (u03 puntúa 0,433).

## Limitaciones

- Corpus sintético y pequeño (5 documentos, ~80 chunks, 15 preguntas): las diferencias son
  orientativas y habría que repetir el eval con contratos y preguntas reales.
- El umbral depende del modelo de embeddings: cambiar de modelo exige recalibrar.
- Las preguntas las escribió el mismo equipo que diseñó el chunking (riesgo de sesgo).
