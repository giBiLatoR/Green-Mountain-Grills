# Per-model overlay images

Drop a **transparent PNG named `<model_id>.png`** in this folder and the
GMG smoker dashboard strategy uses it automatically (no code edit) — falling
back to `../smoker-generic.svg` when no matching file is present.

`model_id` → model (from the integration's `MODEL_NAMES` table):

| id | model | id | model |
|----|-------|----|-------|
| 0 | Davy Crockett | 8 | Trek Prime 2.0 |
| 1 | Trek | 9 | Ledge Prime 2.0 |
| 2 | Daniel Boone | 10 | Peak Prime 2.0 |
| 3 | Jim Bowie | 11 | Daniel Boone Prime+ |
| 4 | Ledge | 12 | Jim Bowie Prime+ |
| 5 | Peak | 13 | Daniel Boone Prime 2.0 |
| 6 | Ledge Prime+ | 14 | Jim Bowie Prime 2.0 |
| 7 | Peak Prime+ | 15 | Trek Prime+ |

Example: a Jim Bowie → `3.png`.

> No product photos ship here. GMG's marketing images are copyrighted; supply
> your own front-on photos with the background cut out (e.g. via a background
> remover), sized ~400×240, saved as a transparent PNG.
