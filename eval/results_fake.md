## Proveedor `fake` · modelo `fake (léxico)`

Corpus: PDFs `seed=true` de `samples/` · solo versiones vigentes · k=6 · filtro de transportista con `resolve_carrier`.

| Estrategia | recall@1 | recall@3 | recall@6 | MRR | umbral único | umbral con transportista | umbral general | respondibles rechazadas (2 umbrales) |
|---|---|---|---|---|---|---|---|---|
| B0 ('fixed', False) | 0.58 | 0.92 | 1.00 | 0.76 | 0.19 | 0.19 | 0.17 | 4 |
| B1 ('clause', False) | 0.58 | 0.92 | 1.00 | 0.73 | 0.32 | 0.32 | 0.22 | 5 |
| B2 ('clause', True) | 0.58 | 0.75 | 1.00 | 0.73 | 0.44 | 0.44 | 0.19 | 5 |

Rango del primer resultado relevante por pregunta (— = no está en el top-k):

| Pregunta | filtro | B0 | B1 | B2 | top score (B2) |
|---|---|---|---|---|---|
| q01 | Transportes Cóndor Andino | 1 | 1 | 1 | 0.489 |
| q02 | Rápido Austral Logística | 2 | 3 | 2 | 0.373 |
| q03 | Mareas del Pacífico Cargo | 1 | 1 | 1 | 0.489 |
| q04 | Transportes Cóndor Andino | 1 | 2 | 2 | 0.289 |
| q05 | Rápido Austral Logística | 3 | 3 | 4 | 0.373 |
| q06 | Mareas del Pacífico Cargo | 1 | 1 | 1 | 0.683 |
| q07 | Vientos del Sur Express | 2 | 3 | 4 | 0.474 |
| q08 | Vientos del Sur Express | 1 | 1 | 1 | 0.366 |
| q09 | — | 1 | 1 | 1 | 0.364 |
| q10 | — | 1 | 1 | 1 | 0.281 |
| q11 | Transportes Cóndor Andino | 2 | 4 | 4 | 0.250 |
| q12 | Vientos del Sur Express | 4 | 1 | 1 | 0.471 |
| u01 | — | sin resp. | sin resp. | sin resp. | 0.107 |
| u02 | Rápido Austral Logística | sin resp. | sin resp. | sin resp. | 0.298 |
| u03 | Transportes Cóndor Andino | sin resp. | sin resp. | sin resp. | 0.433 |
