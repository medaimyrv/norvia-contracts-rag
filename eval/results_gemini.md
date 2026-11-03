## Proveedor `gemini` · modelo `gemini/gemini-embedding-001`

Corpus: PDFs `seed=true` de `samples/` · solo versiones vigentes · k=6 · filtro de transportista con `resolve_carrier`.

| Estrategia | recall@1 | recall@3 | recall@6 | MRR | umbral único | umbral con transportista | umbral general | respondibles rechazadas (2 umbrales) |
|---|---|---|---|---|---|---|---|---|
| B0 ('fixed', False) | 0.42 | 1.00 | 1.00 | 0.71 | 0.67 | 0.67 | 0.64 | 3 |
| B1 ('clause', False) | 0.50 | 1.00 | 1.00 | 0.74 | 0.69 | 0.69 | 0.67 | 2 |
| B2 ('clause', True) | 0.92 | 0.92 | 1.00 | 0.94 | 0.69 | 0.70 | 0.63 | 0 |

Rango del primer resultado relevante por pregunta (— = no está en el top-k):

| Pregunta | filtro | B0 | B1 | B2 | top score (B2) |
|---|---|---|---|---|---|
| q01 | Transportes Cóndor Andino | 2 | 1 | 1 | 0.864 |
| q02 | Rápido Austral Logística | 2 | 2 | 1 | 0.827 |
| q03 | Mareas del Pacífico Cargo | 2 | 2 | 1 | 0.723 |
| q04 | Transportes Cóndor Andino | 2 | 1 | 1 | 0.776 |
| q05 | Rápido Austral Logística | 2 | 2 | 1 | 0.777 |
| q06 | Mareas del Pacífico Cargo | 1 | 1 | 1 | 0.793 |
| q07 | Vientos del Sur Express | 1 | 3 | 4 | 0.794 |
| q08 | Vientos del Sur Express | 1 | 2 | 1 | 0.793 |
| q09 | — | 1 | 1 | 1 | 0.670 |
| q10 | — | 1 | 1 | 1 | 0.706 |
| q11 | Transportes Cóndor Andino | 2 | 2 | 1 | 0.796 |
| q12 | Vientos del Sur Express | 2 | 1 | 1 | 0.851 |
| u01 | — | sin resp. | sin resp. | sin resp. | 0.599 |
| u02 | Rápido Austral Logística | sin resp. | sin resp. | sin resp. | 0.666 |
| u03 | Transportes Cóndor Andino | sin resp. | sin resp. | sin resp. | 0.683 |
