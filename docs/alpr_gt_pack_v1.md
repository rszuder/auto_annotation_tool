# ALPR GT Pack v1 — specyfikacja interoperacyjna

## 1. Cel

`ALPR GT Pack v1` (`.alprgt`) jest przenośnym formatem ground truth dla tablic
rejestracyjnych. Format jest niezależny od:

- projektu,
- runu anotacji,
- ścieżki pliku,
- nazwy pliku,
- programu, który utworzył dane.

Ten sam pack ma być czytelny przez Desktop, Android i przyszłe narzędzia.

## 2. Struktura katalogu

```text
example.alprgt/
├── manifest.json
├── images/
├── plates/
├── geometries/
├── revisions/
├── conflicts/
└── blobs/
    └── images/
```

`blobs/images/` jest opcjonalne. Pack może być "thin" i zawierać wyłącznie
metadata.

## 3. Kodowanie

Wszystkie pliki JSON:

- UTF-8,
- bez BOM,
- nazwy pól są case-sensitive,
- stringi są Unicode,
- identyfikatory są ASCII,
- implementacja powinna tolerować dodatkowe nieznane pola zgodnie z zasadą
  forward compatibility.

## 4. Normalizacja numeru rejestracyjnego

Polityka:

```text
uppercase_alphanumeric.v1
```

Reguły:

1. uppercase,
2. usunięcie spacji i separatorów niealfanumerycznych,
3. brak zamian semantycznych typu `O ↔ 0`, `I ↔ 1`.

Przykład:

```text
" wi 905-pw " → "WI905PW"
```

## 5. Tożsamość obrazu

### 5.1. Exact identity

Kanoniczny `image_id`:

```text
image_id = "img-sha256-" + SHA256(exact source file bytes)
```

Tożsamość nie zależy od:

- nazwy,
- katalogu,
- projektu,
- daty pliku.

Rename i kopia 1:1 zachowują `image_id`.

Ponowny encoding JPG/PNG daje nowe `image_id`, nawet jeżeli obraz wygląda tak
samo.

### 5.2. Recovery fingerprints

Rekord obrazu może zawierać:

```text
pixel_sha256s
perceptual_dhash64s
```

Są to wyłącznie fingerprinty pomocnicze.

Nie wolno na ich podstawie automatycznie scalić GT dwóch różnych `image_id`.
Mogą tworzyć kandydat do reconciliation.

## 6. Rekord obrazu

Schema:

```text
alpr.gt.image.v1
```

Minimalne pola:

```json
{
  "schema": "alpr.gt.image.v1",
  "image_id": "img-sha256-...",
  "source_file_sha256": "...",
  "width": 1920,
  "height": 1080,
  "aliases": [],
  "plate_ids": []
}
```

`aliases` są opisowe. Nie uczestniczą w tożsamości.

## 7. Tożsamość tablicy

Schema:

```text
alpr.gt.plate.v1
```

`plate_id` jest trwałym UUID/ID logicznym odpowiadającym
`plate_annotation_id` w Z2.

Nie wolno wyliczać `plate_id` z geometrii.

Zmiana polygonu tworzy rewizję geometrii, nie nową tablicę.

Przykład:

```text
plate-ann-550e8400-e29b-41d4-a716-446655440000
```

## 8. Rekord tablicy

Przykład:

```json
{
  "schema": "alpr.gt.plate.v1",
  "plate_id": "plate-ann-...",
  "image_id": "img-sha256-...",
  "geometry_revision_ids": [],
  "geometry_heads": [],
  "revision_ids": [],
  "revision_heads": [],
  "legacy_ids": []
}
```

`*_ids` przechowują pełną historię.

`*_heads` są odbudowywalnym cache aktualnych liści DAG i po merge muszą zostać
przeliczone z relacji `parents`.

## 9. Geometria

Schema:

```text
alpr.gt.geometry.v1
```

Typ v1:

```text
polygon4-normalized
```

Współrzędne:

```text
x_normalized = x_pixels / image_width
y_normalized = y_pixels / image_height
```

Zakres:

```text
0.0 ≤ x,y ≤ 1.0
```

Do content hash współrzędne są zaokrąglane do 8 miejsc po przecinku.

Rewizja geometrii jest immutable i zawiera:

```text
geometry_id
plate_id
type
points
parents
```

`geometry_id` jest content-addressed:

```text
geom-sha256-<SHA256(canonical core JSON)>
```

## 10. Rewizje GT

Schema:

```text
alpr.gt.revision.v1
```

Rewizje są immutable.

Obsługiwane operacje:

```text
set
clear
```

### SET

```json
{
  "operation": "set",
  "value": "WI905PW"
}
```

### CLEAR

```json
{
  "operation": "clear",
  "value": null
}
```

`clear` oznacza świadome usunięcie aktywnego GT, ale nie usuwa historii.

Rewizja zawiera:

```text
revision_id
plate_id
operation
value
normalization_policy
parents
source
observed_by
```

`observed_by` nie uczestniczy w content hash i może być łączone przy merge.

`revision_id`:

```text
rev-sha256-<SHA256(canonical core JSON)>
```

## 11. Canonical JSON dla content IDs

Content hash musi być liczony na JSON:

- UTF-8,
- `sort_keys = true`,
- brak whitespace pomiędzy separatorami:
  - `,`
  - `:`,
- `ensure_ascii = false`.

Pseudokod:

```text
UTF8(JSON(value, sortKeys=true, separators=(",", ":"), ensureAscii=false))
```

Content IDs nie obejmują pól opisowych, jeżeli specyfikacja danego rekordu
wyraźnie wskazuje, że nie należą do core.

## 12. Graf rewizji

Pole:

```text
parents
```

tworzy DAG.

Przykład:

```text
rev1
  ↓
rev2
  ↓
rev3
```

Aktualna głowa:

```text
rev3
```

Po merge nie wolno wykonywać zwykłej sumy `revision_heads`.

Heads są:

```text
wszystkie revision_ids
MINUS
wszystkie revision_ids występujące jako parent innej rewizji tej tablicy
```

Ta sama reguła obowiązuje dla geometrii.

Cykl jest błędem integralności.

## 13. Rozwiązanie aktywnego GT

### Brak rewizji

```text
resolved = false
conflict = false
reason = missing_ground_truth
```

### Jedna semantyczna głowa SET

```text
resolved = true
has_ground_truth = true
text = normalized value
```

### Jedna semantyczna głowa CLEAR

```text
resolved = true
has_ground_truth = false
operation = clear
reason = cleared
```

### Kilka głów o tym samym stanie

Przykład:

```text
branch A → SET WI905PW
branch B → SET WI905PW
```

wynik:

```text
resolved = true
conflict = false
text = WI905PW
```

Rewizje pozostają zachowane.

### Różne stany

Przykład:

```text
branch A → SET WI905PW
branch B → SET WI905PX
```

lub:

```text
branch A → SET WI905PW
branch B → CLEAR
```

wynik:

```text
resolved = false
conflict = true
```

Nie wolno wybierać zwycięzcy na podstawie daty.

## 14. Merge packów

Wymagane własności semantyczne:

```text
merge(A,A) = A
merge(A,B) = merge(B,A)
merge(merge(A,B),C) ≈ merge(A,merge(B,C))
```

Merge:

1. łączy immutable geometries,
2. łączy immutable revisions,
3. łączy plate records,
4. łączy image records,
5. scala provenance,
6. przelicza heads,
7. zachowuje konflikty,
8. nie wykonuje last-write-wins.

## 15. Integrity conflict

Jeżeli:

```text
ten sam content-addressed ID
```

ma:

```text
inną core treść
```

jest to błąd integralności.

Implementacja nie może cicho nadpisać rekordu.

## 16. Reconciliation różnych plate_id

Dwa programy mogą niezależnie utworzyć:

```text
plate P1
plate P77
```

dla tej samej fizycznej tablicy.

Samo podobieństwo geometrii nie zmienia automatycznie ich tożsamości.

Program może tworzyć:

```text
reconciliation candidate
```

na podstawie:

- same `image_id`,
- IoU,
- dystansu środków,
- podobieństwa rozmiaru,
- opcjonalnie zgodności GT.

W v1 automatyczny alias różnych `plate_id` nie jest wymagany.

## 17. Conflict records

Schema:

```text
alpr.gt.conflict.v1
```

Conflict record służy do zapisu błędów integralności/merge, których nie można
bezpiecznie rozwiązać.

Semantyczny konflikt dwóch legalnych branchy GT nie wymaga utraty żadnej
rewizji i jest przede wszystkim reprezentowany przez kilka headów tablicy.

## 18. Blobs

Opcjonalny obraz w packu:

```text
blobs/images/<source_file_sha256>
```

Nazwa blobu jest SHA-256 exact file bytes.

Pack bez blobów jest prawidłowy.

## 19. Manifest

Schema:

```text
alpr.gt.pack.v1
```

Manifest jest indeksem/cache.

Nie jest jedynym źródłem prawdy.

Musi dać się odbudować przez skan rekordów.

Przykład:

```json
{
  "schema": "alpr.gt.pack.v1",
  "version": 1,
  "normalization_policy": "uppercase_alphanumeric.v1",
  "producers": ["auto_annotation_tool"],
  "record_counts": {
    "images": 1,
    "plates": 1,
    "geometries": 1,
    "revisions": 1,
    "conflicts": 0,
    "blobs": 0
  }
}
```

## 20. Atomic write i locking

Mutacje powinny być:

```text
temporary file → flush/fsync → atomic replace
```

Pack powinien mieć pojedynczego writera.

Desktop v1 używa:

```text
.pack.lock
```

Inne implementacje mogą użyć równoważnego mechanizmu, ale nie mogą wykonywać
równoległych niezabezpieczonych mutacji tego samego packa.

## 21. Forward compatibility

Parser v1:

- musi odrzucić nieznany główny `schema` packa,
- może tolerować dodatkowe pola w znanych record schemas,
- nie powinien zmieniać nieznanych pól przy read-only operacjach,
- przy merge powinien zachować znane dane bez silent loss.

## 22. Związek z Z2

Z2 używa:

```text
plate_annotation_id == plate_id
```

Z2 snapshot `annotations.xml` może zawierać:

```text
plate_annotation_id
ground_truth_text
ground_truth_source
```

ale ALPR GT Pack jest trwałym magazynem historii.

`annotations.xml` jest snapshotem runu.

## 23. Związek z PZ1

PZ1 docelowo przechowuje:

```text
source_image_id
source_annotation_id
source_geometry_revision_id
source_gt_revision_id
source_gt_hash
```

Zmiana samego GT musi być wykrywalna bez zmiany polygonu.

## 24. Związek z PZ2

RAW inference nie może korzystać z GT.

GT Pack jest źródłem dla:

```text
VALIDATION
```

a nie:

```text
RAW DETECTION
```

## 25. Fixtures interoperacyjne

Katalog:

```text
tests/fixtures/alpr_gt_pack_v1/
```

zawiera przypadki:

```text
single_plate.alprgt
multi_plate.alprgt
gt_history.alprgt
clear_gt.alprgt
gt_conflict.alprgt
geometry_conflict.alprgt
```

Oraz:

```text
tests/fixtures/alpr_gt_pack_v1_sources/
```

z deterministycznymi plikami źródłowymi PPM.

Każdy przyszły parser Desktop/Android powinien przejść te same fixtures.

## 26. Minimalne wymagania implementacji Android

Android musi umieć co najmniej:

1. SHA-256 exact source bytes,
2. odczyt manifestu,
3. odczyt images/plates/geometries/revisions,
4. canonical JSON dla content IDs,
5. normalization `uppercase_alphanumeric.v1`,
6. graph head resolution,
7. SET/CLEAR resolution,
8. wykrywanie conflict heads,
9. walidację content IDs,
10. eksport packa czytelnego przez Desktop.

## 27. Zasada bezpieczeństwa

Jeżeli implementacja nie jest pewna, czy dwa rekordy oznaczają ten sam obraz
lub tę samą tablicę:

```text
NIE scala automatycznie.
```

Woli zachować dwa rekordy i zgłosić reconciliation/conflict niż połączyć
ground truth z niewłaściwą tablicą.
