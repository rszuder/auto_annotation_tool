# HANDOFF — Desktop ALPR: weryfikacja człowieka dla sesji `.alprsession` i statystyki jakości modeli

## 0. Cel

Rozbudować desktopowy `auto_annotation_tool` o narzędzie do **weryfikacji jakości sesji badawczych z Androida**.

Telefon zbiera automatycznie surowe próby i cropy. Desktop jest miejscem, w którym operator:
- przegląda dowody,
- nadaje prawdę odniesienia (GT),
- oznacza próbki niepodlegające ocenie,
- zatwierdza, czy wykryty obszar jest rzeczywiście tablicą,
- a program automatycznie oblicza statystyki jakości.

Nie modyfikuj oryginalnej `.alprsession`.

Prawda odniesienia i wynik weryfikacji mają być osobnym artefaktem powiązanym z SHA-256 archiwum źródłowego.

---

## 1. Stan bazowy

Repo:

```text
rszuder/auto_annotation_tool
```

Commit bazowy przy przygotowaniu handoffu:

```text
1248b4bed3a2eace98c55d98882cbcbccfc5f05d
```

Przed zmianami:

```text
git status
git diff
```

Nie usuwaj lokalnych zmian.

---

## 2. Co już istnieje

Desktop ma już mechanizm importu raportów mobilnych.

Istnieją m.in.:

```text
auto_annotation_tool/gui/z4_mobile_report_browser.py
auto_annotation_tool/ranking/mobile_package_experiments.py
```

Obecny reader:
- otwiera `.alprsession`,
- waliduje archiwum,
- zna `samples/index.csv`,
- zna `samples/annotations.jsonl`,
- raportuje `crop_count`,
- raportuje `annotation_count`,
- czyta telemetryczne artefakty,
- zna manifesty pipeline'u i referencje modeli.

Nie buduj osobnego parsera ZIP od zera. Rozszerz istniejący `MobileReportBundle` / reader.

---

## 3. Wspólny kontrakt z Androidem

Nowe sesje Android będą zachowywać:

```text
samples/index.csv
samples/annotations.jsonl
samples/crops/*.jpg
```

oraz dodawać:

```text
samples/schema.json
samples/attempts.csv
samples/evidence/*.jpg
```

Top-level bundle może nadal używać:

```text
alpr.mobile_research_bundle.v1
```

Rozszerzenie jest addytywne.

---

## 4. Backward compatibility

Dla starej paczki bez:

```text
samples/attempts.csv
```

pokaż:

```text
Sesja nie zawiera pełnego rejestru prób MT.
Możliwa jest weryfikacja cropów MZ / odczytu end-to-end.
```

Nie odrzucaj starej paczki.

---

## 5. Nowy model domenowy desktopu

Preferowane nowe moduły:

```text
auto_annotation_tool/ranking/mobile_human_review.py
auto_annotation_tool/gui/z4_mobile_sample_review.py
```

Nazwy mogą się różnić, ale:
- obliczenia/statystyki poza Tkinter,
- UI nie może zawierać całej logiki porównania tekstów,
- reader ZIP pozostaje współdzielony.

Nie dopisuj całej logiki metryk bezpośrednio do `z4_mobile_report_browser.py`, jeśli można tego uniknąć.

---

## 6. MobileHumanReview

Wprowadź trwały model weryfikacji, np.:

```text
MobileHumanReview
```

Schemat:

```text
alpr.mobile_human_review.v1
```

Minimalne dane:

```text
schema
review_id
source_archive_path
source_archive_sha256
session_id
created_at
updated_at
reviewer_id
review_status
subjects
attempt_annotations
sample_annotations
```

Kluczowa reguła:

```text
source_archive_sha256
```

musi odpowiadać SHA-256 importowanej `.alprsession`.

Jeśli plik źródłowy się zmienił:

```text
REVIEW MUST NOT silently attach
```

---

## 7. Oryginalna paczka jest immutable

Zakaz:
- dopisywania GT do `.alprsession`,
- przepakowywania źródłowego ZIP po weryfikacji,
- podmieniania `samples/annotations.jsonl` wewnątrz źródła.

Domyślny sidecar:

```text
<session-name>.review.json
```

albo:

```text
output/mobile_reviews/<source_sha256>.review.json
```

Ważny jest kontrakt SHA, nie konkretna lokalizacja.

---

## 8. subject_key — grupowanie tej samej tablicy

Nowe sesje mają pole:

```text
subject_key
```

Preferowana semantyka:

```text
session_id + scene_generation + entity_id
```

Desktop ma grupować próbki po `subject_key`.

Nie grupuj po:

```text
prediction
consensus_prediction
plate text
```

OCR jest przedmiotem oceny.

Dla starych sesji bez `subject_key` użyj bezpiecznego fallbacku z identyfikatorów technicznych i oznacz grupę jako `legacy_identity`.

---

## 9. Workflow operatora

Po imporcie `.alprsession`:

```text
Import raportów Android
        ↓
wybierz sesję
        ↓
Weryfikacja próbek
```

Nowy ekran/panel powinien mieć trzy poziomy:

```text
SESJA
  ↓
TABLICA / SUBJECT
  ↓
PRÓBY / CROPY
```

---

## 10. Widok sesji

Pokaż co najmniej:

```text
session_id
experiment_type
series_id
scenario_id
replicate_index
device
analysis_mode
ROI policy
MP model / variant / runtime / precision
MT model / variant / runtime / precision
MZ model / variant / runtime / precision
liczba subjects
liczba attempts
liczba crops
liczba reviewed
liczba not reviewed
```

Jeżeli sesja jest `PARTIAL` albo `ERROR`, wyraźnie zaznacz niekompletność.

---

## 11. Widok subject / tablicy

Dla jednego `subject_key`:

```text
Subject 7 / 24

GT:
[ WI1234A ]

[ ZAPISZ GT ]
[ NIE DO OCENY ]

próby: 8
cropów: 5
MT miss: 2
odczytów MZ: 5
```

GT wpisuje się **raz dla subject**, a następnie jest stosowane do wszystkich jego cropów/prób.

---

## 12. Akcje operatora

Na poziomie subject:

```text
USTAW GT
ZGODNE Z PREDYKCJĄ
NIE DO OCENY
```

`ZGODNE Z PREDYKCJĄ` może przepisać wskazaną predykcję do GT.

Na poziomie konkretnej próby/dowodu:

```text
TABLICA WIDOCZNA
TABLICA NIEWIDOCZNA
NIEJEDNOZNACZNE
TO NIE JEST TABLICA
```

Nie każ operatorowi ręcznie liczyć znaków.

---

## 13. Terminologia UI

Używać:

```text
poprawnie rozpoznane znaki
błędnie rozpoznane znaki
brakujące znaki
znaki nadmiarowe

poprawny odczyt
niepoprawny odczyt
brak odczytu
```

Nie używać jako głównych etykiet:

```text
błędne zmiany
błędne zamiany
substitutions
deletions
insertions
```

Wewnętrznie algorytm może używać standardowych operacji edycyjnych.

---

## 14. Normalizacja rejestracji

Przed porównaniem:
- uppercase,
- trim,
- usuń spacje i separatory zgodnie z obowiązującą polityką rejestracji,
- nie stosuj agresywnej korekcji `O↔0`, `I↔1` przed metryką.

Jeżeli desktop ma już wspólną politykę normalizacji, użyj jej.

---

## 15. Porównanie znak po znaku

Dla:

```text
GT         = WI1234A
prediction = WI12B4A
```

wynik:

```text
poprawnie rozpoznane znaki = 6
błędnie rozpoznane znaki   = 1
brakujące znaki            = 0
znaki nadmiarowe           = 0
```

Dla:

```text
GT         = WI1234A
prediction = WI123A
```

wynik:

```text
poprawnie rozpoznane znaki = 6
błędnie rozpoznane znaki   = 0
brakujące znaki            = 1
znaki nadmiarowe           = 0
```

Dla:

```text
GT         = WI1234A
prediction = WI12344A
```

wynik:

```text
znaki nadmiarowe = 1
```

---

## 16. Algorytm alignment

W logice domenowej użyj deterministycznego dopasowania sekwencji opartego o odległość Levenshteina.

Zwracany obiekt, np.:

```text
PlateTextAlignment
```

ma mieć:

```text
ground_truth
prediction
exact_match
correct_characters
incorrect_characters
missing_characters
extra_characters
edit_distance
cer
alignment
```

Technicznie:

```text
incorrect_characters = substitutions
missing_characters = deletions
extra_characters = insertions
```

ale techniczne nazwy nie są główną terminologią UI.

---

## 17. CER

Liczyć:

```text
CER = (incorrect + missing + extra) / len(GT)
```

Jeżeli GT jest puste:

```text
CER = unavailable
```

---

## 18. Macierz błędów znaków

Dla błędnie rozpoznanych znaków zapisuj parę:

```text
GT char -> predicted char
```

Przykłady:

```text
0 -> O
1 -> I
B -> 8
```

Statystyki sesji powinny pokazać najczęstsze pomyłki. Brakujące i nadmiarowe znaki raportować osobno.

---

## 19. Ocena MZ

Dla każdego audytowalnego cropa tablicy z GT policz:

```text
exact match
incorrect read
no read
CER
correct chars
incorrect chars
missing chars
extra chars
```

`no read`:

```text
GT exists
AND crop is evaluable
AND MZ returned no usable registration
```

---

## 20. Ocena MT

Pełna ocena MT jest możliwa tylko dla nowych sesji z `samples/attempts.csv`.

Dla każdej próby MT operator ocenia:

```text
plate_visible = yes/no/uncertain
```

### MT success

```text
plate_visible = yes
AND mt_status = VALID_QUAD
```

### MT miss

```text
plate_visible = yes
AND mt_status = NO_DETECTION
```

### Invalid geometry

```text
plate_visible = yes
AND mt_status = DETECTION_INVALID_QUAD
```

### False detection

Jeżeli telefon wytworzył detekcję/crop, a operator oznaczy:

```text
TO NIE JEST TABLICA
```

→ false detection.

Nie nazywaj tego mAP. Bez GT bounding boxów nie jest to pomiar mAP.

Nazwa:

```text
skuteczność lokalizacji MT w próbach mobilnych
```

---

## 21. Metryki MT

Dla prób z:

```text
plate_visible = yes
```

policz:

```text
mt_valid_localization_count
mt_no_detection_count
mt_invalid_quad_count
mt_localization_success_rate
```

Dodatkowo:

```text
mt_false_detection_count
```

Próby:

```text
plate_visible = no
plate_visible = uncertain
stale_or_cancelled = true
```

nie wchodzą do podstawowego mianownika.

---

## 22. Ocena end-to-end ALPR

Dla każdego `subject_key` z GT policz:

```text
subject_exact_success
```

czyli czy system uzyskał co najmniej jeden dokładnie poprawny odczyt w czasie sesji.

Dodatkowo, jeśli dane wspierają:

```text
attempts_to_first_exact
time_to_first_exact_ms
first_exact_capture_source
first_exact_camera_zoom_ratio
baseline exact before AZ
exact only after AZ
consensus repaired result
```

Nie wyprowadzaj pól, których sesja nie zawiera.

---

## 23. Statystyki sesji

### Subjects

```text
evaluable_subjects
subjects_with_exact_read
subjects_without_exact_read
subject_success_rate
```

### Odczyty

```text
evaluable_reads
exact_reads
incorrect_reads
no_reads
exact_read_rate
no_read_rate
```

### Znaki

```text
gt_characters
correct_characters
incorrect_characters
missing_characters
extra_characters
CER
```

### MT — jeśli dostępne

```text
evaluable_mt_attempts
mt_valid_localizations
mt_no_detections
mt_invalid_quads
mt_localization_success_rate
mt_false_detections
```

### Czas do skutecznego wyniku — jeśli dostępne

```text
median_time_to_first_exact_ms
p90_time_to_first_exact_ms
median_attempts_to_first_exact
```

---

## 24. Statystyki per wariant

Wynik review musi zachować provenance:

```text
MP model_id/fingerprint/variant/runtime/precision
MT model_id/fingerprint/variant/runtime/precision
MZ model_id/fingerprint/variant/runtime/precision
```

Dzięki temu można porównywać konkretne warianty bez zgadywania.

---

## 25. Nie mieszaj dwóch rodzajów oceny

Rozdziel:

### jakość pojedynczego etapu

```text
MT localization success
MZ exact read / CER
```

### skuteczność systemu mobilnego end-to-end

```text
subject success rate
time to first exact
attempts to first exact
```

Nie przedstawiaj end-to-end jako mAP modelu.

---

## 26. UI — układ

Preferowany panel:

```text
┌ Sesja ─────────────────────────────────────┐
│ E1 / scenario / replicate / device         │
│ modele / warianty                          │
├ Subjects ───────┬──────────────────────────┤
│ 001  reviewed   │ [ obraz / evidence ]     │
│ 002  pending    │                          │
│ 003  pending    │ Predykcja: WI12B4A       │
│                 │ GT: [ WI1234A ]          │
│                 │                          │
│                 │ poprawne: 6              │
│                 │ błędnie rozpoznane: 1    │
│                 │ brakujące: 0             │
│                 │ nadmiarowe: 0            │
│                 │ CER: 0.143               │
│                 │                          │
│                 │ [ZAPISZ] [NIE DO OCENY]  │
├─────────────────┴──────────────────────────┤
│ Próby/cropy subjecta                       │
└────────────────────────────────────────────┘
```

---

## 27. Obraz z ZIP — bezpieczny lazy load

Dodaj możliwość pobrania konkretnego:

```text
samples/crops/<id>.jpg
samples/evidence/<attempt>.jpg
```

na żądanie.

Nie rozpakowuj całej paczki do projektu tylko po to, aby pokazać jeden crop.

Wprowadź limity:

```text
max image entry bytes
max decoded dimensions
```

---

## 28. Zapis review

Sidecar JSON ma przechowywać **adnotacje człowieka**, nie tylko gotowe statystyki.

Przykład:

```json
{
  "schema": "alpr.mobile_human_review.v1",
  "source_archive_sha256": "...",
  "session_id": "exp-...",
  "review_status": "in_progress",
  "subjects": {
    "exp-.../sg-1/entity-7": {
      "ground_truth": "WI1234A",
      "evaluable": true,
      "note": ""
    }
  },
  "attempt_annotations": {
    "attempt-...": {
      "plate_visibility": "visible",
      "is_plate": true
    }
  }
}
```

Derived metrics mogą być zapisywane jako cache, ale muszą być możliwe do ponownego obliczenia z adnotacji.

---

## 29. Revision i autosave

Każda zmiana operatora:

```text
review_revision++
updated_at
autosave
```

Zapis sidecar atomowy:

```text
temporary file
→ close/fsync
→ replace
```

Awaria desktopu nie może usuwać postępu weryfikacji.

---

## 30. Status review

Minimum:

```text
NOT_STARTED
IN_PROGRESS
COMPLETED
```

`COMPLETED` tylko wtedy, gdy wymagane subjects/próby mają decyzję albo są jawnie oznaczone `NIE DO OCENY`.

---

## 31. Eksport wyników

Dodaj z review możliwość eksportu:

```text
review.json
summary.csv
subjects.csv
character_confusion.csv
```

Opcjonalnie `summary.tex`, jeżeli naturalnie pasuje do istniejącego eksportu.

---

## 32. Integracja z MobilePackageExperimentStore / rankingiem

Nie zmieniaj rankingu automatycznie, dopóki review nie jest:

```text
COMPLETED
```

Po completed:
- quality może być zasilona zweryfikowanymi metrykami,
- źródło jakości oznacz jako `human_review`,
- zachowaj SHA źródłowej `.alprsession`.

Nie zastępuj surowych metryk latency/memory.

---

## 33. Operator i reviewer

Metodologicznie rozróżnić:

```text
collection operator
desktop reviewer
```

Może to być ta sama osoba.

Opcjonalnie przechowuj `reviewer_id`. Nie wymagaj danych osobowych.

---

## 34. Testy logiki tekstu

### D1

```text
GT = WI1234A
P  = WI1234A
```

Oczekiwane:

```text
exact = true
correct = 7
incorrect = 0
missing = 0
extra = 0
CER = 0
```

### D2

```text
GT = WI1234A
P  = WI12B4A
```

```text
correct = 6
incorrect = 1
missing = 0
extra = 0
```

### D3

```text
GT = WI1234A
P  = WI123A
```

```text
correct = 6
missing = 1
```

### D4

```text
GT = WI1234A
P  = WI12344A
```

```text
extra = 1
```

### D5

Pusty prediction przy widocznej/evaluable tablicy:

```text
no_read = true
missing = len(GT)
```

---

## 35. Testy importu i review

### R1 — nowa paczka
Reader ładuje `samples/index.csv`, `samples/attempts.csv`, `samples/schema.json` i obrazy.

### R2 — stara paczka
Brak `attempts.csv` nie powoduje błędu; UI informuje o ograniczeniu oceny MT.

### R3 — SHA mismatch
Sidecar z innego archiwum nie może zostać automatycznie podpięty.

### R4 — subject grouping
Wiele cropów tego samego `subject_key` dostaje jedno GT.

### R5 — OCR text not identity
Dwa różne subjects z tym samym OCR pozostają osobne.

### R6 — exact / incorrect / no read
Każdy stan jest liczony osobno.

### R7 — MT miss
Visible plate + `NO_DETECTION` → MT miss.

### R8 — no plate
`plate_visibility=no` nie zwiększa mianownika MT.

### R9 — cancelled
`stale_or_cancelled=true` nie jest liczone jako błąd modelu.

### R10 — false detection
`is_plate=false` przy detekcji → false detection.

### R11 — autosave
Po każdej zmianie sidecar da się ponownie otworzyć.

### R12 — original archive immutable
Hash `.alprsession` przed i po weryfikacji jest identyczny.

---

## 36. Testy statystyk

### S1

```text
10 evaluable reads
7 exact
2 incorrect
1 no read
```

```text
exact_read_rate = 0.7
no_read_rate = 0.1
```

### S2

```text
5 subjects
4 mają co najmniej jeden exact
```

```text
subject_success_rate = 0.8
```

### S3

```text
GT chars = 100
incorrect = 4
missing = 3
extra = 2
```

```text
CER = 0.09
```

### S4

```text
0 -> O = 2
1 -> I = 1
```

macierz ma zwrócić dokładnie te liczności.

---

## 37. Kryteria akceptacji desktop

Zadanie jest zakończone, gdy:

1. Istniejący import `.alprsession` nadal działa.
2. Nowe `samples/attempts.csv` jest czytane addytywnie.
3. Operator może otworzyć panel weryfikacji.
4. Próbki są grupowane po `subject_key`.
5. GT wpisuje się raz dla subject.
6. Program automatycznie liczy poprawnie rozpoznane, błędnie rozpoznane, brakujące i nadmiarowe znaki.
7. Program liczy exact match, no read i CER.
8. Nowe sesje pozwalają ocenić MT miss na podstawie evidence.
9. Stare sesje działają w ograniczonym trybie crop-only.
10. Oryginalna `.alprsession` nie jest modyfikowana.
11. Review jest zapisane w sidecarze związanym przez SHA-256.
12. Autosave chroni postęp operatora.
13. Dostępne są statystyki per read, per subject i — dla nowych danych — per MT attempt.
14. Wyniki zachowują dokładne provenance modelu/wariantu/runtime.
15. Review można wyeksportować do CSV/JSON.
16. Testy logiczne, parsera, SHA i statystyk przechodzą.

---

## 38. Raport końcowy agenta

Na końcu podaj:

```text
1. zmienione pliki,
2. zmiany w MobileReportBundle/reader,
3. nowy model MobileHumanReview,
4. lokalizację sidecara,
5. algorytm porównania tekstów,
6. sposób grupowania subjects,
7. sposób oceny MT miss,
8. dostępne statystyki,
9. backward compatibility,
10. testy i ich wyniki.
```
