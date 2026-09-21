# ALPR GT Pack v1 — companion O i portable layout GT

Rozszerzenie 0022 nie zmienia identyfikatora głównego schematu `alpr.gt.pack.v1`.
Dodaje dwa kompatybilne elementy:

1. **Powiązanie GT Pack z zasobem O** — w projekcie jest zapisywane w
   `artifact_registry.json` pod `image_source.companions`. Źródłowe packi są
   kopiowane do `_campaign_state/ground_truth/imported/` i używane read-only.
2. **Portable layout GT** — rewizje `single_row` / `two_row` są przechowywane
   osobno od tekstowego GT w katalogu `layout_revisions/` jako
   `alpr.gt.layout-revision.v1`.

Layout ma własny DAG rewizji (`layout_revision_ids`, `layout_heads`) i takie
same zasady merge jak tekst GT: równoległe identyczne wartości są semantycznie
zgodne, a `single_row` kontra `two_row` pozostaje jawnym konfliktem zamiast
last-write-wins.

Discovery companionów jest celowo nierekurencyjne: po wybraniu katalogu O
program sprawdza tylko jego bezpośrednie podkatalogi `*.alprgt/manifest.json`.
`current_work.alprgt` jest traktowany jako domyślny pack roboczy free mode i nie
jest automatycznie montowany jako source.

Z2 otwierając obraz wykonuje kolejno:

1. dopasowanie obrazu po SHA-256,
2. hydration brakujących `Detection(label="plate")` z geometrii GT Pack,
3. rebind istniejących polygonów po `plate_annotation_id` lub exact geometry,
4. restore tekstu GT i layout GT,
5. zapis nowych zmian do working packa z outboxem na wypadek błędu I/O.
