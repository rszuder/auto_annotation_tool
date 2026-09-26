# Plan implementacji przenośnego AZ opartego o SHA i SQLite

**Projekt:** `rszuder/auto_annotation_tool`  
**Obszar:** Z3/PZ1–PZ3, graf kampanii T01/T02, tryb swobodny, `alpr_registry.sqlite3`  
**Cel nadrzędny:** umożliwić bezpieczne zatrzymywanie, odzyskiwanie i przenoszenie pracy nad anotacjami znaków (AZ) między iteracjami, projektami i trybem swobodnym bez ponownego boxowania tych samych cropów oraz bez mnożenia zbędnych CTA w UI.


## 0. Stan wdrożenia po AZ000 — 2026-09-24

**Gałąź robocza:** `funkcja/az-crop-registry`

AZ000 został wykonany i zweryfikowany na rzeczywistym `Workspace/_registry/alpr_registry.sqlite3`.

### Potwierdzone fakty

1. Warstwa SQLite pochodzi z gałęzi `feature/evaluation-registry`, ale pełny merge tej gałęzi jest niedopuszczalny:
   - gałęzie są rozbieżne,
   - `feature/evaluation-registry` zawiera duży, niezwiązany zakres PZ3/Z4/eksperymentów.
2. Do `funkcja/az-crop-registry` przeniesiono minimalny fundament:
   - `auto_annotation_tool/registry/database.py`,
   - `auto_annotation_tool/registry/schema.py`,
   - `auto_annotation_tool/registry/migrations.py`,
   - minimalny `auto_annotation_tool/registry/__init__.py`,
   - testy schematu i migracji.
3. Kod i istniejąca baza są zgodne:
   - `SCHEMA_VERSION = 5`,
   - `PRAGMA user_version = 5`,
   - `RegistryDatabase.initialize()` pozostawia wersję 5,
   - `PRAGMA integrity_check = ok`.
4. Audyt `image_artifacts` wykazał:
   - `33 186` rekordów,
   - `11 077` różnych SHA,
   - `1 498` grup SHA występujących wielokrotnie,
   - rodzaje: `dataset_image`, `derived_image`, `evaluation_track_image`,
   - brak zarejestrowanych cropów PZ1/Z3.
5. Wniosek:
   - `image_artifacts` reprezentuje **fizyczne wystąpienia artefaktów**,
   - `image_artifacts.sha256` **nie może stać się UNIQUE**,
   - logiczna tożsamość cropa musi być osobną warstwą,
   - jeden logiczny crop może mieć wiele rekordów `image_artifacts`.

### Decyzja po AZ000

Docelowy model rozdziela:

```text
plate entity / source lineage
        ↓
logical plate crop identity
        ↓
plate_crops
        ↓
crop_artifacts ── 1:N ── image_artifacts
        ↓
project / iteration membership
        ↓
AZ revisions
```

AZ001 zaczynamy od addytywnej migracji v5 → v6. Nie zmieniamy ani nie przebudowujemy istniejących tabel.


## 0A. Aktualny stan wykonania — 2026-09-27

```text
AZ000  DONE
AZ001  DONE
AZ002  DONE
AZ003  DONE END-TO-END
AZ004  DONE END-TO-END
AZ005  DONE END-TO-END
AZ006  DONE END-TO-END
AZ007A DONE
AZ007B1 DONE
AZ007B2 DONE
AZ007C1 DONE
AZ007C2 DONE
AZ007C3 IMPLEMENTATION READY / LIVE SMOKE PENDING
AZ008  PLANNED
AZ009  PLANNED
AZ010  PLANNED
```

Dodatkowo zakończono przygotowawcze i naprawcze UX:

```text
Z2HIST DONE
Z3SRC  DONE

T01 resource-state path semantics FIXED
T03 manual Z2 entry CTA FIXED
PZ2 review flow V3 IMPLEMENTED
PZ2 fullscreen number HUD IMPLEMENTED
1R/2R control: pan-follow + vertical right-side layout IMPLEMENTED
fullscreen panel tabs: lightweight vertical tabs IMPLEMENTED
right status copy: dynamic wrap IMPLEMENTED
```

Najbliższy cel nadal jest podporządkowany doświadczeniom do pracy inżynierskiej: **domknąć realny smoke test AZ007C3 SOURCE → TARGET, a następnie przejść do doświadczeń bez ponownego boxowania tych samych logical cropów**.

Stan po AZ007C2 i implementacji C3:

```text
AZ007B2
→ istniejąca akcja Import przy AZ jest podłączona
→ source-project browser korzysta z list_project_az_import_sources(...)
→ import korzysta z import_project_az_bindings(...)
→ exact crop_id only
→ target binding = imported_pending_review
→ refresh istniejącego resource modal
→ bez nowej bramki i bez nowej ścieżki PZ2

AZ007C1/C2
→ T01/T02/graph semantics zabezpieczone regresjami
→ pending AZ nie daje fałszywego zatwierdzenia
→ partial/conflict pozostają jawne
→ graph fallback jest registry-backed, nie placeholderowy
→ istniejące O/AT/MT/MZ zachowują kontrakt

AZ007C3
→ kod i regresje lokalne są gotowe
→ trwa kontrolowany real UI smoke test
→ SOURCE: AZ007C3_SOURCE
→ TARGET ma odtworzyć dokładnie te same crop_id bez ręcznego przerysowania AT
```

Pakietowy import/eksport AZ pozostaje późniejszym etapem. AZ007 domyka najpierw wewnętrzny registry, graf kampanii i realny workflow PZ2.

---

## 1. Decyzja architektoniczna w skrócie

AZ przestaje być traktowane wyłącznie jako wynik konkretnego runu PZ2/PZ3. Każdy crop tablicy otrzymuje **stabilną tożsamość SHA**, a SQLite staje się źródłem informacji:

- czy taki crop był już wcześniej widziany,
- czy należy już do puli danego projektu,
- czy ma istniejące AZ,
- z której rewizji AZ można odzyskać boxy i znaki,
- w których iteracjach był używany,
- skąd pochodzi i jak został utworzony.

Najważniejsza zasada UX:

> **AZ jest nowym typem zasobu, a nie nową ścieżką interfejsu.**

Dlatego:

- w kampanii import AZ podpinamy pod już istniejące **„Import zasobów”** przy T01/T02 i istniejący zasób `char_run`,
- w trybie swobodnym nie dodajemy trzeciego kafla ani osobnego stałego CTA w PZ2; rozszerzamy istniejące wejście zewnętrzne,
- między iteracjami tego samego projektu nie ma ręcznego importu w ogóle — odzyskiwanie AZ odbywa się automatycznie po SHA,
- PZ2 pozostaje miejscem pracy i kontroli,
- PZ3 pozostaje miejscem przygotowania finalnego materiału/datasetu; nie zamieniamy go w menedżer zasobów.

---

## 2. Stan obecny — punkty, na których opieramy wdrożenie

### 2.1. SQLite już istnieje

W `Workspace/_registry/alpr_registry.sqlite3` istnieją m.in. tabele:

- `projects`,
- `source_images`,
- `image_artifacts`,
- `datasets`,
- `dataset_members`,
- `models`,
- `training_runs`,
- tabele eksperymentów i evaluation tracks.

Najważniejsze dla AZ są obecnie:

```text
source_images
- source_image_id
- canonical_sha256 (unikalny, jeśli niepusty)

image_artifacts
- artifact_id
- source_image_id
- relative_path / external_path
- sha256
- kind
- derived_from_artifact_id
- width / height
- created_at
```

`image_artifacts.sha256` ma indeks, ale **nie jest UNIQUE**. Nie wolno bez audytu zmieniać go na unikalny — historyczne rekordy mogą zawierać kilka artefaktów o identycznej zawartości.

### 2.2. Graf kampanii już zna AZ

W `campaign_resource_catalog.py` zasób istnieje jako:

```text
key = char_run
code = AZ
label = AZ - anotacje znaków
```

W `campaign_step1_assets.py` jest już wiersz `char_run`, lecz jego stan jest obecnie placeholderem:

```text
Planowane | import AZ nie jest jeszcze dostępny w zasobach bramki.
```

To znaczy, że nie projektujemy nowego panelu. Podłączamy backend do istniejącego modelu zasobów.

### 2.3. Tryb swobodny ma już istniejące wejścia

Z3/PZ1 ma obecnie m.in.:

- `Kontynuuj na runie anotacji`,
- `Wskaż anotacje do wyodrębnienia`,
- osobne wejście `Akwizycja Androida`.

Nie dokładamy trzeciego kafla „Importuj AZ”. Zamiast tego drugie wejście zostanie uogólnione na zewnętrzne źródło `AT/AZ`.

### 2.4. PZ2 nadal pracuje na `preview_dir + images/ + metadata.json`

Nie należy teraz przebudowywać całego edytora PZ2 na bezpośrednią pracę na rekordach SQL. To byłoby zbyt ryzykowne przed doświadczeniami do pracy inżynierskiej.

SQLite będzie warstwą trwałej tożsamości, deduplikacji i przenoszenia, natomiast istniejący format roboczy PZ2 pozostanie adapterem edycyjnym.

---

# 3. Docelowy model pojęciowy

```text
                 alpr_registry.sqlite3
                         │
             globalna tożsamość cropów
                         │
               crop_identity_sha256
                         │
          ┌──────────────┴──────────────┐
          │                             │
     PROJECT A                      PROJECT B
          │                             │
   project_crop_members          project_crop_members
          │                             │
   IT1 / IT2 / IT3                   IT1 / IT2
          │                             │
          └──────────── AZ ─────────────┘
                         │
                    rewizje AZ
                         │
                   boxy + znaki
```

Tryb swobodny korzysta z tej samej globalnej tożsamości cropów i może tworzyć/odczytywać rewizje AZ, ale **nie przypisuje ich po cichu do żadnego projektu**.

---

# 4. Tożsamość cropa — polityka SHA

## 4.1. Dlaczego samo SHA pliku JPG nie wystarcza

Obecne `image_artifacts.sha256` jest hashem fizycznego pliku. Ten sam logiczny crop może zostać ponownie zapisany i otrzymać inne bajty JPEG mimo identycznego źródła i geometrii.

Dlatego rozdzielamy:

1. **artifact SHA** — SHA fizycznego pliku; pozostaje w `image_artifacts.sha256`,
2. **crop identity SHA** — stabilna tożsamość logicznego cropa używana do odzyskiwania AZ.

## 4.2. Preferowany `crop_identity_sha256`

Dla cropów wygenerowanych przez aplikację tożsamość wynika z lineage oraz z kontraktu generowania cropa, a nie z nazwy pliku JPG.

### Kontrakt `alpr.crop_identity.v1`

Preferowany payload:

```json
{
  "schema": "alpr.crop_identity.v1",
  "source_image_id": "img-sha256:...",
  "source_annotation_id": "plate-ann-...",
  "source_geometry_hash": "...",
  "crop_contract": {
    "generator": "PlateGenerator",
    "contract_version": "pz1_crop.v1",
    "rectify": true,
    "do_deskew": false,
    "enhance_contrast": false,
    "interpolation": "lanczos4",
    "output_width": 256,
    "output_height": 64
  }
}
```

Dla tablicy dwurzędowej:

```text
output_width = 256
output_height = 128
```

`interpolation` jest częścią identity, ponieważ w PZ1 jest ustawieniem runtime i może się zmieniać.

### Dlaczego `source_annotation_id`

Obecny PZ1 już przenosi `plate_annotation_id` z Z2 jako `source_annotation_id`. Jest to trwała tożsamość konkretnej tablicy w ramach źródła i należy ją zachować w lineage.

Nie wystarcza jednak sama:

```text
source_image_id + source_annotation_id
```

bo zmiana geometrii tablicy może zmienić piksele cropa oraz współrzędne znaków. Dlatego `source_geometry_hash` / geometry revision jest częścią crop identity.

### Reguła po zmianie polygonu

```text
ten sam plate_id
+ nowa geometria
= nowy crop identity
```

To jest zamierzone. AZ dla starego cropa nie może zostać automatycznie nałożone na geometrycznie inny crop, bo boxy znaków mogą przestać odpowiadać pikselom.

Powiązanie „to nadal ta sama fizyczna tablica” pozostaje dostępne przez:

```text
source_image_id
source_annotation_id
```

i może później służyć do kontrolowanej migracji/reconciliation, ale nie do cichego reuse AZ.

### Canonical JSON

`crop_identity_sha256`:

```text
SHA256(canonical_json(payload))
```

Zasady:

- UTF-8,
- `sort_keys=True`,
- separators bez zbędnych whitespace,
- jawna wersja schematu,
- jawna wersja crop contract,
- brak lokalnych ścieżek i nazw plików,
- brak timestampów,
- wartości bool/int/string w jednoznacznej postaci.

Jeśli w IT1 i IT3 występują:

- ten sam `source_image_id`,
- ten sam `source_annotation_id`,
- ten sam `source_geometry_hash`,
- ten sam kontrakt cropowania,

to `crop_identity_sha256` musi być identyczny.

## 4.3. Fallback dla cropów zewnętrznych

Jeśli crop przychodzi w pakiecie AZ bez pełnego lineage:

```text
identity_mode = pixels_v1
```

Hash fallback:

```text
SHA256(
  "alpr.crop_pixels.v1\0" +
  width + height + channels +
  decoded_RGB_bytes
)
```

Pakiet powinien jednak zachowywać oryginalny `crop_identity_sha256`, jeżeli powstał on wcześniej w aplikacji. Wtedy przy kolejnym imporcie używamy deklarowanej, zweryfikowanej tożsamości zamiast generować nową.

## 4.4. Czego nie używamy jako klucza głównego

Nie używamy do automatycznego scalania:

- nazwy pliku,
- `plate_id` z konkretnego runu,
- kolejności na liście,
- pHash / perceptual hash.

pHash może w przyszłości służyć wyłącznie jako **narzędzie wyszukiwania kandydatów podobnych**, nigdy jako automatyczny dowód identyczności.

---

# 5. Zmiany w SQLite

## 5.1. Założenie

Nie zmieniamy semantyki istniejącego `image_artifacts`.

Po audycie AZ000 wiemy, że:

```text
image_artifacts = fizyczne wystąpienia plików/obrazów
plate_crops     = logiczna tożsamość cropa PZ1
```

To samo `image_artifacts.sha256` może występować wiele razy i jest to stan poprawny.

Migracja AZ001 jest **wyłącznie addytywna**.

## 5.2. Tabela `plate_crops`

```sql
CREATE TABLE plate_crops (
    crop_id TEXT PRIMARY KEY,
    identity_sha256 TEXT NOT NULL,
    identity_mode TEXT NOT NULL,
    identity_schema TEXT NOT NULL DEFAULT 'alpr.crop_identity.v1',
    source_image_id TEXT,
    source_annotation_id TEXT,
    source_geometry_hash TEXT,
    crop_contract_sha256 TEXT,
    width INTEGER,
    height INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_image_id)
        REFERENCES source_images(source_image_id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE UNIQUE INDEX idx_plate_crops_identity
    ON plate_crops(identity_schema, identity_sha256);

CREATE INDEX idx_plate_crops_source_plate
    ON plate_crops(source_image_id, source_annotation_id);
```

`crop_id` jest stabilnym ID domenowym, np. `CROP-<UUID/ULID>`. Nie używamy SHA bezpośrednio jako FK.

## 5.3. Tabela `crop_artifacts`

Jeden logiczny crop może mieć wiele fizycznych wystąpień w katalogach/runach/datasetach.

```sql
CREATE TABLE crop_artifacts (
    crop_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT,
    last_seen_at TEXT,
    PRIMARY KEY(crop_id, artifact_id),
    FOREIGN KEY(crop_id)
        REFERENCES plate_crops(crop_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY(artifact_id)
        REFERENCES image_artifacts(artifact_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX idx_crop_artifacts_artifact
    ON crop_artifacts(artifact_id, crop_id);
```

Nie dodajemy `UNIQUE(artifact_id)` na tym etapie. Najpierw utrzymujemy model konserwatywny i walidujemy rzeczywiste przypadki.

## 5.4. Tabela `project_crop_members`

```sql
CREATE TABLE project_crop_members (
    project_id TEXT NOT NULL,
    crop_id TEXT NOT NULL,
    first_seen_iteration INTEGER,
    last_seen_iteration INTEGER,
    first_seen_at TEXT,
    last_seen_at TEXT,
    source_mode TEXT,
    PRIMARY KEY(project_id, crop_id),
    FOREIGN KEY(project_id)
        REFERENCES projects(project_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY(crop_id)
        REFERENCES plate_crops(crop_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE INDEX idx_project_crop_members_crop
    ON project_crop_members(crop_id, project_id);
```

## 5.5. Tabela `iteration_crop_members`

```sql
CREATE TABLE iteration_crop_members (
    project_id TEXT NOT NULL,
    iteration_num INTEGER NOT NULL,
    crop_id TEXT NOT NULL,
    artifact_id TEXT,
    source_image_id TEXT,
    source_plate_key TEXT,
    source_at_ref TEXT,
    first_seen_at TEXT,
    PRIMARY KEY(project_id, iteration_num, crop_id),
    FOREIGN KEY(project_id)
        REFERENCES projects(project_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY(crop_id)
        REFERENCES plate_crops(crop_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY(artifact_id)
        REFERENCES image_artifacts(artifact_id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY(source_image_id)
        REFERENCES source_images(source_image_id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE INDEX idx_iteration_crop_members_crop
    ON iteration_crop_members(crop_id, project_id, iteration_num);
```

## 5.6. Tabela `az_revisions`

```sql
CREATE TABLE az_revisions (
    az_revision_id TEXT PRIMARY KEY,
    crop_id TEXT NOT NULL,
    parent_revision_id TEXT,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_status TEXT,
    trust_state TEXT NOT NULL,
    origin_project_id TEXT,
    origin_iteration INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(crop_id)
        REFERENCES plate_crops(crop_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY(parent_revision_id)
        REFERENCES az_revisions(az_revision_id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY(origin_project_id)
        REFERENCES projects(project_id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE INDEX idx_az_revisions_crop
    ON az_revisions(crop_id, created_at);

CREATE UNIQUE INDEX idx_az_revisions_payload
    ON az_revisions(crop_id, payload_sha256);
```

## 5.7. Tabela `project_crop_az`

```sql
CREATE TABLE project_crop_az (
    project_id TEXT NOT NULL,
    crop_id TEXT NOT NULL,
    az_revision_id TEXT NOT NULL,
    effective_status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, crop_id),
    FOREIGN KEY(project_id)
        REFERENCES projects(project_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY(crop_id)
        REFERENCES plate_crops(crop_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY(az_revision_id)
        REFERENCES az_revisions(az_revision_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
```

## 5.8. Wersja schematu

Nie wprowadzamy osobnej tabeli `registry_schema_migrations`, ponieważ istniejąca warstwa registry już używa:

```text
PRAGMA user_version
SCHEMA_VERSION
MIGRATIONS
```

AZ001:

```text
SCHEMA_VERSION: 5 → 6
SCHEMA_V6_STATEMENTS
_migrate_to_v6()
MIGRATIONS[6]
```

## 5.9. Reguły AZ001

AZ001:

- nie modyfikuje żadnych rekordów v1–v5,
- nie wykonuje backfillu,
- nie skanuje Workspace,
- nie zmienia `image_artifacts.sha256`,
- nie dodaje `UNIQUE` do historycznych tabel,
- tworzy wyłącznie nowe tabele i indeksy,
- musi być idempotentna,
- musi przejść `PRAGMA foreign_key_check`,
- najpierw jest testowana na bazie tymczasowej oraz kopii bazy.

# 6. Co trafia do `payload_json` AZ

Nie zapisujemy całego stanu GUI.

Zapisujemy tylko dane trwałe i semantyczne:

```json
{
  "schema": "alpr.az_revision.v1",
  "crop_identity_sha256": "...",
  "characters": [
    {
      "character": "W",
      "bbox": [0.10, 0.20, 0.18, 0.80],
      "row": 0,
      "method": "local_manual",
      "source_kind": "local_manual",
      "confidence": 1.0
    }
  ],
  "layout": {
    "kind": "1R",
    "confirmed": true
  },
  "gold_state": {
    "approved": true,
    "excluded": false,
    "candidate": true
  },
  "status": "perfect",
  "expected_text": "WX12345",
  "provenance": {
    "modified_by": "human",
    "source": "pz2",
    "source_batch_id": "..."
  }
}
```

Usuwamy z canonical payload m.in.:

- aktualnie zaznaczony box,
- pozycję scrolla,
- aktywny zoom,
- hover,
- indeks listboxa,
- transient runtime cache,
- kolory renderowania,
- elementy wyłącznie prezentacyjne.

Przed obliczeniem `payload_sha256`:

- boxy sortujemy w stabilnej kolejności,
- liczby normalizujemy do ustalonej precyzji,
- JSON serializujemy canonicalnie.

---

# 7. Warstwa backendowa — proponowane moduły

Nazwy są propozycją; ważny jest podział odpowiedzialności.

## 7.1. `crop_identity.py`

Odpowiedzialność:

- budowanie `alpr.crop_identity.v1`,
- canonical JSON,
- liczenie `crop_identity_sha256`,
- fallback `pixels_v1`,
- weryfikacja deklarowanego SHA z pakietu.

API:

```python
build_crop_identity(...)
compute_crop_identity_sha256(...)
compute_pixel_fallback_sha256(...)
verify_crop_identity(...)
```

## 7.2. `az_registry.py`

Jedyna warstwa, która zna nowe tabele SQLite.

API wysokiego poziomu:

```python
register_crop(...)
find_crop_by_identity(...)
attach_crop_to_project(...)
mark_crop_seen_in_iteration(...)
get_project_crop_membership(...)

save_az_revision(...)
get_latest_project_az(...)
bind_project_az_revision(...)
list_project_az_candidates(...)
```

GUI nie powinno wykonywać surowych zapytań SQL.

## 7.3. `az_workset.py`

Adapter między SQLite a obecnym PZ2.

Odpowiedzialność:

- materializacja cropów do `preview_dir/images`,
- generowanie/uzupełnianie `metadata.json`,
- hydracja istniejącego AZ,
- synchronizacja `metadata.json -> az_revisions`,
- budowanie raportu: reused/new/conflict/skipped.

## 7.4. `az_package.py`

Obsługa przenośnego pakietu AZ:

```python
inspect_az_package(path)
validate_az_package(path)
export_az_package(...)
import_az_package(...)
```

Import nie powinien bezpośrednio znać Tkintera.

---

# 8. Integracja z PZ1 — moment rejestracji cropa

## 8.1. Gdzie faktycznie powstaje crop

Crop jest tworzony przez:

```text
auto_annotation_tool/character_recognition/plate_generator.py
```

`PlateGenerator.generate_from_annotations()`:

1. bierze źródłowy bbox/polygon,
2. opcjonalnie prostuje,
3. normalizuje rozmiar,
4. zapisuje JPG do `run_dir/images/`,
5. buduje `metadata.json`.

Aktualny kontrakt produkcyjny PZ1:

```text
rectify = True
do_deskew = False
enhance_contrast = False
interpolation = ustawienie PZ1
single-row = 256×64
two-row    = 256×128
```

Metadata już zawiera m.in.:

```text
source_image_id
source_file_sha256
source_bbox
source_polygon
source_annotation_id
source_geometry_hash
source_geometry_revision_id(s)
source_gt_revision_id(s)
```

Nie tworzymy równoległego mechanizmu lineage.

## 8.2. Rejestracja nie odbywa się per `cv2.imwrite`

Nie zapisujemy do SQLite w środku każdej operacji zapisu JPG.

Preferowany przepływ:

```text
PlateGenerator
  ↓
generuje cały run
  ↓
save_metadata()
  ↓
write source manifest
  ↓
register_pz1_preview_run(run_dir)
  ↓
jedna kontrolowana transakcja SQLite
```

## 8.3. `register_pz1_preview_run(run_dir)`

Dla każdego wpisu `metadata.json`:

1. znajdź `images/<plate_id>.jpg`,
2. odczytaj istniejące lineage,
3. zbuduj `crop_identity`,
4. policz `crop_identity_sha256`,
5. policz `file_sha256` fizycznego JPG,
6. zarejestruj fizyczny `image_artifact` z `kind='plate_crop'`,
7. znajdź lub utwórz `plate_crops`,
8. dodaj relację `crop_artifacts`,
9. w kampanii dodaj membership projektu i iteracji,
10. dopisz do roboczego metadata `crop_id`, SHA i `artifact_id`.

Minimalny rekord:

```json
{
  "crop_id": "CROP-...",
  "crop_identity_sha256": "...",
  "crop_identity_schema": "alpr.crop_identity.v1",
  "artifact_id": "ART-..."
}
```

## 8.4. Rejestracja `source_images`

`plate_crops.source_image_id` musi wskazywać rekord istniejący w `source_images`.

Jeżeli PZ1 ma `source_image_id`, ale registry nie ma jeszcze takiego `source_images`:

- wykonujemy bezpieczny upsert,
- wykorzystujemy `source_file_sha256` zgodnie z kontraktem registry,
- nie tworzymy drugiej tożsamości tego samego źródła.

## 8.5. Powtórne PZ1

Jeżeli IT2 wygeneruje ten sam `identity_schema + identity_sha256`:

- nie tworzymy nowego `plate_crops`,
- nowy fizyczny plik może dostać nowy `image_artifacts`,
- relacja trafia do `crop_artifacts`,
- aktualizujemy memberships,
- później hydratujemy istniejące AZ.

# 9. Automatyczne odzyskiwanie AZ między iteracjami

To jest najważniejszy scenariusz i powinien działać bez żadnego CTA.

## 9.1. Przepływ

```text
PZ1 IT2 tworzy crop
      ↓
crop_identity_sha256
      ↓
plate_crops
      ↓
project_crop_members
      ↓
project_crop_az
      ↓
AZ istnieje?
```

### Jeśli tak

Adapter uzupełnia nowy rekord `metadata.json` danymi z bieżącej rewizji AZ.

### Jeśli nie

Crop pozostaje nowy i trafia do zwykłej pracy PZ2.

## 9.2. Raport

Po materializacji PZ2 backend powinien zwrócić np.:

```json
{
  "total": 251,
  "reused": 184,
  "new": 67,
  "excluded_reused": 12,
  "ready_reused": 25,
  "ok_reused": 147,
  "conflicts": 0
}
```

UI może wykorzystać istniejące miejsce statusu/AS. Nie tworzymy osobnego dużego panelu.

## 9.3. Statusy w tym samym projekcie

Ponieważ to własna pula projektu:

- `N` pozostaje `N`,
- `OK` pozostaje `OK`,
- `ZATWIERDŹ` pozostaje gotowe do zatwierdzenia,
- `DO KOREKTY` pozostaje do korekty.

Nie ma powodu wymuszać ponownej akceptacji dla dokładnie tego samego cropa i tej samej własnej rewizji projektu.

---

# 10. Synchronizacja zmian z PZ2 do SQLite

## 10.1. Źródło prawdy podczas aktywnej edycji

Podczas otwartego PZ2 bieżącym roboczym źródłem prawdy nadal jest istniejące `metadata.json` + stan runtime.

SQLite dostaje trwałe checkpointy.

## 10.2. Kiedy zapisywać rewizję AZ

Natychmiastowy flush:

- `O` / zatwierdzenie OK,
- `N` / wykluczenie,
- cofnięcie N,
- jawne zapisanie pracy,
- opuszczenie PZ2,
- przełączenie projektu,
- eksport AZ.

Debounced sync:

- przesunięcie boxa,
- dodanie/usunięcie boxa,
- wpisanie/zmiana znaku,
- potwierdzenie layoutu.

Proponowany debounce: 250–500 ms po ostatniej zmianie, ale finalny parametr dobrać testem wydajnościowym.

## 10.3. Brak niepotrzebnych rewizji

Przed `INSERT az_revisions`:

1. canonicalizuj payload,
2. policz `payload_sha256`,
3. jeśli taki payload dla cropa już istnieje — nie twórz nowej rewizji,
4. tylko zaktualizuj binding, jeśli jest potrzebny.

---

# 11. Konflikty i zasada „nie niszczymy manuali”

## 11.1. Priorytet

Nigdy nie nadpisujemy po cichu lokalnej pracy manualnej importem.

### Macierz minimalna

| Stan docelowy | Import | Zachowanie |
|---|---|---|
| brak AZ | dowolne AZ | przyjmij |
| auto/untouched | manualne importowane | przyjmij jako kandydat do kontroli |
| manualne lokalne | identyczne payload SHA | no-op |
| manualne lokalne | inne manualne | konflikt, bez nadpisania |
| N lokalne | OK importowane | N wygrywa lokalnie, konflikt/informacja |
| OK lokalne | starsze/inne importowane | nie nadpisuj |
| AZ z tego samego projektu i ten sam crop | zapis z własnej puli | zwykłe wznowienie |

## 11.2. Import z innego projektu

Nie przenosimy automatycznie zaufania `OK` między projektami.

Przenosimy:

- boxy,
- znaki,
- layout,
- provenance,
- informację, że w źródle rekord był `OK`.

Ale efektywny status w projekcie docelowym:

- `N` może pozostać `N`,
- źródłowe `OK` → `ZATWIERDŹ` / `imported_pending_review`,
- `needs_fix` → `needs_fix`.

To pozwala zaoszczędzić boxowanie, ale zachowuje świadomą kontrolę przed dopuszczeniem do finalnego GOLD.

---

# 12. Kampania — T01/T02 i istniejący „Import zasobów”

## 12.1. Bez nowego CTA

Nie dodajemy:

- przycisku „Importuj AZ” do PZ2,
- osobnej karty AZ w Z3,
- nowej ścieżki grafu.

Podłączamy istniejący `char_run` do już istniejącego systemu zasobów.

## 12.2. `campaign_step1_assets.py`

Obecny placeholder:

```text
Planowane | import AZ nie jest jeszcze dostępny w zasobach bramki.
```

zostaje zastąpiony rzeczywistym snapshotem z SQLite.

Przykładowy stan:

```text
AZ - anotacje znaków
Źródło: pula projektu / import AZ
184 cropy z AZ
147 OK | 25 do zatwierdzenia | 12 N
```

## 12.3. Akcja w wierszu AZ

Korzystamy z istniejącego slotu akcji w tabeli zasobów.

Obsługiwane źródła:

1. **Pula bieżącego projektu** — jeśli AZ już istnieje,
2. **Inny projekt w tym samym registry** — bez eksportowania plików,
3. **Pakiet AZ** — dla danych spoza aktualnego Workspace.

Jeśli istniejący modal „Import zasobów” ma już model wyboru źródła/scope, AZ powinno wejść do niego jako kolejny handler, nie jako nowy modal.

## 12.4. T01

T01 może przyjąć AZ jako zasób opcjonalny.

Jeśli bieżące cropy jeszcze nie istnieją:

- AZ zostaje zarejestrowane w puli projektu,
- późniejsze PZ1 automatycznie odzyska je po SHA.

Nie blokujemy T01 tylko dlatego, że AZ nie pasuje jeszcze do żadnego cropa tej iteracji.

## 12.5. T02

T02 jest naturalnym miejscem użycia gotowego AZ.

Dwa warianty:

### A. Projekt ma już zgodne cropy/AT

Import AZ dołącza rewizje do istniejącej puli i po wejściu do Z3/PZ2 materiał jest od razu gotowy do kontroli.

### B. Pakiet AZ jest hermetyczny i zawiera cropy + anchor manifest

Może zostać potraktowany jako kompletne źródło znaków i otworzyć PZ2 bez ponownego PZ1.

Warunek: pakiet musi przejść pełną walidację manifestu, SHA i lineage.

Jeśli pakiet zawiera tylko anotacje bez cropów i w projekcie nie istnieją odpowiadające cropy — zasób jest `niezgodny`/`częściowy`, nie próbujemy zgadywać dopasowań.

---

# 13. Tryb swobodny — UX bez mnożenia CTA

## 13.1. Nie dodajemy trzeciego kafla

Obecny kafel:

```text
Wskaż anotacje do wyodrębnienia
```

uogólniamy do np.:

```text
Wskaż źródło zewnętrzne
```

Jeden flow obsługuje:

```text
AT → annotations.xml + obrazy → PZ1 → PZ2
AZ → pakiet AZ / registry → bezpośrednio PZ2
```

## 13.2. Rozpoznawanie typu bez zbędnego pytania

Preferowana kolejność UX:

1. użytkownik korzysta z istniejącego wejścia „zewnętrzne źródło”,
2. wskazuje plik/folder,
3. backend rozpoznaje format:
   - `annotations.xml` / run Z2 → AT,
   - manifest `alpr.az_pack.v1` → AZ,
4. tylko jeśli źródło jest niejednoznaczne, pokazujemy wybór typu.

Nie pokazujemy dodatkowego modala „AT czy AZ?” przy każdym użyciu.

## 13.3. Tryb swobodny nie modyfikuje projektu

Import AZ w free mode:

- rejestruje cropy globalnie,
- może utworzyć rewizje AZ,
- materializuje working set PZ2,
- **nie tworzy `project_crop_members`**, nawet jeśli w tle istnieje aktywny projekt.

Dopiero późniejsze użycie `Import zasobów → AZ` w kampanii formalnie przypisuje materiał do projektu.

---

# 14. Przenoszenie AZ między projektami w tym samym Workspace

To nie powinno wymagać fizycznego eksportu pliku.

Przykład:

```text
Projekt A
crop X → AZ rev 4
crop Y → AZ rev 2

Projekt B
T02 → Import zasobów → AZ → źródło: Projekt A
```

Backend:

1. pobiera listę cropów/revizji z Projektu A,
2. dla każdego cropa sprawdza membership Projektu B,
3. brakujące membership dodaje,
4. tworzy binding projektu B do importowanej rewizji,
5. ustawia `trust_state=external_pending_review`,
6. nie kopiuje niepotrzebnie pliku, jeśli artifact jest dostępny w registry,
7. zapisuje zdarzenie w historii projektu.

To jest podstawowy scenariusz „przenoszenia między projektami”.

---

# 15. Pakiet AZ — przenoszenie między Workspace/komputerami

## 15.1. Schemat

Proponowana nazwa schematu:

```text
alpr.az_pack.v1
```

Rozszerzenie pliku można ustalić później. Backend nie powinien być zależny od finalnej nazwy rozszerzenia.

## 15.2. Struktura

```text
package/
├── manifest.json
├── crops/
│   ├── <crop_identity_sha256>.jpg
│   └── ...
├── az/
│   ├── <crop_identity_sha256>.json
│   └── ...
└── checksums.json
```

## 15.3. Manifest

```json
{
  "schema": "alpr.az_pack.v1",
  "created_at": "...",
  "source_context": "project|free_mode",
  "source_project": "informacyjne",
  "crop_identity_schema": "alpr.crop_identity.v1",
  "counts": {
    "crops": 120,
    "with_az": 118,
    "ok": 70,
    "ready": 30,
    "excluded": 18
  },
  "items": [
    {
      "crop_identity_sha256": "...",
      "identity_mode": "lineage_v1",
      "crop_path": "crops/...jpg",
      "file_sha256": "...",
      "az_path": "az/...json",
      "az_payload_sha256": "...",
      "source_status": "perfect",
      "anchor": {
        "source_image_sha256": "...",
        "rectification_version": "..."
      }
    }
  ]
}
```

## 15.4. Walidacja importu

Przed zapisem do DB:

- schema/version,
- brak path traversal,
- brak symlinków,
- limity rozmiaru/liczby elementów,
- wszystkie zadeklarowane pliki istnieją,
- `file_sha256` zgodne,
- `az_payload_sha256` zgodne,
- `crop_identity_sha256` zgodne z manifestem/lineage,
- bboxy poprawne i w zakresie,
- znaki należą do alfabetu,
- brak duplikatów crop identity w pakiecie.

Cały import przechodzi przez staging + transakcję SQLite. Błąd krytyczny nie może pozostawić połowy zasobu jako „zaimportowanej”.

---

# 16. Eksport AZ i UX

## 16.1. Ta sama przestrzeń robocza

Nie eksportujemy pliku tylko po to, aby użyć AZ w innym projekcie w tym samym `alpr_registry.sqlite3`.

`Import zasobów` powinien umieć wskazać zasób AZ z innego projektu bez fizycznego pakowania.

## 16.2. Eksport plikowy jest funkcją transportową

Jest potrzebny dla:

- innego komputera,
- backupu,
- ręcznego przekazania materiału,
- odseparowanego Workspace.

Nie tworzymy przez to stale widocznego CTA w PZ2.

## 16.3. Miejsce UI eksportu

Po wdrożeniu backendu wykonać osobny mini-audyt istniejącej powierzchni eksportowej.

Preferencja:

- użyć istniejącego menu/sekcji eksportu/„więcej”,
- jeśli PZ3 ma istniejący mechanizm wyboru rodzaju operacji eksportowej, dodać AZ jako format/zakres,
- nie uzależniać eksportu roboczego AZ od osiągnięcia GOLD — backend musi umieć eksportować częściową pracę.

Jeżeli istniejący PZ3 nie pozwala na eksport niedokończonej pracy bez mylenia semantyki, lepiej umieścić eksport AZ w istniejącym menu kontekstowym/operacyjnym niż dodać nowy duży CTA na głównym PZ2.

---

# 17. Adapter PZ2 — bez dużego refaktoru edytora

## 17.1. Materializacja

PZ2 nadal dostaje:

```text
preview_dir/
├── images/
└── metadata.json
```

`az_workset.materialize(...)` przygotowuje ten zestaw z registry/pakietu.

## 17.2. Hydracja

Dla każdego cropa:

- rekord bazowy PZ1,
- `crop_id`,
- `crop_identity_sha256`,
- jeśli istnieje AZ → dołącz `characters`, layout, gold_state/status i provenance.

## 17.3. Powrót zmian

Po zapisie PZ2:

```text
metadata.json
      ↓
canonical AZ payload
      ↓
payload_sha256
      ↓
az_revisions
      ↓
project_crop_az (campaign)
```

W free mode rewizja może zostać zapisana globalnie jako przenośna rewizja, lecz nie ma project binding.

---

# 18. Obsługa CVAT

CVAT pozostaje osobną pętlą korekcyjną.

Po imporcie CVAT i aktualizacji `metadata.json`:

1. istniejący mechanizm zapisuje manualne poprawki,
2. warstwa AZ tworzy nową rewizję dla zmienionych cropów,
3. `source_kind = cvat_manual`,
4. `parent_revision_id` wskazuje rewizję sprzed importu,
5. crop identity nie zmienia się.

Dzięki temu CVAT nie tworzy drugiej, równoległej historii poza AZ.

---

# 19. Migracja istniejących projektów i runów

Nie wykonujemy masowej, agresywnej migracji 89 MB bazy na starcie aplikacji.

## 19.1. Migracja schematu

Registry posiada już wersjonowanie przez:

```text
PRAGMA user_version
SCHEMA_VERSION
MIGRATIONS
```

Nie dodajemy drugiego mechanizmu migracyjnego.

Migracja `AZ001`:

- podnosi `SCHEMA_VERSION` z 5 do 6,
- dodaje `SCHEMA_V6_STATEMENTS`,
- dodaje `_migrate_to_v6()`,
- rejestruje `MIGRATIONS[6]`,
- tworzy tylko nowe tabele/indeksy,
- nie wykonuje backfillu,
- jest idempotentna.

## 19.2. Lazy backfill

Istniejące cropy rejestrujemy **leniwie**, gdy:

- projekt zostanie otwarty w Z3,
- PZ2 zostanie przywrócone,
- użytkownik eksportuje AZ,
- użytkownik wybiera projekt jako źródło AZ.

Dla istniejącego preview:

1. odczytaj `metadata.json`,
2. odnajdź obrazy w `images/`,
3. jeśli da się odtworzyć lineage → `lineage_v1`,
4. jeśli nie → fallback `pixels_v1`,
5. zarejestruj crop,
6. utwórz rewizję AZ z aktualnego metadata,
7. dla projektu dodaj membership/binding.

## 19.3. Nie zmieniamy historycznych plików bez potrzeby

Do starych `metadata.json` dopisujemy nowe ID dopiero przy ich aktywnym wznowieniu/zapisie.

---

# 20. API importu — jeden backend, różne wejścia UX

Proponowany kontrakt wysokiego poziomu:

```python
import_az_resource(
    source,
    *,
    target_scope,
    project_id=None,
    iteration_num=None,
    active_preview_dir=None,
)
```

`target_scope`:

```text
campaign
free_mode
```

Wynik:

```json
{
  "ok": true,
  "source_kind": "registry_project|az_pack",
  "matched": 120,
  "new_crops": 30,
  "reused_crops": 90,
  "imported_revisions": 100,
  "duplicates": 10,
  "conflicts": 5,
  "skipped": 5,
  "materialized_preview_dir": "..."
}
```

GUI jedynie renderuje rezultat.

---

# 21. Stan zasobu `char_run` w grafie

W `campaign_resource_state` / resource snapshot AZ powinno raportować m.in.:

```text
present
crop_count
az_count
ok_count
ready_count
excluded_count
conflict_count
source_mode
source_project
source_package
contract_ready
requires_review
```

Proponowane statusy prezentacyjne:

- `brak`,
- `jest`,
- `częściowe`,
- `do kontroli`,
- `niezgodne`.

Nie tworzymy kilkunastu mikrostatusów w UI.

---

# 22. Szczegółowa kolejność implementacji

## Etap AZ000 — audyt i baseline — **WYKONANE**

1. Zlokalizowano warstwę registry na `feature/evaluation-registry`.
2. Odrzucono pełny merge tej gałęzi jako zbyt szeroki i ryzykowny.
3. Przeniesiono minimalny fundament SQLite na `funkcja/az-crop-registry`.
4. Zweryfikowano `SCHEMA_VERSION=5`, `user_version=5`, WAL/FK oraz `integrity_check=ok`.
5. Wykonano kopię bazy przed pracami.
6. Audyt realnej DB:
   - `33 186` image artifacts,
   - `11 077` unique SHA,
   - `1 498` duplicated SHA groups,
   - brak cropów PZ1/Z3.
7. Potwierdzono, że `image_artifacts` nie może być logicznym rejestrem cropów 1:1.

**Kryterium zakończenia:** spełnione.

---

## Etap AZ001 — schema migration v5 → v6 — **DONE**

### Zakres kodu

```text
auto_annotation_tool/registry/schema.py
auto_annotation_tool/registry/migrations.py
tests/test_registry_schema.py
tests/test_registry_migrations.py
tests/test_az_registry_schema.py
```

### Implementacja

1. `SCHEMA_VERSION = 6`.
2. Dodać `SCHEMA_V6_STATEMENTS`.
3. Dodać:
   - `plate_crops`,
   - `crop_artifacts`,
   - `project_crop_members`,
   - `iteration_crop_members`,
   - `az_revisions`,
   - `project_crop_az`.
4. Dodać indeksy z sekcji 5.
5. Dodać `_migrate_to_v6()`.
6. Dodać `6: _migrate_to_v6` do `MIGRATIONS`.
7. Nie dotykać danych tabel v1–v5.

### Testy obowiązkowe

- pusta baza inicjalizuje się do v6,
- v5 → v6 zachowuje stare rekordy,
- `user_version=6`,
- `PRAGMA foreign_key_check` bez błędów,
- druga migracja jest no-op,
- dwa różne `artifact_id` mogą należeć do jednego `crop_id`,
- duplicate `image_artifacts.sha256` pozostaje dozwolony,
- duplicate `(identity_schema, identity_sha256)` jest blokowany,
- membership i FK zachowują integralność.

### Bezpieczeństwo

Migrację rzeczywistej bazy uruchamiamy dopiero po zielonych testach i po kopii:

```text
Workspace/_registry/backups/alpr_registry_before_AZ001.sqlite3
```

**Kryterium:** rzeczywista baza przechodzi 5→6, `integrity_check=ok`, a liczniki starych tabel nie zmieniają się.

---

## Etap AZ002 — `crop_identity` — **DONE**

1. Implementacja canonical JSON.
2. Implementacja `lineage_v1`.
3. Implementacja `pixels_v1` fallback.
4. Testy stabilności hashy.
5. Testy: nazwa/katalog nie wpływa na identity.
6. Test: zmiana geometrii zmienia identity.
7. Test: zmiana rectification version zmienia identity.
8. Test: ten sam lineage w innej iteracji daje ten sam SHA.

**Kryterium:** mamy deterministyczny kontrakt crop identity.

---

## Etap AZ003 — rejestracja cropów PZ1

1. Podpiąć identity do końca procesu wyodrębniania.
2. Upsert `image_artifacts` bez zmiany istniejącej semantyki.
3. Upsert `plate_crops`.
4. W kampanii: membership projektu + iteracji.
5. Dodać ID/hash do `metadata.json`.
6. Przy istniejącym cropie nie tworzyć nowego `plate_crops`.
7. Dopuścić wiele fizycznych artifactów do jednego logicznego cropa.

**Kryterium:** powtórne PZ1 na tym samym lineage rozpoznaje crop jako istniejący.

### Stan realizacji AZ003 — DONE (2026-09-25)

AZ003 został wdrożony i zweryfikowany end-to-end.

#### AZ003A — backend rejestracji logicznego cropa

Powstał moduł:

```text
auto_annotation_tool/registry/az_registry.py
```

Zakres:

- atomowa rejestracja `source_images` + `image_artifacts(kind='plate_crop')` + `plate_crops` + `crop_artifacts`,
- rozdzielenie logicznego cropa od fizycznego artifactu,
- idempotencja dla tego samego identity i tej samej ścieżki,
- obsługa 1 logiczny crop → N fizycznych artifactów,
- reuse istniejącego `source_images` po `canonical_sha256`, nawet jeśli historyczny `source_image_id` ma inny format,
- opcjonalny membership projektu i iteracji,
- rollback całej transakcji przy błędnym projekcie,
- free mode bez membership projektu.

Ważne rozróżnienie pozostaje obowiązujące:

```text
PZ1 / GT Pack source_image_id:
img-sha256-<lowercase sha>

SQLite registry source_images.source_image_id:
SRC-SHA256-<UPPERCASE SHA>
```

Adapter łączy te światy po `canonical_sha256`, a nie przez wymuszanie identycznego string ID.

#### AZ003B — adapter całego runu PZ1

Powstał moduł:

```text
auto_annotation_tool/registry/pz1_run_registry.py
```

Adapter bierze zakończony run:

```text
run_dir/
├── metadata.json
└── images/
```

i dla każdego cropa:

1. buduje `crop_identity.v1`,
2. liczy SHA fizycznego JPG,
3. rejestruje logiczny crop i artifact w SQLite,
4. opcjonalnie dodaje membership projektu/iteracji,
5. uzupełnia `metadata.json` o trwałe referencje.

Do `metadata.json` trafiają m.in.:

```text
crop_id
crop_identity_sha256
crop_identity_schema
crop_identity_mode
crop_contract_sha256
artifact_id
registry_source_image_id
```

Weryfikacja po AZ003B:

```text
49 passed, 14 subtests passed
```

#### AZ003C — realny hook końca PZ1

Hook został podpięty w:

```text
auto_annotation_tool/gui/z3_extraction_tab_ui.py
```

Kolejność jest celowo następująca:

```text
PlateGenerator
→ generator.save_metadata()
→ merge reextract / zachowanie wcześniejszych boxów
→ register_pz1_preview_run()
→ przejście do PZ2
```

Rejestracja odbywa się **po merge reextract**, aby registry pracował na finalnym `metadata.json` runu.

Hook jest best-effort:

- błąd SQLite/registry jest logowany,
- błąd registry nie może zerwać istniejącego PZ1/PZ2,
- workflow użytkownika pozostaje działający nawet przy awarii registry.

Dodatkowo dodano stabilne mapowanie projektu kampanii do `projects.project_id` na podstawie `folder_name`, zgodne z historycznym registry eksperymentów.

Weryfikacja po AZ003C:

```text
55 passed, 14 subtests passed
```

#### AZ003D — test na realnym runie PZ1

W trybie swobodnym wykonano świeży realny run:

```text
Workspace/3_cropped_characters/run_001_20260925_115720
```

Verifier potwierdził:

```text
user_version: 6
integrity_check: ok
foreign_key_check rows: 0

total PZ1 lineage crops: 11
verified in registry: 11
missing hook fields: 0
project membership rows: 0
iteration membership rows: 0
projects: FREE MODE / brak membership

RESULT: PASS
```

Wniosek:

```text
PZ1
→ crop_identity.v1
→ image_artifacts(kind=plate_crop)
→ plate_crops
→ crop_artifacts
→ metadata.json z crop_id / artifact_id
```

działa na rzeczywistym runie aplikacji.

Free mode zachowuje oczekiwaną semantykę: crop jest globalnie zarejestrowany, ale nie tworzy `project_crop_members` ani `iteration_crop_members`.

#### Ważny wniosek z diagnostyki AZ003D

Nie wolno używać samego `metadata.json mtime` jako czasu utworzenia runu. PZ2 może później ponownie zapisać stare `metadata.json`, przez co historyczny run wygląda jak świeży.

Przykład:

```text
run_001_20260923_013511
metadata mtime: 2026-09-25
```

To nadal run z 23 września. Do diagnostyki wieku runu preferujemy timestamp z nazwy `run_...`, manifest/provenance albo faktyczny czas utworzenia runu, a nie wyłącznie mtime metadanych.

---

## Etap AZ004 — zapis i rewizje AZ z PZ2 — **DONE END-TO-END**

Cel AZ004: trwały, wersjonowany zapis semantycznego stanu AZ w SQLite, niezależny od roboczego `metadata.json` PZ2.

### Aktualna polityka zapisu

Po implementacji i testach przyjęto świadomie prostszą politykę niż pierwotny debounce wszystkich manualnych zmian:

```text
ruch / resize boxa
→ zapis roboczy metadata.json PZ2
→ bez automatycznej rewizji AZ

N (exclude) / O (approve)
→ trwały zapis metadata.json
→ canonical AZ payload
→ payload SHA compare
→ nowa rewizja AZ tylko jeśli stan semantyczny się zmienił
```

Powód: przed doświadczeniami ważniejsza jest stabilna, audytowalna historia **decyzji semantycznych** niż tworzenie rewizji SQLite przy każdym technicznym ruchu boxa. PZ2 pozostaje roboczym edytorem, SQLite przechowuje trwałe checkpointy AZ.

### AZ004A — backend wersjonowanych rewizji AZ — **DONE**

Powstał moduł:

```text
auto_annotation_tool/registry/az_revision_store.py
```

Zrealizowano:

- canonical payload `alpr.az_revision.v1`,
- deterministyczny `payload_sha256`,
- normalized bbox `[0,1]`,
- stabilne sortowanie znaków,
- layout + GOLD/status + opcjonalny expected text,
- deduplikację identycznego payloadu,
- `parent_revision_id`,
- binding `project_crop_az` dla kampanii,
- free mode bez sztucznego project binding,
- walidację zgodności crop identity.

Weryfikacja:

```text
55 passed, 10 subtests passed
```

### AZ004B — adapter PZ2 metadata → canonical AZ payload — **DONE**

Powstał moduł:

```text
auto_annotation_tool/registry/pz2_az_adapter.py
```

Adapter mapuje rzeczywisty rekord PZ2 na canonical AZ payload:

- pixel bbox → `[0,1]`,
- `reading_row` → `row`,
- `character`, `method`, `source_kind`, `confidence`,
- layout kind / confirmed,
- GOLD: approved / excluded / candidate,
- status / expected text,
- provenance dla CVAT / local manual / auto.

Testy adaptera przeszły.

### AZ004C — hook decyzji N/O w PZ2 — **DONE (implementacja + testy)**

Powstał moduł:

```text
auto_annotation_tool/registry/pz2_revision_registry.py
```

Hook w:

```text
auto_annotation_tool/gui/z3_review_runtime.py
```

Semantyka:

- `N` → event `exclude_toggle`,
- `O` → event `review_approved`,
- brak rewizji AZ na sam drag/resize/autosave,
- registry dimensions są źródłem prawdy do normalizacji bbox,
- free mode zapisuje rewizję globalną bez project binding,
- campaign mode wiąże rewizję z projektem/iteracją,
- błąd registry nie blokuje UI PZ2.

### AZ004D — realny test trwałości N/O — **DONE / REAL PASS**

Run testowy:

```text
Workspace/3_cropped_characters/run_001_20260925_115720
```

Pierwszy verifier wykazał:

```text
Excluded AZ-backed plates in metadata: 0
FAIL: brak trwałego excluded w metadata.json
```

Diagnostyka potwierdziła, że handler `N` poprawnie ustawia w pamięci:

```text
gold_state["excluded"] = True
```

oraz uruchamia hook AZ, natomiast trwały zapis mógł trafić do ścieżki wynikającej z aktualnego `preview_dir_var`, a nie do runu faktycznie załadowanego w PZ2.

#### AZ004D-PATH — naprawa bezpieczeństwa ścieżki zapisu — **DONE / TESTS GREEN**

Zmieniono wspólny mechanizm synchronicznego zapisu metadata PZ2:

```text
_loaded_meta_path
→ ma pierwszeństwo

preview_dir_var / _get_preview_metadata_path()
→ tylko fallback
```

To ujednolica synchroniczny zapis z istniejącym autosave, który już wcześniej chronił edycje przed zapisaniem do innego wybranego runu.

Dodano test regresyjny:

```text
test_sync_persist_writes_loaded_run_not_next_selected_run
```

Testy po patchu przeszły.

#### Realna weryfikacja po poprawce

Po ponownym uruchomieniu aplikacji i naciśnięciu `N` na jednej tablicy verifier zwrócił:

```text
Excluded AZ-backed plates in metadata: 1

Registry:
user_version: 6
integrity_check: ok
foreign_key_check rows: 0

plate_000000:
crop_id: CROP-EB3FA80A9B0544EBB3BFD2CB3CFE8300
az_revision_id: AZR-CC1A2C56BBDA4B3C8C4EFCF99CD92E17
source_kind: pz2_detect
source_status: needs_fix
trust_state: auto
origin_project_id: None
origin_iteration: None
excluded: True
project bindings: 0

=== RESULT ===
PASS
```

Potwierdzono więc end-to-end:

```text
N w PZ2
→ gold_state.excluded=true w tym samym metadata.json
→ canonical AZ payload
→ trwała rewizja az_revisions
→ free mode bez project binding
→ SQLite integrity OK
```

### Kryterium zamknięcia AZ004 — **SPEŁNIONE**

AZ004 otrzymuje status:

```text
DONE END-TO-END
```

### Zmiany UX wspierające dalszy reuse AZ — **DONE**

W trakcie AZ004 wykonano również potrzebne uporządkowanie istniejących wejść Z2/Z3, bez dodawania nowej ścieżki AZ.

#### Z2HIST — historia runów AT

- dropdown pokazuje run + datę + liczbę AT,
- podgląd anotacji jest osadzony w wolnym obszarze Z2,
- pokazuje próbki cropów AT z marginesem,
- nie używa osobnego modala,
- testy regresyjne zielone.

#### Z3SRC — źródło wejściowe PZ1/PZ2 w free mode

`Wskaż własne źródło` zostało rozdzielone na dwa **alternatywne**, a nie sekwencyjne warianty:

```text
A. Gotowe tablice
   → istniejący run PZ1 (metadata.json + images/)
   → bez ponownego PZ1
   → bezpośrednio PZ2

B. XML + obrazy
   → AT + obrazy źródłowe
   → nowy run cropów PZ1
   → PZ2
```

Dodatkowo:

- lista istniejących runów PZ1 jest wewnętrzna, nie opiera się głównie na Explorerze,
- Explorer pozostaje fallbackiem `Wskaż run spoza listy…`,
- podgląd cropów znajduje się po prawej stronie,
- wybór jednej ścieżki ukrywa UI drugiej,
- brak nowego trzeciego kafla AZ,
- testy Z3 source routes przeszły (`40 passed`).

Ta architektura jest bezpośrednim fundamentem AZ005/AZ008: gotowe cropy bez AZ trafią do PZ2 jako nowa praca, a gotowe cropy z pasującą rewizją AZ będą mogły zostać automatycznie uwodnione.

---

## Etap AZ005 — automatyczne odzyskiwanie w kolejnej iteracji — **DONE END-TO-END**

Cel AZ005: przy ponownym pojawieniu się tego samego logicznego cropa automatycznie odzyskać istniejącą AZ z SQLite, bez dodatkowego CTA i bez ponownego boxowania.

### AZ005A — resolver istniejącej rewizji AZ — **DONE**

Rozszerzono:

```text
auto_annotation_tool/registry/az_revision_store.py
```

Polityka wyboru:

```text
free mode
→ najnowsza znana rewizja AZ dla crop_id

campaign
→ wyłącznie jawne project_crop_az dla bieżącego project_id
→ brak cichego fallbacku do globalnej AZ / innego projektu
```

Testy:

```text
22 passed
```

### AZ005B — odwrotny adapter canonical AZ → PZ2 metadata — **DONE**

Rozszerzono:

```text
auto_annotation_tool/registry/pz2_az_adapter.py
```

Adapter odtwarza:

- bbox `[0,1]` → piksele PZ2,
- znaki,
- `reading_row`, `reading_col`, `reading_index`,
- layout,
- GOLD / excluded / candidate,
- status,
- expected text,
- provenance `az_reuse`.

Adapter zachowuje bazową linię PZ1/cropa, w tym `crop_id` i `crop_identity_sha256`.

Canonical AZ **nie odtwarza sesyjnego `review_state`**. Nie fabrykujemy `approved_reference`, timestampów ani nowej decyzji człowieka.

Dodano semantyczny round-trip:

```text
PZ2 → canonical AZ → PZ2 → canonical AZ
```

Testy:

```text
37 passed
```

### AZ005C — automatyczny hook reuse podczas load PZ2 — **DONE (implementation + tests)**

Powstał moduł:

```text
auto_annotation_tool/registry/pz2_az_reuse.py
```

oraz hook best-effort w:

```text
auto_annotation_tool/gui/z3_preview_ui.py
→ load_preview_data()
```

Przepływ:

```text
PZ2 ładuje metadata.json
        ↓
crop_id / crop_identity_sha256
        ↓
AZ005A resolver
        ↓
sprawdzenie polityki ochrony
        ↓
AZ005B AZ → PZ2
        ↓
materializacja w loaded metadata
        ↓
trwały zapis do tego samego metadata.json
```

AZ reuse może zastąpić:

- świeży rekord PZ1/PZ2,
- nietknięty automatyczny wynik RAW,
- starszą materializację `az_reuse`, jeśli registry ma nowszą rewizję.

AZ reuse **nie może** nadpisać:

- `review_state.human_edited=True`,
- zatwierdzonego lokalnego REVIEW,
- `manual_correction`,
- `manual`,
- `cvat_import`,
- źródła `local_manual`,
- źródła `cvat_manual`,
- `source_info.last_modified_by=human`,
- lokalnej decyzji `N`,
- lokalnego GOLD/O, jeśli rekord nie pochodzi już z `az_reuse`.

Dla kampanii nadal obowiązuje:

```text
project-bound AZ only
```

Awaria registry:

```text
log warning
→ PZ2 nadal się otwiera
```

Testy AZ005C i pakiet regresyjny przeszły.

### AZ005D — realny reuse na kolejnym runie — **DONE / REAL PASS**

Przygotowano kontrolowany drugi fizyczny run:

```text
run_AZ005D_reuse_20260925_222147
```

Wybrany przypadek:

```text
plate_id: plate_000000
crop_id: CROP-EB3FA80A9B0544EBB3BFD2CB3CFE8300
expected AZ: AZR-CC1A2C56BBDA4B3C8C4EFCF99CD92E17
expected excluded: True
```

Stan startowy runu B:

```text
characters: 0
excluded: False
az_reuse: None
az_revisions: 5
project_crop_az: 0
```

Pierwszy realny verifier wykazał brak materializacji. Diagnostyka potwierdziła jednak, że:

```text
AZ005A resolver działa
AZ005B reverse adapter działa
AZ005C backend reuse działa
direct GUI helper call -> applied=1
```

Przyczyną było umieszczenie hooka reuse wyłącznie w gałęzi `need_reload`.

#### AZ005D-HOOK — poprawka miejsca wykonania reuse — **DONE / TESTS GREEN**

Reuse zostało przeniesione poza warunek `need_reload`:

```text
load_preview_data()
        ↓
ZAWSZE sprawdź reusable AZ
        ↓
same AZ -> already_current
human work -> protected
newer reusable AZ -> applied
        ↓
zapis metadata.json tylko gdy applied > 0
```

Dodano regresje sprawdzające:

- zapis po `applied > 0`,
- brak zapisu przy braku zmiany.

#### Realny verifier po poprawce — PASS

Po restarcie aplikacji i ponownym otwarciu tego samego runu B verifier zwrócił:

```text
Loaded row:
plate_id: plate_000000
crop_id: CROP-EB3FA80A9B0544EBB3BFD2CB3CFE8300
status: needs_fix
characters: 0
excluded: True
az_reuse.az_revision_id:
AZR-CC1A2C56BBDA4B3C8C4EFCF99CD92E17

Registry:
az_revisions before/after: 5 / 5
project_crop_az before/after: 0 / 0
integrity_check: ok
foreign_key_check rows: 0

=== RESULT ===
PASS
```

`characters: 0` jest prawidłowe dla tego przypadku, ponieważ źródłowa rewizja `N/excluded` również nie zawierała znaków. Kluczowe jest, że run B odzyskał dokładnie tę samą semantykę canonical AZ.

Potwierdzono end-to-end:

```text
run A
→ trwała AZ w SQLite
→ drugi fizyczny run tego samego logical crop
→ automatyczny lookup po crop_id
→ materializacja tej samej az_revision_id
→ excluded=True
→ provenance az_reuse
→ brak nowej rewizji
→ brak project binding w free mode
→ SQLite integrity OK
```

### Kryterium zamknięcia AZ005 — **SPEŁNIONE**

```text
użytkownik nie boxuje drugi raz cropa o tej samej identity,
a automatyczne reuse nie nadpisuje nowszej pracy człowieka.
```

AZ005 otrzymuje status:

```text
DONE END-TO-END
```

---

## Etap AZ006 — backend importu między projektami w jednym registry — **DONE END-TO-END**

Cel AZ006 był następujący: pozwolić projektowi docelowemu przejąć istniejące AZ z innego projektu **bez kopiowania rewizji, bez dopasowań heurystycznych i bez cichego nadpisywania własnej pracy**.

### AZ006A — bezpieczny backend project -> project — **DONE**

Powstał moduł:

```text
auto_annotation_tool/registry/az_project_import.py
```

oraz testy:

```text
tests/test_az_project_import.py
```

Import jest dozwolony wyłącznie dla ścisłego przecięcia logical cropów:

```text
source project ma crop_id X
AND
target project ma crop_id X
```

Nie dopasowujemy:

- po nazwie pliku,
- po numerze tablicy,
- po podobieństwie obrazu,
- po samych boxach,
- po luźnym SHA artefaktu bez zgodnego logical crop identity.

Projekt docelowy musi już mieć crop w:

```text
project_crop_members
```

Import nie tworzy kopii rewizji:

```text
source:
crop_id X -> AZR-123

target:
crop_id X -> ten sam AZR-123
```

Powstaje wyłącznie nowe powiązanie:

```text
project_crop_az(target_project_id, crop_id, az_revision_id)
```

Klasyfikacja planu importu:

```text
importable
already_bound
target_conflict
target_missing_crop
source_missing_crop_membership
```

Reguły:

```text
target nie ma AZ dla cropa
→ importable

target ma dokładnie tę samą az_revision_id
→ already_bound

target ma inną AZ dla cropa
→ target_conflict
→ NIE nadpisuj

target nie ma cropa
→ target_missing_crop
→ NIE importuj
```

Domyślny status targetu po imporcie:

```text
effective_status = imported_pending_review
```

Powtórny import jest idempotentny.

### AZ006B — materializacja `imported_pending_review` w PZ2 — **DONE**

Potwierdzona semantyka:

```text
canonical AZ:
- bboxy zachowane
- znaki zachowane
- layout zachowany
- expected_text zachowany
- provenance zachowane

target PZ2:
- approved = False
- candidate = False
- excluded = False
- status = needs_fix
- requires_review = True
- effective_status = imported_pending_review
- fusion source = az_project_import
```

Źródłowe `approved/perfect` nie staje się lokalnym GOLD projektu docelowego.

Testy po AZ006B:

```text
49 passed
```

Commit:

```text
43863eb Materialize imported AZ for PZ2 review
```

### AZ006C1 — realny binding/import A -> B — **REAL PASS**

Audyt rzeczywistego registry wykazał, że istniejące projekty nie miały jeszcze:

```text
project_crop_members: 0
project_crop_az: 0
```

Dlatego przygotowano kontrolowaną parę projektów testowych w tym samym realnym SQLite.

Wynik:

```text
imported: True
same_revision: True
pending_review: True
no_new_revision: True
projects_plus_2: True
members_plus_2: True
bindings_plus_2: True
integrity_ok: True
foreign_keys_ok: True

=== RESULT ===
PASS
```

Potwierdzono realnie:

- ten sam `crop_id`,
- ten sam `az_revision_id`,
- brak nowej rewizji przy imporcie,
- `effective_status = imported_pending_review`.

### AZ006C2 — realna materializacja targetu — **REAL PASS**

Do jednoznacznego testu użyto kontrolowanej rewizji fixture z:

```text
characters: ['A', 'B']
approved: True
status: perfect
```

Po imporcie do projektu B:

```text
characters: ['A', 'B']
status: needs_fix
gold_state:
  approved: False
  candidate: False
  excluded: False

effective_status: imported_pending_review
requires_review: True
fusion source: az_project_import
```

Verifier potwierdził:

```text
two_chars: True
status_needs_fix: True
approved_false: True
candidate_false: True
excluded_false: True
requires_review: True
effective_status: True
project_id: True
import_provenance: True
same_revision: True
expected_text: True
canonical_source_still_approved: True
canonical_source_still_perfect: True
materialized_payload_not_approved: True
materialized_payload_needs_fix: True
no_revision_from_import: True
no_revision_from_materialize: True
integrity_ok: True
foreign_keys_ok: True

=== RESULT ===
PASS
```

### Cleanup AZ006C — **PASS**

Po verifierach usunięto wyłącznie kontrolowane:

- projekty `PRJ-AZ006C...`,
- projekty `PRJ-AZ006C2...`,
- jedną fixture revision utworzoną dla C2,
- fizyczny run `run_AZ006C2_pending_review_...`.

Wynik:

```text
=== RESULT ===
PASS
Usunięto kontrolowane projekty/rewizję/runy AZ006C.
Istniejące projekty użytkownika i wcześniejsze AZ pozostały nietknięte.
```

### Kryterium zamknięcia AZ006 — **SPEŁNIONE**

```text
Projekt B może przejąć AZ z A dla tego samego logical cropa,
bez ponownego boxowania,
bez kopiowania rewizji,
bez automatycznego GOLD,
bez cichego nadpisania własnej AZ B.
```

AZ006 ma status:

```text
DONE END-TO-END
```

---

## Etap AZ007 — podłączenie AZ do istniejącego grafu T01/T02 — **IMPLEMENTATION COMPLETE / LIVE C3 PENDING**

Cel: `AZ` ma stać się pełnoprawnym zasobem istniejącego modelu E1/T01/T02, bez nowej bramki, nowego top-level CTA ani osobnej ścieżki PZ2.

### AZ007A — registry-backed `char_run` — **DONE**

Audyt wykazał, że graf i modal zasobów już posiadają:

```text
row_key = char_run
label = AZ - anotacje znaków
primary action label = Import
```

ale stan był placeholderem:

```text
Planowane | import AZ nie jest jeszcze dostępny w zasobach bramki.
counter = 0
```

AZ007A zastąpiło placeholder realnym odczytem registry projektu.

Nowy moduł:

```text
auto_annotation_tool/registry/az_campaign_resource.py
```

Testy:

```text
tests/test_az_campaign_resource.py
```

Modyfikowany UI:

```text
auto_annotation_tool/gui/campaign_step1_assets.py
```

#### Zasada

Refresh grafu jest read-only wobec registry.

Projekt jest identyfikowany przez istniejący stabilny kontrakt:

```text
project_id_from_folder_name(folder_name)
```

Nie tworzymy drugiej mapy projektów ani nie wywołujemy `ensure_campaign_project()` tylko po to, aby narysować UI.

Agregator czyta:

```text
project_crop_members
project_crop_az
```

i zwraca:

```text
crop_count
az_count
usable_count
ready_count
pending_review_count
excluded_count
other_count
missing_count
latest_updated_at
coverage_status
contract_ready
```

Stany pokazywane dla AZ:

```text
no_project
no_crops
missing
partial
full
```

W UI odpowiada to prostym komunikatom:

```text
Brak cropów PZ1
Brak AZ
Częściowe
Jest
```

Licznik ma formę:

```text
usable AZ / logical crops projektu
np. 7/12
```

Snapshot resource meta zawiera także breakdown:

```text
ready
pending review
excluded
missing
```

Szczegóły AZ nie mówią już „Planowane”; pokazują realny stan registry projektu.

#### Testy AZ007A

```text
40 passed in 4.01s
```

### AZ007B1 — discovery projektów źródłowych AZ — **DONE**

AZ007B zostało celowo podzielone na backend i UI.

Nowa część backendowa znajduje projekty, które już mają AZ i ocenia każdy source względem targetu przy użyciu **tej samej logiki AZ006**, bez własnych heurystyk GUI.

Rozszerzony moduł:

```text
auto_annotation_tool/registry/az_project_import.py
```

Dodano:

```text
AZProjectImportSourceCandidate
list_project_az_import_sources(...)
```

Dla każdego źródła zwracane są m.in.:

```text
source_project_id
target_project_id
source_display_name
source_folder_name
source_campaign_key
source_az_count
importable_count
already_bound_count
conflict_count
target_missing_crop_count
invalid_source_count
can_import
compatible_count
```

#### Ważna zasada

Discovery jest **read-only**:

```text
nie tworzy projektów
nie tworzy bindingów
nie tworzy rewizji
nie zmienia project_crop_az
```

Każdy kandydat jest analizowany przez:

```text
analyze_project_az_import(...)
```

czyli dokładnie ten sam backend, który został zweryfikowany w AZ006.

Sortowanie preferuje:

```text
najwięcej importable
potem already_bound
potem najmniej conflicts
potem najmniej target_missing_crop
```

#### Regres napotkany i naprawiony w AZ007B1

Pierwszy patch B1 podczas wstawiania nowej funkcji przypadkowo zmienił sygnaturę:

```python
def import_project_az_bindings(
    *,
    ...
)
```

zamiast poprawnej:

```python
def import_project_az_bindings(
    registry: AZRegistry,
    *,
    ...
)
```

Objaw:

```text
TypeError:
import_project_az_bindings() takes 0 positional arguments
but 1 positional argument ... was given
```

Naprawiono wyłącznie sygnaturę; logika AZ006 pozostała bez zmian.

**Przyszły agent nie może ponownie zmieniać tej sygnatury.**

#### Testy AZ007B1

Po poprawce:

```text
25 passed in 5.37s
```

Pokryte przypadki:

```text
source discovery
importable/already/conflict/missing counts
read-only discovery
target bez cropów
dotychczasowe AZ006 import tests
AZ007A resource aggregation
PZ2 reuse regressions
```

### AZ007B2 — istniejąca akcja `Import` dla AZ — **DONE**

AZ007B2 podłączyło gotowy backend AZ006/AZ007B1 do istniejącego wiersza:

```text
row_key = char_run
label = AZ - anotacje znaków
primary_label = Import
```

Nie powstał nowy wiersz zasobu, nowa bramka ani nowe top-level CTA.

#### Zrealizowany kontrakt

1. `Import` dla `char_run` jest aktywowany wyłącznie w prawidłowym kontekście.
2. Browser źródeł korzysta z:

```python
list_project_az_import_sources(...)
```

3. Analiza zgodności pozostaje read-only.
4. Finalne `Importuj` korzysta z:

```python
import_project_az_bindings(
    registry,
    source_project_id=...,
    target_project_id=...,
)
```

5. Import:
   - używa istniejącego `az_revision_id`,
   - nie kopiuje canonical rewizji,
   - importuje tylko exact `crop_id`,
   - nie stosuje filename/fuzzy/image-similarity matching,
   - nie nadpisuje konfliktów targetu,
   - ustawia target binding jako `imported_pending_review`.
6. Po imporcie odświeżany jest istniejący resource modal.
7. Sam import nie:
   - otwiera automatycznie PZ2,
   - zatwierdza bramki,
   - tworzy `review_state`,
   - nadaje lokalnego GOLD/OK.

#### Semantyka partial

Przykładowo:

```text
source AZ: 20
target wspólne cropy: 8
importable: 6
already: 1
conflict: 1
target_missing_crop: 12
```

Importowanych jest tylko:

```text
6 importable
```

Brakujące cropy nie są „ratowane” heurystyką.

---

### AZ007C — kontrakt T01/T02, regresje i real UI smoke — **IN PROGRESS**

AZ007C został podzielony na część kontraktowo-regresyjną i kontrolowany test na rzeczywistym UI.

#### AZ007C1 — kontrakt grafu i resource semantics — **DONE**

Potwierdzone reguły:

- T01 nie zależy od AZ w sposób blokujący przygotowanie obrazów/AT;
- T02 korzysta tylko z logical cropów faktycznie należących do targetu;
- partial pozostaje partial;
- conflicts nie są nadpisywane;
- `imported_pending_review` nie jest lokalnym `OK`;
- sam fakt importu AZ nie przesuwa etapu kampanii;
- pending review nie spełnia kontraktu równoważnego reviewed/local GOLD;
- GT nie jest wejściem do RAW inference Z3;
- RAW Z3 pozostaje `gt_blind.v1`.

#### AZ007C2 — integracja UI/grafu i regresje — **DONE**

Domknięto regresje istniejącego grafu i usunięto legacy fallbacki, które mogły udawać planowany placeholder zamiast realnego registry.

W szczególności testy zabezpieczają m.in.:

```text
tests/test_az_campaign_graph_contract.py
tests/test_campaign_entry_resource_selection.py
```

oraz ścieżki resource-selection używane przez T01/T02.

#### AZ007C3 — kontrolowany real UI smoke SOURCE → TARGET — **IMPLEMENTATION READY / LIVE PENDING**

Projekt źródłowy:

```text
AZ007C3_SOURCE
```

Minimalny materiał kampanii dla toru znaków:

```text
>= 10 zatwierdzonych tablic AT
```

SOURCE został przeprowadzony przez:

```text
T01 char_from_images
→ E2
→ T03
→ Z2
→ 10 zatwierdzonych tablic
→ E3
→ T05
→ PZ1/PZ2
```

Podczas smoke testu wykryto i naprawiono kilka regresji UX/runtime.

##### C3-UI1 — T01 resource state

Lokalne porównanie `path_key == current_path` błędnie zgłaszało T01 jako nieaktywne dla `char_from_images`.

Naprawa:

```text
campaign_dashboard_ui
→ użycie wspólnego is_transition_path_active(...)
```

T01 może legalnie obsługiwać zarówno `plate_training`, jak i `char_from_images`.

##### C3-UI2 — ręczne przygotowanie XML w Z2

T03 poprawnie otwierało Z2, ale UI nie wystawiało jawnego startu manualnego XML mimo kontraktu:

```text
wejście Z2 odtwarza workspace
→ użytkownik sam uruchamia przygotowanie manualnego XML
```

Naprawa przywróciła CTA:

```text
Przygotuj roboczy XML Z2
```

Po utworzeniu XML aktywne jest:

```text
Rysuj ramkę 4 pkt (D)
```

##### PZ2 review flow V3 — aktualny kontrakt numeru

Jeżeli tablica **nie ma zapisanego numeru**:

```text
operator sprawdza/poprawia boxy i symbole
→ O / Zatwierdź tablicę
→ bieżący świadomie sprawdzony odczyt staje się pierwszym zapisanym numerem
→ tablica dostaje OK
```

Jeżeli numer został odziedziczony z Z2 (`ground_truth_source = manual_z2`):

```text
Numer z Z2: ...
```

Edycja boxów i znaków:

- nie nadpisuje cicho numeru z Z2,
- jawnie informuje operatora o istniejącym numerze,
- po korekcie oczekuje `O`.

Jeżeli odczyt znaków różni się od odziedziczonego numeru:

```text
O blokuje zatwierdzenie
```

Operator musi:

```text
poprawić znaki
albo
użyć „Zmień numer”
```

`Zmień numer` dla wartości odziedziczonej z Z2 pokazuje ostrzeżenie i wymaga jawnego potwierdzenia przed utworzeniem rewizji PZ2.

Stan persisted:

```text
approved bez jakiegokolwiek zapisanego numeru
```

pozostaje fail-closed.

##### PZ2 fullscreen / canvas UX

Wdrożono:

- numer widoczny bezpośrednio na canvasie,
- klikany canvas action do edycji numeru,
- `1R/2R` podąża razem z tablicą podczas pan,
- `1R/2R` jest po prawej stronie ramki w układzie pionowym,
- boczne zakładki paneli są lekkimi pionowymi zakładkami z kierunkiem wysunięcia/wsunięcia,
- dynamiczne copy `Status pracy` zawija się do rzeczywistej szerokości prawego panelu.

##### Stan regresji C3 przed live smoke

Przechodziły m.in.:

```text
81 passed — PZ2 review flow V3 i najbliższe regresje
68/68 — panel tabs/fullscreen/layout regressions
```

W drugiej serii jeden test Tk raz zatrzymał się na lokalnym błędzie inicjalizacji `tk.tcl`; dokładny retry tego testu przeszedł. Nie był to błąd logiki aplikacji.

##### Ważny punkt do sprawdzenia podczas C3

Skrót klawiaturowy `O` korzysta ze ścieżki zoptymalizowanej UI:

```text
_confirm_review_gold(
    quiet=True,
    persist=False,
    refresh=False,
)
```

a następnie planuje zapis metadata.

Przed uznaniem C3 za zakończone trzeba na realnym SOURCE potwierdzić, że zatwierdzenie wykonane skrótem `O` kończy się także oczekiwanym trwałym AZ/bindingiem w registry. Jeżeli nie, należy spiąć tę ścieżkę z tym samym trwałym checkpointem AZ co jawne zatwierdzenie przyciskiem.

Do czasu potwierdzenia w smoke teście jawny przycisk:

```text
Zatwierdź tablicę
```

jest bezpieczniejszym punktem kontrolnym do weryfikacji pełnej ścieżki persistence.

##### TARGET — reguła absolutna

TARGET nie może dostać ręcznie przerysowanych AT.

Aby `crop_id` było identyczne:

```text
same O
+ dokładnie ten sam SOURCE annotations.xml / AT
+ ta sama geometria źródłowa
+ ten sam PZ1 crop contract
= ten sam logical crop identity
```

Drobna różnica geometrii oznacza inny `source_geometry_hash`, a więc inny logical crop.

Docelowy test TARGET:

```text
SOURCE z AZ
  ↓
TARGET z tym samym crop_id
  ↓
T01/T02 → ZASOBY
  ↓
AZ → Import
  ↓
Import AZ z projektu
  ↓
importable > 0
  ↓
Importuj
  ↓
project_crop_az target = imported_pending_review
  ↓
resource row = Do kontroli
  ↓
PZ2 materializuje boxy/znaki/layout
  ↓
approved=False
candidate=False
excluded=False
status=needs_fix
requires_review=True
fusion/source=az_project_import
```

Następnie lokalna kontrola targetu musi się utrwalić i nie może zostać nadpisana ponownym importem.

#### Kryterium zamknięcia AZ007C3

C3 jest zamknięte dopiero, gdy na realnym SOURCE/TARGET potwierdzimy:

```text
1. SOURCE zapisuje trwałą AZ dla kontrolowanych tablic.
2. TARGET odtwarza exact same crop_id.
3. browser AZ pokazuje importable > 0.
4. import tworzy imported_pending_review.
5. PZ2 materializuje import bez automatycznego OK.
6. operator może zatwierdzić target lokalnie.
7. ponowne wejście/reload zachowuje lokalną decyzję.
8. ponowny import nie nadpisuje późniejszej pracy człowieka.
```

### Później

Źródło pakietowe ma pozostać pod tym samym `Import` AZ, ale hermetyczny format pakietu i jego walidacja należą do późniejszego etapu import/export, nie do podstawowego AZ007.

### Kryterium zamknięcia AZ007

```text
AZ jest pełnoprawnym zasobem istniejącego grafu T01/T02,
widocznym z realnym stanem registry,
importowanym istniejącą akcją zasobów,
bez nowej bramki i bez nowej ścieżki PZ2.
```

---

## Etap AZ008 — tryb swobodny

Stan UX wejścia został już częściowo przygotowany przez Z3SRC.

Docelowa semantyka pozostaje:

1. `Wskaż własne źródło` jest istniejącym wejściem nadrzędnym — bez osobnego kafla „Importuj AZ”.
2. Wariant `Gotowe tablice` obsługuje istniejący run PZ1 (`metadata.json + images/`) i przechodzi bezpośrednio do PZ2.
3. Wariant `XML + obrazy` zachowuje klasyczny flow AT → PZ1 → PZ2.
4. Po AZ005 wariant `Gotowe tablice` przy materializacji PZ2 automatycznie sprawdza registry po `crop_identity_sha256` i odzyskuje pasujące AZ.
5. Zewnętrzny AZ package/registry będzie rozpoznawany w tej samej rodzinie wejść, bez nowego top-level CTA.
6. Free mode nie tworzy project membership.
7. PZ2 działa na istniejącym formacie roboczym i dostaje odtworzone boxy/statusy jako materializację z registry.
8. AS/help pokazuje źródło i trust/reuse status, ale nie tworzy osobnego workflow.

**Kryterium:** użytkownik może użyć istniejącego runu cropów lub AZ bez przechodzenia przez XML/PZ1 i bez dodatkowego kafla głównego.

---

## Etap AZ009 — pakiet `alpr.az_pack.v1`

1. Eksporter.
2. Importer.
3. Checksums.
4. Walidacja bezpieczeństwa ZIP.
5. Partial work allowed.
6. N/OK/ready/needs_fix zachowane w źródle.
7. Import zewnętrzny stosuje trust policy.
8. Test round-trip.
9. Test między dwoma czystymi registry.

**Kryterium:** pakiet przenosi pracę między komputerami bez zależności od nazw plików.

---

## Etap AZ010 — UX eksportu

Dopiero po działającym backendzie.

1. Audyt istniejących powierzchni eksportowych.
2. Wykorzystanie istniejącego menu/sekcji.
3. Brak nowego stałego przycisku w PZ2, jeśli można uniknąć.
4. Eksport częściowej pracy musi być możliwy.
5. W tym samym registry promować transfer bezplkowy zamiast pakowania.

**Kryterium:** nowa funkcja nie zwiększa liczby głównych CTA bez uzasadnienia.

---

# 23. Plan testów

## 23.1. Testy jednostkowe

Proponowane pliki:

```text
tests/test_az_crop_identity.py
tests/test_az_registry.py
tests/test_az_revision_store.py
tests/test_az_package_contract.py
```

Scenariusze:

- stabilność SHA,
- inne nazwy pliku → ten sam crop identity,
- inna geometria → inny identity,
- duplicate artifact SHA nie psuje crop registry,
- payload dedup revisions,
- FK/ON DELETE zachowują integralność,
- błędne bbox/znak odrzucane.

## 23.2. Testy workflow

```text
tests/test_z3_az_iteration_reuse.py
tests/test_z3_az_campaign_import.py
tests/test_z3_az_free_mode_import.py
tests/test_z3_az_conflicts.py
tests/test_z3_az_cvat_revision.py
```

Scenariusze:

### Same project / next iteration

- IT1 crop A + manual AZ + OK,
- IT2 ponownie crop A,
- PZ2 odzyskuje AZ i OK automatycznie.

### New crop

- IT2 crop B nie istnieje,
- brak hydracji,
- zwykła praca.

### Cross-project

- A: crop X OK,
- B importuje X,
- boxy/znaki są obecne,
- status docelowy wymaga kontroli,
- A pozostaje niezmieniony.

### Conflict

- B ma manualną lokalną wersję,
- import innej wersji z A,
- lokalna nie jest nadpisana,
- konflikt raportowany.

### Free mode

- import AZ,
- brak wpisu w `project_crop_members`,
- PZ2 materializuje poprawnie,
- eksport round-trip działa.

## 23.3. Regresje istniejących testów

Szczególnie:

- PZ2 N/O,
- PZ2 GOLD eligibility,
- PZ3 export,
- CVAT import/export,
- T01/T02 state machine,
- project attachment,
- project history,
- Z3 free-mode flow,
- dataset provenance,
- SQLite experiment registry.

---

# 24. Testy wydajnościowe

Do zmierzenia:

1. hash 100 / 1 000 / 10 000 cropów,
2. lookup 1 000 SHA w SQLite,
3. materializacja PZ2 z 1 000 cropów,
4. hydracja 1 000 AZ,
5. debounce zapisów przy szybkim boxowaniu,
6. import pakietu 1 GB / wiele tysięcy cropów — jeśli realny zakres projektu tego wymaga.

Cel UX:

- pojedyncze przejście Q/E nie może blokować na zapisie SQLite,
- O/N nadal powinny dawać natychmiastowy feedback,
- sync trwały może odbywać się po natychmiastowej zmianie UI, ale musi zostać flushowany przed zmianą kontekstu/projektu.

---

# 25. Historia i provenance

Każdy import/promocja powinien zostawić ślad:

```text
AZ imported
source = project:<id> | package:<sha>
matched = ...
new = ...
conflicts = ...
iteration = ...
```

Do historii projektu nie wpisujemy każdego pojedynczego boxa. Rewizje cropów są w SQLite; historia kampanii dostaje agregowane zdarzenie operacyjne.

---

# 26. Rollback i bezpieczeństwo wdrożenia

1. Przed pierwszą migracją wykonać kopię `alpr_registry.sqlite3`.
2. Migracje tylko addytywne.
3. Nie usuwać ani nie rename’ować istniejących tabel w AZ001–AZ010.
4. Stary PZ2 ma działać nawet przy pustych nowych tabelach.
5. Jeśli registry AZ jest niedostępne, aplikacja ma wrócić do starego zachowania „pracuj tylko na metadata.json”, z ostrzeżeniem/logiem, a nie utratą pracy.
6. Import pakietu zawsze przez staging + transaction.
7. Brak automatycznego nadpisania manuali.

---

# 27. Kryteria akceptacji całego feature’u

Feature uznajemy za gotowy dopiero wtedy, gdy wszystkie poniższe punkty są spełnione.

Stan na 2026-09-27:

- [x] każdy nowy crop PZ1 ma stabilne `crop_identity_sha256`,
- [x] ten sam logiczny crop w kolejnej iteracji jest rozpoznawany,
- [x] PZ2 automatycznie odzyskuje AZ w tym samym projekcie,
- [x] `N`, `OK`, `ZATWIERDŹ`, `DO KOREKTY` mają zabezpieczony trwały kontrakt reuse,
- [x] zewnętrzny projekt nie może po cichu przemycić źródłowego `OK` jako finalnego OK targetu,
- [x] manualna lokalna wersja nie jest nadpisywana importem backendowym,
- [x] graf T01/T02 obsługuje istniejący `char_run` zamiast placeholdera,
- [x] import AZ korzysta z istniejącego „Import zasobów”,
- [ ] free mode wykorzystuje istniejące wejście zewnętrzne bez nowego kafla — **AZ008**,
- [ ] real SOURCE → TARGET potwierdza cross-project import w UI — **AZ007C3 LIVE PENDING**,
- [ ] AZ można wyeksportować/importować między Workspace przez `alpr.az_pack.v1` — **AZ009**,
- [ ] PZ3 GOLD/dataset przechodzi końcowy smoke po aktualnych zmianach C3,
- [ ] CVAT przechodzi końcowy regression/smoke po aktualnych zmianach,
- [x] backend importu SQLite nie zostawia częściowych bindingów po błędzie,
- [ ] pełny pakiet regresji milestone przechodzi przed rozpoczęciem właściwych doświadczeń,
- [ ] cały workflow jest potwierdzony na materiale eksperymentalnym bez konieczności ponownego boxowania tych samych logical cropów.

---

# 28. Co wdrażać najpierw — priorytet pod doświadczenia

Najkrótsza ścieżka dająca realną wartość przed eksperymentami:

```text
AZ000 audit DB
  ↓
AZ001 schema
  ↓
AZ002 crop identity SHA
  ↓
AZ003 rejestracja cropów PZ1
  ↓
AZ004 trwałe rewizje AZ
  ↓
AZ005 automatyczny reuse między iteracjami
```

Już po AZ005 rozwiązany jest główny problem:

> nie trzeba ponownie boxować tego samego cropa w kolejnych iteracjach projektu.

Następnie:

```text
AZ006 cross-project registry
  ↓
AZ007 T01/T02
  ↓
AZ008 free mode
  ↓
AZ009 package transport
  ↓
AZ010 finalne dopięcie UX eksportu
```

Dzięki temu nie blokujemy doświadczeń czekaniem na kompletne UI import/export.

---

# 29. Ostateczny przepływ użytkownika

## 29.1. Ta sama kampania — następna iteracja

```text
IT1 PZ2
boxowanie + poprawki + OK
        ↓
SQLite zapisuje crop identity + AZ
        ↓
IT2 PZ1
wycina crop
        ↓
SHA znane
        ↓
PZ2 automatycznie odzyskuje pracę
        ↓
operator pracuje tylko nad nowymi cropami
```

**Zero dodatkowych kliknięć.**

## 29.2. Inny projekt w tym samym Workspace

```text
Projekt B
T01/T02
  ↓
Import zasobów
  ↓
AZ
  ↓
wybór zasobu z Projektu A
  ↓
SQLite dopasowuje cropy po identity
  ↓
PZ2 pokazuje import do kontroli
```

**Bez ręcznego eksportu pliku.**

## 29.3. Inny komputer / Workspace

```text
Workspace A
AZ package export
      ↓
plik alpr.az_pack.v1
      ↓
Workspace B
T01/T02 → Import zasobów → AZ
      lub
Free mode → istniejące wejście zewnętrzne
      ↓
walidacja SHA
      ↓
registry
      ↓
PZ2
```

## 29.4. Tryb swobodny

```text
Z3
Wskaż źródło zewnętrzne
       ↓
AT → obecny PZ1
AZ → bezpośrednio PZ2
```

Bez zmiany stanu kampanii i bez przypisywania materiału do aktywnego projektu.

---

# 30. Zasada końcowa

Implementacja ma zmienić **tożsamość i trwałość danych**, a nie rozbudować interfejs.

Docelowy użytkownik powinien odczuć feature przede wszystkim jako:

> „Program pamięta cropy, nad którymi już pracowałem, i nie każe mi robić tego drugi raz.”

oraz:

> „Mogę użyć AZ z innego projektu przez istniejący import zasobów, a program sam sprawdzi, co naprawdę pasuje.”

Jeśli wdrożenie wymaga dodania wielu nowych przycisków, osobnych ekranów albo ręcznego zarządzania SHA, oznacza to, że warstwa backendowa została zbyt mocno przeniesiona do UX i plan należy uprościć.

---

# 31. Checkpoint wykonawczy — stan na start AZ001

```text
branch: funkcja/az-crop-registry

AZ000:
  DONE
  registry core restored
  schema v5 verified
  production registry integrity OK
  image_artifacts audited
  no PZ1 crops currently registered

AZ001:
  NEXT
  additive schema v6
  no UI
  no backfill
  no PZ1 integration yet

AZ002:
  AFTER AZ001
  crop_identity.v1

AZ003:
  PZ1 registration

AZ004:
  AZ revisions

AZ005:
  automatic iteration reuse
```

## Pierwsza seria commitów

```text
AZ000: Add SQLite registry foundation for AZ crop identity
AZ001: Add logical crop and AZ registry schema
AZ002: Add deterministic PZ1 crop identity
AZ003: Register PZ1 crops in SQLite registry
AZ004: Persist versioned AZ revisions
AZ005: Reuse AZ across project iterations
```

Do końca AZ005 nie dodajemy nowych głównych CTA.

---

# 32. Sposób pracy nad wdrożeniem — obowiązujący workflow współpracy

Ten projekt wdrażamy **iteracyjnie, małymi krokami**, z testem i feedbackiem po każdym kroku.

Nie przygotowujemy kilku dużych etapów naraz. Każdy kolejny patch powstaje dopiero po sprawdzeniu poprzedniego na rzeczywistym repo użytkownika.

## 32.1. Cykl pracy

Obowiązujący cykl:

```text
1. analiza aktualnego stanu repo
        ↓
2. przygotowanie małego skryptu patchującego
        ↓
3. użytkownik zapisuje/uruchamia skrypt w katalogu głównym repo
        ↓
4. uruchomienie wskazanych testów
        ↓
5. użytkownik wkleja wynik testów / git status / błąd
        ↓
6. analiza feedbacku
        ↓
7. poprawka albo kolejny mały skrypt
        ↓
8. ponowne testy
        ↓
9. commit etapu
        ↓
10. następny etap
```

## 32.2. Forma wymiany

Preferowana forma implementacji:

```text
ChatGPT / agent
→ generuje plik .py patchera

użytkownik
→ pobiera plik
→ umieszcza go w:
  C:\Users\48572\Desktop\dyplom\start4

użytkownik
→ uruchamia:
  python .\patch_....py
```

Patch powinien:

- wykonywać jeden jasno określony etap,
- być możliwie idempotentny,
- nie wymagać ręcznego kopiowania wielu fragmentów kodu,
- nie modyfikować plików niezwiązanych z etapem,
- kończyć się czytelnym komunikatem o zmienionych plikach,
- zatrzymywać się bezpiecznie, jeśli struktura repo jest inna niż oczekiwana.

## 32.3. Testy po każdym patchu

Po uruchomieniu patchera użytkownik wykonuje dokładnie podany zestaw testów, np.:

```powershell
python -m pytest `
  tests/test_az_crop_identity.py `
  tests/test_az_registry_schema.py `
  -q -p no:cacheprovider
```

Zakres testów dobieramy warstwowo:

```text
nowe testy etapu
+ najbliższe regresje
+ testy fundamentu, jeśli etap go dotyka
```

Nie uruchamiamy za każdym razem całego ogromnego suite, jeśli zmiana jest lokalna.

Pełniejszy zestaw regresji uruchamiamy:

- po zamknięciu większego etapu,
- przed merge,
- przed doświadczeniami do pracy inżynierskiej.

## 32.4. Feedback po stronie użytkownika

Po patchu użytkownik wkleja:

1. wynik patchera,
2. wynik wskazanych testów,
3. `git status -sb`,
4. ewentualny traceback/błąd.

Przykład:

```text
python patch_AZ00X_....py
→ patch applied

pytest ...
→ 18 passed

git status -sb
→ M ...
→ ?? ...
```

Na tej podstawie powstaje kolejny krok.

## 32.5. Zasada: feedback przed kolejnym etapem

Nie przechodzimy do następnego etapu tylko dlatego, że patch „powinien działać”.

Najpierw musi być:

```text
patch
→ lokalne uruchomienie
→ test
→ feedback
→ analiza
```

Dopiero potem:

```text
kolejny patch
```

Wyjątek: tylko drobna, oczywista poprawka testu lub patchera, która nie zmienia architektury.

## 32.6. Commitowanie

Commit powstaje dopiero wtedy, gdy:

- testy etapu są zielone,
- working tree zawiera tylko oczekiwane zmiany,
- nie ma tymczasowych patcherów w commicie,
- etap ma jednoznaczny zakres.

Schemat:

```text
patch
→ tests
→ git status
→ usunięcie patcherów roboczych
→ git add wybranych plików
→ git commit
```

Patcherów typu:

```text
patch_AZ001_....
patch_AZ002_....
verify_....
```

nie commitujemy, chyba że świadomie zostają jako narzędzie developerskie.

## 32.7. Bezpośrednia praca w repo zamiast dużych diffów tekstowych

Preferujemy:

```text
mały skrypt .py
```

zamiast:

```text
ręcznie wklej 200 linii do trzech plików
```

Powody:

- mniejsze ryzyko literówki,
- łatwiejsze odtworzenie,
- prostszy rollback,
- jednoznaczny zakres zmiany,
- szybszy feedback.

## 32.8. Reguła bezpieczeństwa

Jeżeli patch:

- nie znajduje oczekiwanego fragmentu,
- trafia na inną wersję pliku,
- wykrywa nieoczekiwany schemat DB,
- nie może jednoznacznie wykonać zmiany,

to powinien:

```text
STOP
```

zamiast próbować zgadywać.

Przykład:

```text
Nie znaleziono oczekiwanego fragmentu.
Nie zmieniono pliku.
```

Potem użytkownik wkleja błąd i przygotowywana jest poprawiona wersja patchera.

## 32.9. Zasada małych etapów AZ

Dla obecnego feature'u:

```text
AZ001 schema
→ test
→ feedback
→ commit

AZ002 crop identity
→ test
→ feedback
→ commit

AZ003 PZ1 registration
→ test
→ feedback
→ commit

AZ004 AZ revisions
→ test
→ feedback
→ commit

AZ005 automatic reuse
→ test
→ feedback
→ commit
```

Nie łączymy np. AZ003+AZ004+AZ005 w jeden patch.

## 32.10. Priorytet

Celem nie jest maksymalna szybkość pisania kodu, tylko:

```text
szybki mały krok
+ natychmiastowa weryfikacja
+ brak regresji
```

To jest szczególnie ważne przed doświadczeniami do pracy inżynierskiej.

---

# 33. Checkpoint historyczny — 2026-09-26, po AZ007B1

Stan:

```text
branch:
funkcja/az-crop-registry

AZ000:
DONE

AZ001:
DONE

AZ002:
DONE

AZ003:
DONE END-TO-END

AZ004:
DONE END-TO-END

Z2HIST:
DONE

Z3SRC:
DONE

AZ005:
DONE END-TO-END

AZ006:
DONE END-TO-END
- project -> project import
- exact crop_id only
- no heuristic matching
- imported_pending_review
- real C1 PASS
- real C2 PASS
- cleanup PASS

AZ007A:
DONE
- char_run registry-backed
- read-only refresh
- missing / partial / full
- ready / pending / excluded
- 40 passed

AZ007B1:
DONE
- source project discovery
- AZProjectImportSourceCandidate
- list_project_az_import_sources(...)
- all source analysis through AZ006
- read-only
- 25 passed
- signature regression fixed

AZ007B2:
NEXT
- enable existing Import action for char_run
- source-project browser
- preview importability
- import_project_az_bindings(...)
- refresh same resource modal

AZ007C:
PLANNED
- T01/T02 semantics
- partial/conflict
- graph regressions
```

Najbliższy krok:

```text
AZ007B2
→ patch campaign_dashboard_ui.py
→ char_run primary Import enabled in valid context
→ browser over list_project_az_import_sources(...)
→ import only when candidate.can_import
→ call import_project_az_bindings(...)
→ refresh rows
→ tests
```

Priorytet pozostaje ten sam: stabilny pipeline do doświadczeń pracy inżynierskiej, z maksymalnym reuse istniejącej pracy i minimalną liczbą nowych elementów UX.

---

# 34. Handoff historyczny — AZ007B2 i dalsze kroki

## 34.1. Cel nadrzędny

Nie rozwijamy AZ jako osobnego subsystemu UX dla samego siebie.

Cel całej pracy jest praktyczny:

```text
domknąć stabilny workflow doświadczeń do pracy inżynierskiej
i nie boxować ponownie tych samych logical cropów.
```

Każda zmiana powinna być oceniana pytaniem:

```text
Czy pomaga bezpiecznie reuse/importować istniejące AZ
bez naruszania pracy człowieka i bez zwiększania liczby ścieżek UI?
```

Jeżeli nie — prawdopodobnie nie należy do bieżącego etapu.

## 34.2. Obowiązkowy tryb współpracy

Pracujemy iteracyjnie:

```text
audit
→ mały patch_*.py
→ user uruchamia patch
→ dokładne testy
→ user wkleja output
→ analiza
→ commit
→ kolejny etap
```

Nie łączyć kilku etapów w jeden duży patch.

Patcher:

- musi walidować anchory,
- musi STOPować gdy struktura nie pasuje,
- powinien robić `compile()` przed zapisem, gdy to możliwe,
- nie może zgadywać miejsca insercji.

Po każdym patchu:

```powershell
python -m pytest ...
git status -sb
```

Pełny suite dopiero po większym milestone.

## 34.3. Kluczowe pliki AZ

### Registry / identity

```text
auto_annotation_tool/registry/az_registry.py
auto_annotation_tool/registry/crop_identity.py
auto_annotation_tool/registry/pz1_run_registry.py
```

### Rewizje AZ

```text
auto_annotation_tool/registry/az_revision_store.py
auto_annotation_tool/registry/pz2_revision_registry.py
auto_annotation_tool/registry/pz2_az_adapter.py
auto_annotation_tool/registry/pz2_az_reuse.py
```

### Import między projektami

```text
auto_annotation_tool/registry/az_project_import.py
```

### Stan AZ jako zasobu kampanii

```text
auto_annotation_tool/registry/az_campaign_resource.py
```

### UI kampanii / Import zasobów

```text
auto_annotation_tool/gui/campaign_step1_assets.py
auto_annotation_tool/gui/campaign_dashboard_ui.py
auto_annotation_tool/gui/tab_campaign.py
```

### PZ2 runtime

```text
auto_annotation_tool/gui/z3_preview_ui.py
auto_annotation_tool/gui/z3_review_runtime.py
auto_annotation_tool/gui/z3_preview_metadata_runtime.py
```

## 34.4. Najważniejsze kontrakty, których nie wolno złamać

### Crop identity

```text
crop identity != GT
```

Zmiana GT nie zmienia logical cropa.

### AZ identity

Canonical AZ jest rewizją semantyczną cropa.

Nie wiąż AZ po nazwie pliku.

### Cross-project import

```text
same crop_id only
```

Nie stosować fuzzy match ani podobieństwa obrazu.

### Conflict policy

Jeżeli target ma inną AZ:

```text
target_conflict
→ nie nadpisuj
```

### Imported review policy

Cross-project import:

```text
effective_status = imported_pending_review
```

Materializacja do PZ2:

```text
boxy/znaki/layout/expected_text = zachowane
approved = False
candidate = False
excluded = False
status = needs_fix
requires_review = True
```

### Human-work protection

Nie nadpisywać:

```text
human_edited
manual_correction
manual
cvat_import
local_manual
cvat_manual
lokalnego N
lokalnego O/GOLD
```

### Reuse nie jest nową decyzją REVIEW

Materializacja nie tworzy:

```text
review_state
approved_reference
fake O
```

## 34.5. Project ID

Stabilny registry project ID:

```python
project_id_from_folder_name(folder_name)
```

Do zapisu projektu, gdy trzeba:

```python
ensure_campaign_project(...)
```

Ale read-only UI refresh nie powinien tworzyć projektu.

AZ007A używa tylko:

```python
project_id_from_folder_name(...)
```

i czyta registry.

## 34.6. Co dokładnie istnieje w resource modal

W `campaign_dashboard_ui.py` istnieje już:

```text
row_key: char_run
label: AZ - anotacje znaków
primary label: Import
```

Nie dodawać drugiego wiersza AZ.

Nie dodawać osobnego przycisku w PZ2.

Nie dodawać nowej bramki.

## 34.7. Aktualny blocker AZ007B2

W `_refresh_rows(...)` obecnie istnieje blokada:

```python
primary_enabled = (
    spec_enabled
    and row_key != "char_run"
    ...
)
```

To jest miejsce do zmiany.

W `_run_action(...)` istnieją gałęzie dla:

```text
images
plate_run
plate_model
char_model
```

brakuje:

```text
char_run
```

AZ007B2 powinno dodać tylko tę gałąź i browser projektów źródłowych.

## 34.8. Backend gotowy do B2

W `az_project_import.py` istnieją:

```python
analyze_project_az_import(...)
import_project_az_bindings(...)
list_project_az_import_sources(...)
```

UI nie może duplikować ich logiki.

Browser powinien traktować te funkcje jako źródło prawdy.

## 34.9. Oczekiwany browser AZ source projects

Minimalna tabela:

```text
Projekt
AZ źródła
Do importu
Już przypięte
Konflikty
Brak cropa targetu
Status
```

Status może być prosty:

```text
Można importować
Brak zgodnych cropów
Konflikty
Już przypięte
```

Nie trzeba jeszcze implementować package import.

## 34.10. Import button logic

Finalny przycisk `Importuj`:

enabled gdy:

```python
candidate.can_import
```

po kliknięciu:

```python
result = import_project_az_bindings(...)
```

UI powinien pokazać:

```text
Zaimportowano: X
Już było: Y
Konflikty: Z
Brak cropa targetu: N
```

Po sukcesie:

```text
refresh istniejącego resource modal
```

Nie przechodź automatycznie do Z3/PZ2.

## 34.11. Testy B2

Minimum po patchu:

```text
tests/test_az_project_import.py
tests/test_az_campaign_resource.py
```

oraz test strukturalny/GUI-light sprawdzający:

```text
char_run nie jest już blokowany przez row_key != "char_run"
_run_action posiada gałąź char_run
browser używa list_project_az_import_sources
import używa import_project_az_bindings
```

Jeśli patch dotyka resource modal szerzej, uruchomić także:

```text
tests/test_campaign_graph_presentation.py
tests/test_resource_modal_minimize.py
tests/test_campaign_graph_sanity.py
```

jeżeli te pliki istnieją w aktualnym branch.

## 34.12. Regres z AZ007B1

Nie powtórzyć błędu:

```python
def import_project_az_bindings(
    *,
```

Poprawna sygnatura:

```python
def import_project_az_bindings(
    registry: AZRegistry,
    *,
```

To zostało już naprawione i testy są green.

## 34.13. Git discipline

Każdy etap osobny commit.

Przykładowa kolejność:

```text
AZ007A commit
AZ007B1 commit
AZ007B2 commit
AZ007C commit
```

Patchery tymczasowe usuwać przed commitem.

## 34.14. Co jest poza zakresem AZ007B2

Nie robić jeszcze:

- ZIP/manifest package AZ,
- zewnętrznego pliku import/export,
- nowego formatu kontraktu pakietowego,
- nowego widoku historii AZ,
- nowego PZ2 CTA,
- automatycznego otwierania PZ2 po imporcie,
- heuristic crop matching,
- zmiany schema SQLite.

Te rzeczy są później.

---

# 35. Potwierdzone kontrakty do checkpointu AZ007B1

Poniższe zasady są od teraz traktowane jako zweryfikowany kontrakt implementacyjny, a nie tylko założenie planu.

## 34.1. Logical crop vs physical artifact

```text
1 crop_id
→ 1..N image_artifacts
```

Ten sam logiczny crop może pojawić się w wielu fizycznych runach/ścieżkach bez duplikowania `plate_crops`.

## 34.2. Source identity

`source_file_sha256` jest mostem między PZ1/GT Pack i SQLite registry. Nie zakładamy zgodności stringowego `source_image_id` między warstwami.

## 34.3. Free mode

Free mode rejestruje globalne cropy i artifacty, ale nie tworzy sztucznego projektu tylko po to, żeby mieć membership.

## 34.4. Campaign mode

W kampanii projekt musi zostać odwzorowany na stabilny `projects.project_id`; mapping bazuje na trwałym `folder_name`, nie na efemerycznym stanie UI.


## 34.5. Reuse selection

```text
free mode
→ latest AZ revision for crop_id

campaign
→ project_crop_az for current project_id only
```

Nie ma cichego fallbacku między projektami.

## 34.6. Reuse vs human work

Registry może automatycznie nawodnić świeży lub nietknięty automatyczny rekord PZ2, ale nie może nadpisywać późniejszej pracy człowieka.

Chronione są przede wszystkim:

```text
human_edited
manual_correction
local_manual
cvat_manual
local N
local GOLD/O
```

## 34.7. AZ materialization is not a new REVIEW decision

Odtworzenie trwałej AZ:

- nie tworzy sztucznego `review_state`,
- nie tworzy `approved_reference`,
- nie udaje nowego kliknięcia `O`,
- zapisuje provenance `az_reuse`,
- zachowuje trwały stan semantyczny AZ.


## 34.8. Cross-project AZ import

Import AZ między projektami oznacza **binding istniejącej rewizji**, a nie kopiowanie canonical payloadu.

```text
source project
crop_id X -> AZR-Y

target project
crop_id X -> AZR-Y
```

Warunki:

- target musi już mieć `crop_id X` w `project_crop_members`,
- brak heurystycznego dopasowania cropów,
- istniejąca inna AZ targetu = konflikt i brak nadpisania,
- źródłowe `origin_project_id/origin_iteration` pozostają niezmienione,
- nowy target binding domyślnie otrzymuje `imported_pending_review`.

`imported_pending_review` jest decyzją projektu docelowego o zaufaniu/konieczności kontroli i **nie zmienia samej canonical rewizji AZ**.


## 34.9. Campaign resource snapshot for AZ

`char_run` w grafie kampanii jest widokiem stanu registry, a nie osobnym magazynem danych.

Źródło prawdy:

```text
project_crop_members
project_crop_az
```

Refresh UI:

- nie tworzy projektu,
- nie tworzy cropów,
- nie tworzy bindingów,
- nie zmienia rewizji,
- tylko agreguje istniejący stan.

Id projektu kampanii jest wyliczany istniejącym kontraktem:

```text
project_id_from_folder_name(folder_name)
```

AZ jako zasób raportuje pokrycie projektu (`missing/partial/full`) oraz rozdziela stan na `ready/pending review/excluded`.

## 34.5. Hook PZ1

Registry hook działa po finalnym merge reextract. Dzięki temu pola AZ dopisywane są do końcowego `metadata.json`, a nie do wersji, która mogłaby zostać chwilę później nadpisana.

## 34.6. Failure policy

Registry jest warstwą trwałości i reuse, ale jego chwilowa awaria nie może blokować podstawowego PZ1/PZ2. Hook pozostaje best-effort z logowaniem błędu.

## 34.7. Diagnostyka czasu runu

Do ustalania, czy run jest świeży, nie opieramy się wyłącznie na mtime `metadata.json`. Preferujemy:

1. timestamp zakodowany w nazwie `run_XXX_YYYYMMDD_HHMMSS`,
2. manifest/provenance runu,
3. jawne `created_at`, jeśli zostanie dodane,
4. dopiero pomocniczo mtime.

## 34.8. Trwały zapis PZ2 należy do załadowanego runu

Dla operacji synchronicznych (m.in. semantyczne N/O) źródłem prawdy dla ścieżki zapisu jest:

```text
_loaded_meta_path
```

a nie sam aktualny `preview_dir_var`.

Reguła:

```text
_loaded_meta_path
→ run faktycznie załadowany i edytowany

preview_dir_var
→ bieżący wybór / fallback, który może zmienić się wcześniej niż dataset w pamięci
```

Synchronizowany zapis i autosave muszą stosować tę samą zasadę, aby edycje historycznego runu nie zostały zapisane do innego runu.


---

# 35. Priorytet względem pracy inżynierskiej

Feature AZ rozwijamy tylko do poziomu potrzebnego do wiarygodnych doświadczeń.

Kolejność priorytetów pozostaje:

```text
trwała identyfikacja cropa
→ trwała rewizja AZ
→ reuse między iteracjami
→ kontrolowany import/export
→ doświadczenia
```

Nie dokładamy kosmetycznych ekranów ani dodatkowych CTA przed zamknięciem AZ004/AZ005, jeśli nie są niezbędne do eksperymentów.

---

# 36. Aktualny checkpoint — 2026-09-27, przed commitem C3

```text
branch:
funkcja/az-crop-registry

AZ000–AZ006:
DONE

AZ007A:
DONE

AZ007B1:
DONE

AZ007B2:
DONE

AZ007C1:
DONE

AZ007C2:
DONE

AZ007C3:
IMPLEMENTATION READY
LIVE SOURCE → TARGET SMOKE PENDING
```

Najważniejszy stan techniczny:

```text
registry v6
→ logical crop identity działa
→ PZ1 registration działa
→ versioned AZ działa
→ same-project reuse działa
→ cross-project exact-crop backend działa
→ char_run jest realnym zasobem kampanii
→ istniejący Import AZ jest podłączony
→ pending review policy jest fail-closed
```

Najważniejszy stan UX/runtime:

```text
T01 path state fixed
T03 manual XML entry fixed
PZ2 review-number flow V3 implemented
fullscreen number HUD implemented
1R/2R right-side vertical + pan-follow implemented
fullscreen side tabs slim/vertical
status copy dynamic wrap
```

Po tym checkpointcie nie należy rozszerzać AZ o nowe UX przed ukończeniem C3.

---

# 37. Plan bezpośrednio po commicie/pushu

Kolejność dalszych działań:

```text
1. reopen AZ007C3_SOURCE
2. T05 → PZ2
3. zatwierdzić kontrolowany zestaw 10 tablic
4. sprawdzić trwały zapis AZ w registry
5. przejść do PZ3
6. utworzyć źródłowy dataset/artefakt wymagany przez T05
7. potwierdzić source AZ bindings
8. utworzyć AZ007C3_TARGET
9. użyć tych samych O oraz dokładnie tego samego AT/annotations.xml
10. PZ1 target → te same crop_id
11. ZASOBY → AZ → Import AZ z projektu
12. potwierdzić imported_pending_review
13. wejść do PZ2 target
14. potwierdzić materializację bez automatycznego OK
15. zatwierdzić lokalnie wybrane rekordy
16. reload
17. potwierdzić persistence i ochronę pracy człowieka
```

Dopiero po tych punktach:

```text
AZ007C3 = DONE
AZ007 = DONE
```

---

# 38. Reguły testu SOURCE/TARGET

## 38.1. SOURCE

SOURCE służy do wytworzenia kontrolowanej, lokalnie zatwierdzonej AZ.

Nie wystarczy sam wynik YOLO.

Operator ma świadomie sprawdzić:

```text
geometrię boxów
znaki
layout 1R/2R
numer tablicy
```

i dopiero nadać `OK`.

## 38.2. TARGET

TARGET służy do testu przeniesienia istniejącej pracy.

Nie wolno ręcznie odtwarzać geometrii AT, ponieważ nawet minimalna różnica może utworzyć inny logical crop.

## 38.3. Oczekiwany import

Cross-project import przenosi pracę, ale nie zaufanie projektu źródłowego:

```text
source OK
→ target imported_pending_review
→ PZ2 needs_fix/requires_review
→ operator zatwierdza lokalnie
```

## 38.4. Ochrona lokalnej pracy

Po lokalnej korekcie targetu:

```text
kolejny import
```

nie może nadpisać:

```text
manual edit
local N
local OK
lokalnie zmienionego numeru
```

---

# 39. Milestone higieny repozytorium wykonany przed C3

Przed dalszym smoke testem oczyszczono historię Git z historycznego katalogu `data/`, który dominował rozmiar repo.

Wykonano:

```text
pełny bundle backup przed rewrite
git-filter-repo --path data/ --invert-paths
weryfikację branch trees przed/po
force-with-lease push
świeży clone start4
```

Historyczny pack zmniejszył się z około:

```text
695 MiB
```

do około:

```text
9.77 MiB
```

Workspace roboczy nie został usunięty. Aktualny `start4/Workspace` jest junctionem do zachowanego fizycznego Workspace w katalogu sprzed cleanupu.

**Nie usuwać katalogu `start4_pre_history_cleanup_2026-09-26` bez wcześniejszego przeniesienia fizycznego Workspace i aktualizacji junctiona.**

---

# 40. Priorytet po AZ007

Po zamknięciu realnego C3 kolejność pozostaje podporządkowana pracy inżynierskiej:

```text
AZ007 real workflow confirmed
→ minimalny brakujący AZ008/AZ009 tylko jeśli potrzebny do doświadczeń
→ zamrożenie pipeline
→ właściwe eksperymenty MZ-n vs MZ-s
```

Nie rozbudowujemy dalej UI dla samego AZ, jeśli nie zwiększa to wiarygodności lub powtarzalności doświadczeń.

Najważniejszy cel pozostaje:

> **program ma pamiętać i bezpiecznie reuse’ować pracę nad logical cropem, a użytkownik ma kontrolować tylko to, czego naprawdę jeszcze nie zatwierdził.**

