# HANDOFF — Desktop: poprawna jednostka statystyki MT i zaślepiona weryfikacja GT

## Cel

Domknąć desktopowe narzędzie weryfikacji sesji mobilnych przed pierwszym pełnym pilotażem.

Dwa zadania:
1. poprawić jednostkę statystyki MT — liczyć rzeczywiste wywołania MT, a nie surowe rekordy detekcji,
2. wprowadzić domyślną zaślepioną weryfikację GT, aby operator nie był sugerowany predykcją modelu.

Nie przebudowuj istniejącego importu raportów ani rankingu.

## Stan bazowy

Repo:
`rszuder/auto_annotation_tool`

Gałąź:
`main`

HEAD podczas audytu:
`3f66c4be68846b139d78a24a3a1ac1c747d30781`

Commit zawiera już:
- `MobileHumanReview`,
- `MobileReviewSession`,
- `z4_mobile_sample_review.py`,
- obsługę `samples/attempts.csv`,
- statystyki MT/MZ/ALPR,
- immutable source `.alprsession`,
- sidecar związany przez SHA-256,
- autosave,
- eksport review/CSV,
- integrację `human_review` z rankingiem.

Przed zmianami:
```text
git status
git diff
git rev-parse HEAD
```

Nie usuwaj lokalnych zmian.

---

## 1. Problem statystyki MT

Android zapisuje:

```text
mt_invocation_id
```

Jedno rzeczywiste wywołanie backendu MT może zwrócić kilka detekcji:

```text
mt_invocation_id = X
    detection row 0
    detection row 1
    detection row 2
```

Obecna logika desktopu iteruje po `attempt_rows` i może potraktować te wiersze jako trzy niezależne próby MT.

Podstawowa jednostka wykonywania MT ma być:

> jedno rzeczywiste wywołanie backendu MT na jednym wejściu.

---

## 2. Model logiczny `MtInvocationGroup`

Dodaj model domenowy niezależny od Tk, np.:

```text
MtInvocationGroup
```

Pola:
```text
mt_invocation_id
session_id
scene_generation
subject_keys
source_sequence
source_timestamp_nanos
ROI/input geometry
evidence_entry
records
detection_count
cancelled
```

Nie trzeba serializować tego typu do pliku. Może być tworzony przy odczycie.

---

## 3. Grupowanie

Klucz podstawowy:

```text
mt_invocation_id
```

Fallback dla starych sesji:

```text
attempt_id
```

jeśli `mt_invocation_id` nie istnieje.

Nigdy nie grupuj po:
```text
prediction
consensus_prediction
plate text
```

---

## 4. Walidacja spójności invocation

Wszystkie wiersze jednego invocation powinny mieć zgodne:
- `session_id`,
- `scene_generation`,
- `visual_epoch`,
- `camera_transform_generation`,
- `source_sequence`,
- `source_timestamp_nanos`,
- ROI geometry,
- input geometry.

Jeżeli są sprzeczne:
```text
raise ValueError
```
albo oznacz źródło jako nieprawidłowe.

Nie wybieraj arbitralnie pierwszego rekordu.

---

## 5. Nowe pola Androida

Jeżeli paczka zawiera:

```text
mt_detection_index
mt_detection_count
```

wykorzystaj je do walidacji:

```text
indices unique
0..N-1
same count on all child rows
```

Jeżeli ich brak:
```text
legacy grouping by mt_invocation_id
```
ma nadal działać.

---

## 6. Wielotablicowe wejście

Jedno wywołanie R0 może widzieć więcej niż jedną fizyczną tablicę.

Bez pełnego GT bounding boxów nie wolno udawać klasycznego recall/mAP.

Dla metryki:
```text
mt_localization_success_rate
```

wprowadź decyzję operatora na poziomie invocation:

```text
visible_plate_count =
    none
    one
    multiple
    uncertain
```

UI po polsku:
```text
Brak widocznej tablicy
Jedna widoczna tablica
Wiele widocznych tablic
Niejednoznaczne
```

---

## 7. Główna metryka MT

Do podstawowego mianownika `mt_localization_success_rate` wchodzą tylko invocation:

```text
not cancelled
evaluable = true
evidence available
visible_plate_count = one
```

Znaczenie miary:

> odsetek wywołań MT z jedną widoczną tablicą, w których MT utworzył co najmniej jedną poprawną lokalizację tej tablicy.

Nie nazywaj jej mAP.

---

## 8. Ocena detekcji wewnątrz invocation

Każdy detection row może nadal mieć:

```text
is_plate = true/false
evaluable = true/false
```

Dla invocation z jedną widoczną tablicą:

### Sukces
Co najmniej jeden child row:
```text
mt_status = VALID_QUAD
is_plate = true
```

### Brak detekcji
Brak success i invocation ma:
```text
NO_DETECTION
```

### Błędna geometria
Brak valid success, ale istnieje:
```text
DETECTION_INVALID_QUAD
is_plate = true
```

### False detection
Każdy child:
```text
VALID_QUAD lub DETECTION_INVALID_QUAD
is_plate = false
```
liczyć osobno.

---

## 9. Wielotablicowe invocation

Dla:
```text
visible_plate_count = multiple
```

nie licz invocation do głównej `mt_localization_success_rate`.

Raportuj:
```text
mt_multi_plate_invocations
```

Można nadal pokazywać child detections i false detections.

Nie obliczaj pełnego recall wielu tablic bez GT bbox.

---

## 10. Brak tablicy i niejednoznaczność

Dla:
```text
visible_plate_count = none
```
nie wchodzi do recall-like denominator.

Jeśli MT zwróci nieprawidłową detekcję:
```text
mt_false_detection_count += 1
```

Dla:
```text
visible_plate_count = uncertain
```
nie wchodzi do podstawowej statystyki.

Raportuj:
```text
mt_uncertain_invocations
```

---

## 11. Zachować statystyki MZ i ALPR

Nie zmieniaj:
- exact read MZ,
- incorrect read,
- no read,
- CER,
- correct/incorrect/missing/extra characters,
- subject success,
- consensus repaired result,
- time to first exact,
- AZ fields.

Problem dotyczy tylko jednostki MT.

---

## 12. Zaślepiona weryfikacja GT

Obecny UI pokazuje predykcję przed wpisaniem GT i ma przycisk:

```text
Zgodne z predykcją
```

Do finalnych eksperymentów domyślnie chcemy:

```text
review_mode = blinded_gt_v1
```

---

## 13. UI przed zapisaniem GT

Dopóki subject nie ma zapisanego GT, UKRYJ:
- prediction text,
- consensus prediction,
- character alignment,
- exact/incorrect/no-read outcome,
- przycisk `Zgodne z predykcją`.

Lista rekordów może pokazywać:
```text
MT status
MZ status
```

ale kolumna z tekstem predykcji ma pokazywać:
```text
ukryta do czasu GT
```

Operator widzi obraz/crop i wpisuje GT z obrazu.

---

## 14. UI po zapisaniu GT

Po pierwszym jawnym:
```text
Zapisz GT
```

dla subject:
- predykcje stają się widoczne,
- alignment staje się widoczny,
- automatycznie liczone są statystyki,
- późniejsza poprawa GT nadal działa,
- statystyki przeliczają się po zmianie.

Nie wymagaj reopen.

---

## 15. Tryb diagnostyczny

Można zachować stare zachowanie do debugowania:

```text
review_mode = assisted
```

ale:
- `blinded_gt_v1` ma być domyślny dla nowych research reviews,
- tryb ma być zapisany w sidecarze,
- wynik ma zachować informację o trybie review.

Nie zmieniaj trybu po cichu w połowie weryfikacji.

---

## 16. Schemat review

Do:
```text
alpr.mobile_human_review.v1
```

dodaj addytywnie:
```text
review_mode
```

Wartości:
```text
blinded_gt_v1
assisted
```

Dla starych sidecarów bez pola:
```text
review_mode = assisted
```

Nie fałszuj historii starych review.

Po pierwszej zapisanej decyzji review mode powinien być stały.

---

## 17. Sidecar i SHA

Zachować:
```text
source_archive_sha256
```

oraz atomowy zapis.

Nie modyfikuj `.alprsession`.

---

## 18. Ranking i quality

Do `quality` publikowanej po `COMPLETED` dodaj:
```text
review_mode
```

Nie zmieniaj latency/memory.

Nowe nazwy MT:
```text
evaluable_mt_invocations
mt_successful_invocations
mt_no_detection_invocations
mt_invalid_quad_invocations
mt_multi_plate_invocations
mt_uncertain_invocations
mt_false_detections
mt_localization_success_rate
```

Stare pola `...attempts` można zachować tylko jako aliasy zgodności wstecznej.

Nowy UI/report powinien używać `invocation`.

---

## 19. Backward compatibility

Stare `.alprsession`:
- bez `mt_invocation_id` → jeden attempt = jedno invocation,
- bez `attempts.csv` → MT unavailable jak dotąd,
- bez `review_mode` → assisted.

Stary sidecar ma się otwierać bez niszczącej migracji.

---

## 20. Eksport wyników

`summary.csv` ma zawierać:
```text
review_mode
evaluable_mt_invocations
mt_successful_invocations
mt_no_detection_invocations
mt_invalid_quad_invocations
mt_multi_plate_invocations
mt_uncertain_invocations
mt_false_detections
mt_localization_success_rate
```

`review.json` przechowuje surowe decyzje invocation/operatora, aby statystyki były odtwarzalne.

---

## 21. UI invocation

W tabeli rekordów nie trzeba usuwać child rows.

Dodaj czytelny kontekst:
```text
MT invocation X
  ├─ detekcja 1
  ├─ detekcja 2
  └─ detekcja 3
```

Może to być grupa w Treeview albo wyświetlanie wspólnego `mt_invocation_id`.

Ocena liczby widocznych tablic ma być przypisana do invocation, nie osobno do child detection.

---

## 22. Czego NIE zmieniać

Nie zmieniaj:
- readera ZIP na drugi parser,
- SHA binding,
- atomowego zapisu review,
- MZ alignment,
- CER,
- subject grouping,
- provenance modeli,
- rankingu latency/memory,
- importu starych raportów,
- całego wyglądu Z4 poza koniecznym zakresem.

---

## 23. Testy logiki MT

### T1 — zero detections
```text
1 invocation
0 detections
visible_plate_count = one
```
Wynik:
```text
evaluable_mt_invocations = 1
mt_no_detection_invocations = 1
rate = 0
```

### T2 — one valid detection
```text
1 invocation
1 valid true plate
```
Wynik:
```text
success = 1
rate = 1
```

### T3 — three rows, one invocation
```text
same mt_invocation_id
3 rows
```
Nadal:
```text
evaluable_mt_invocations = 1
```

### T4 — valid + false positive
Jedna prawidłowa + jedna fałszywa:
```text
success = 1
false_detections = 1
```

### T5 — invalid quad only
```text
invalid = 1
success = 0
```

### T6 — multiple visible plates
```text
visible_plate_count = multiple
```
poza denominator.

### T7 — no visible plate + false detection
poza recall denominator, ale:
```text
false_detection += 1
```

### T8 — cancelled
całe invocation poza metryką.

---

## 24. Testy blinded review

### B1
Przed GT:
```text
prediction hidden
consensus hidden
alignment hidden
```

### B2
Po zapisaniu GT:
```text
prediction visible
alignment visible
metrics computed
```

### B3
`Zgodne z predykcją` niedostępne przed GT w `blinded_gt_v1`.

### B4
Stary sidecar bez `review_mode` otwiera się jako:
```text
assisted
```

### B5
`review_mode` trafia do eksportu i quality.

### B6
Autosave GT nadal działa.

### B7
SHA źródła przed i po review identyczny.

---

## 25. Test integracyjny z aktualnym Android samples v2

Użyj paczki zawierającej:
```text
mt_invocation_id
mt_detection_index
mt_detection_count
```

Sprawdź:
```text
reader
grouping
UI
statistics
export
ranking
```

To nadal nie jest finalny terenowy pilot.

---

## 26. Definition of Done

Zadanie zakończone, gdy:
1. MT liczy invocation, nie surowe detection rows.
2. Multi-detection nie zawyża mianownika.
3. Multi-plate nie jest udawane jako pełna klasyczna metryka detekcji.
4. Blinded GT jest domyślne dla nowych research reviews.
5. Predykcja jest niewidoczna przed GT.
6. Stare review i paczki nadal działają.
7. Sidecar nadal jest związany z SHA i atomowy.
8. Ranking publikuje human_review dopiero po `COMPLETED`.
9. Testy regresyjne przechodzą.
10. Agent podaje commit SHA gotowy do pilotażu.

---

## 27. Raport końcowy agenta

Podaj:
```text
1. HEAD przed zmianą,
2. zmienione pliki,
3. model MtInvocationGroup,
4. dokładny denominator MT,
5. obsługę multi-detection,
6. obsługę multi-plate,
7. działanie blinded review,
8. backward compatibility,
9. testy i wyniki,
10. commit SHA gotowy do pilotażu.
```
