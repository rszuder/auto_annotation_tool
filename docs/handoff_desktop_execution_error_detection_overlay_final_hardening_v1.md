# HANDOFF — Desktop: finalne domknięcie przed pilotażem
## `execution_error` MT + jednoznaczne wskazanie ocenianej detekcji

## 0. Cel

Wykonać mały, końcowy hardening desktopowego narzędzia weryfikacji sesji mobilnych przed testem end-to-end i zamrożeniem wersji eksperymentalnej.

Zakres obejmuje tylko dwa problemy wykryte w audycie aktualnego commita:

1. **nie liczyć technicznego błędu wykonania MT jako `NO_DETECTION`,**
2. **jednoznacznie zaznaczać na obrazie wejścia MT, którą konkretną detekcję operator właśnie ocenia.**

Nie przebudowuj mechanizmu review, rankingu, parsera ZIP ani statystyk MZ/ALPR.

---

## 1. Stan bazowy

Repo:

```text
rszuder/auto_annotation_tool
```

Gałąź:

```text
main
```

HEAD podczas przygotowania handoffu:

```text
0382817f0214cecbad4c67ef9a6f39d29610f887
```

Commit:

```text
Licz wywolania MT i dodaj zaslepiona weryfikacje GT
```

Aktualna mobilka użyta jako kontrakt:

```text
repo: rszuder/alpr_mobile_client
main: 355ee2d26358ad0bca3c188546b8d784227ad881
```

Przed pracą:

```text
git status
git diff
git rev-parse HEAD
```

Nie resetuj lokalnych zmian.
Nie zmieniaj historii.
Nie wykonuj force push.

---

## 2. Co już działa i ma pozostać bez zmian

Aktualny desktop ma już:

- `MtInvocationGroup`,
- grupowanie po `mt_invocation_id`,
- walidację `mt_detection_index` / `mt_detection_count`,
- `visible_plate_count = none|one|multiple|uncertain`,
- invocation-level `mt_localization_success_rate`,
- `review_mode = blinded_gt_v1`,
- szkic GT niewidoczny dla metryk przed jawnym zatwierdzeniem,
- `invocation_annotations`,
- SHA binding sidecara,
- immutable `.alprsession`,
- autosave,
- zgodność ze starymi sidecarami,
- statystyki MZ/CER/ALPR,
- publikację `human_review` dopiero po `COMPLETED`.

Nie zmieniaj tych kontraktów poza zakresem opisanym niżej.

---

# 3. Problem 1 — `execution_error` jest obecnie mylony z MT miss

## 3.1. Kontrakt Androida

Mobilka zapisuje w `samples/attempts.csv`:

```text
mt_executed
mt_status
execution_error
```

Android ustawia:

```text
mt_executed = true
mt_status = NO_DETECTION
```

bezpośrednio przed wejściem do:

```text
plateBackend.run(...)
```

Jeżeli backend lub późniejsze dekodowanie zakończy się wyjątkiem, rekord może finalnie wyglądać:

```text
mt_executed = true
mt_status = NO_DETECTION
execution_error = <niepusty opis>
```

To **nie jest brak detekcji modelu**. To jest technicznie nieukończone / błędne wykonanie MT.

---

# 4. Docelowa semantyka błędu wykonania

Dodaj invocation-level stan do `MtInvocationGroup`:

```python
execution_failed: bool
execution_errors: tuple[str, ...]
```

Grupa jest `execution_failed`, jeżeli dowolny child row ma niepuste `execution_error` po trim.

Zachowaj wszystkie różne teksty błędów do diagnostyki. Nie klasyfikuj rodzaju wyjątku na podstawie tekstu.

---

# 5. Nowa statystyka

Dodaj:

```text
mt_execution_error_invocations
```

Znaczenie:

> liczba wykonanych, nieanulowanych wywołań MT, których wykonanie nie zakończyło się poprawnie i dla których zapisano `execution_error`.

Nie mieszaj tego z `mt_no_detection_invocations`.

---

# 6. Mianownik MT po poprawce

`evaluable_mt_invocations` obejmuje invocation tylko wtedy, gdy:

```text
group.executed == true
group.cancelled == false
group.execution_failed == false
invocation annotation evaluable == true
evidence available == true
visible_plate_count == one
```

Czyli:

```text
execution_failed
→ poza mianownikiem
```

---

# 7. Kolejność klasyfikacji invocation

W `calculate_mt_invocations()` preferowana kolejność:

```text
1. cancelled
2. not executed
3. execution_failed
4. visible_plate_count / evaluable / evidence
5. success / no_detection / invalid_quad
```

Nie pozwalaj, aby:

```text
execution_error != ""
+
mt_status = NO_DETECTION
```

skończyło jako:

```text
outcome = no_detection
```

Dla błędu:

```text
outcome = execution_error
included = false
```

---

# 8. False detections przy błędzie wykonania

Jeżeli invocation ma `execution_error`, traktuj całe invocation jako niekompletne technicznie.

Nie wykorzystuj jego child rows do podstawowych statystyk jakości MT.

Nie zwiększaj z takiej grupy:

```text
mt_successful_invocations
mt_no_detection_invocations
mt_invalid_quad_invocations
mt_false_detections
```

Child rows pozostają do inspekcji diagnostycznej.

---

# 9. Completion review a `execution_error`

Invocation z:

```text
execution_failed = true
```

nie powinno wymagać od operatora:

```text
visible_plate_count
is_plate dla dzieci
```

aby zakończyć review.

W `invocation_completion_issues()` failed invocation ma zwracać brak wymaganych decyzji.

---

# 10. UI dla błędu wykonania

W kontekście invocation pokaż:

```text
Wywołanie MT: <id> • błąd wykonania
```

oraz skrócony tekst `execution_error`.

Pełny tekst może trafić do szczegółów.

Dla failed invocation zablokuj `visible_plate_count`, ponieważ nie wejdzie ono do metryki jakości.

---

# 11. Ranking / quality

Po `COMPLETED` publikuj:

```text
mt_execution_error_invocations
```

razem z istniejącymi metrykami invocation.

Nie zmieniaj latency, memory, MZ, CER ani ALPR.

---

# 12. Backward compatibility

Stare paczki bez `execution_error`:

```text
execution_failed = false
execution_errors = ()
```

Nie wymagaj migracji.

---

# 13. Problem 2 — operator nie widzi, którą detekcję ocenia

Aktualny UI pokazuje:

```text
Detekcja 1
Detekcja 2
Detekcja 3
```

i operator oznacza:

```text
To jest tablica
To nie jest tablica
```

Na wejściu MT nie ma jednak graficznego wskazania konkretnej detekcji. Przy wielu kandydatach może więc nie być jasne, którego obszaru dotyczy child row.

---

# 14. Dane dostępne z Androida

Dla child detection Android zapisuje:

```text
plate_left
plate_top
plate_right
plate_bottom
```

oraz dla invocation:

```text
roi_left
roi_top
roi_right
roi_bottom
input_width
input_height
input_scale
input_pad_x
input_pad_y
```

`plate_*` są w układzie źródłowej klatki.

`mt_input_evidence_entry` jest bitmapą letterbox wejścia MT o rozmiarze:

```text
input_width × input_height
```

---

# 15. Mapowanie detekcji na obraz wejścia MT

Użyj:

```text
left_input   = (plate_left   - roi_left) * input_scale + input_pad_x
top_input    = (plate_top    - roi_top)  * input_scale + input_pad_y
right_input  = (plate_right  - roi_left) * input_scale + input_pad_x
bottom_input = (plate_bottom - roi_top)  * input_scale + input_pad_y
```

Dla R0:

```text
roi_left = 0
roi_top = 0
```

Po obliczeniu clamp do:

```text
[0, input_width]
[0, input_height]
```

Jeżeli:

```text
right <= left
lub
bottom <= top
```

zwróć brak poprawnej geometrii.

---

# 16. Nie zgaduj geometrii legacy

Jeżeli brakuje wymaganych pól:

```text
plate_left/right/top/bottom
input_scale
input_pad_x/y
roi_left/top
input_width/height
```

nie wyliczaj boxa.

UI:

```text
Brak geometrii detekcji w tej sesji.
```

---

# 17. Wydziel funkcję mapowania poza Tk

Preferowane miejsce:

```text
ranking/mobile_mt_invocations.py
```

np.:

```python
def detection_box_on_mt_input(row) -> tuple[float, float, float, float] | None:
    ...
```

Funkcja ma być testowalna bez GUI.

---

# 18. Co rysować

Gdy operator wybrał child detection i ogląda `Wejście MT`, narysuj:

- prostokąt `plate_*`,
- etykietę np. `Detekcja 2 / 3`,
- opcjonalnie status `VALID_QUAD` / `DETECTION_INVALID_QUAD`.

Tylko aktualnie oceniana detekcja musi być jednoznacznie wyróżniona.

---

# 19. Box tylko na właściwym obrazie

Nie rysuj boxa na cropie MZ.

Rysuj go tylko na:

```text
mt_input_evidence_entry
```

Jeżeli aktualny obraz to crop:

```text
overlay detection box = OFF
```

---

# 20. Wybór evidence dla child row

Preferuj:

```text
row.mt_input_evidence_entry
```

dla bieżącego child row.

Dopiero przy braku użyj innego dostępnego `mt_input_evidence_entry` z `MtInvocationGroup`.

Nigdy nie używaj cropa jako fallback wejścia MT.

---

# 21. Canvas / resize

Możesz:

- rysować rectangle/text na Canvas,
- albo na kopii PIL przeznaczonej wyłącznie do prezentacji.

Jeżeli box jest liczony w `input_width × input_height`, a obraz jest skalowany i centrowany w Canvas, użyj dokładnie tego samego `display_scale` i offsetu co `PhotoImage`.

Nie zakładaj, że wyświetlany obraz zaczyna się w `(0,0)` Canvas.

---

# 22. `DETECTION_INVALID_QUAD`

Jeżeli bounding box jest dostępny, pokaż go również dla:

```text
DETECTION_INVALID_QUAD
```

Operator musi odróżnić:

```text
rzeczywista tablica, ale błędna geometria
```

od:

```text
fałszywa detekcja
```

---

# 23. `NO_DETECTION`

Dla:

```text
mt_detection_count = 0
mt_status = NO_DETECTION
```

nie ma boxa.

Operator ocenia tylko całe wejście:

```text
none / one / multiple / uncertain
```

---

# 24. `execution_error`

Dla failed invocation można pokazać istniejącą geometrię diagnostycznie, ale:

- nie wymagaj jej oceny,
- nie licz jej do jakości,
- zaznacz invocation jako technicznie nieukończone.

---

# 25. Zachowanie blinded GT

Dodanie boxa detekcji nie może ujawnić OCR przed GT.

Przed `gt_confirmed` nadal ukryte:

```text
prediction
consensus prediction
alignment
exact/incorrect/no-read
```

Geometria detekcji może być widoczna.

---

# 26. Testy `execution_error`

## E1 — backend error wyglądający jak NO_DETECTION

Dane:

```text
mt_executed = true
mt_status = NO_DETECTION
execution_error = RuntimeException
visible_plate_count = one
```

Oczekiwane:

```text
mt_execution_error_invocations = 1
evaluable_mt_invocations = 0
mt_no_detection_invocations = 0
mt_localization_success_rate = None
outcome = execution_error
```

## E2 — błąd + child detection

```text
VALID_QUAD child
execution_error != ""
```

Oczekiwane:

```text
mt_execution_error_invocations = 1
mt_successful_invocations = 0
mt_false_detections = 0
```

## E3 — cancelled + error

Preferowana precedence:

```text
cancelled > execution_error
```

Czyli cancelled invocation nie zwiększa `mt_execution_error_invocations`.

## E4 — legacy

Brak `execution_error`:

```text
execution_failed = false
```

---

# 27. Testy mapowania boxa

## G1 — R0

```text
roi_left=0
roi_top=0
scale=1
pad=0
plate=(100,50,300,150)
```

wynik:

```text
(100,50,300,150)
```

## G2 — ROI

```text
roi_left=200
roi_top=100
scale=2
pad_x=0
pad_y=20
plate=(250,120,350,170)
```

wynik:

```text
(100,60,300,160)
```

## G3 — clipping

Box częściowo poza inputem → clamp.

## G4 — brak pola

Brak `input_scale` → `None`.

## G5 — invalid geometry

Po transformacji `right <= left` → `None`.

---

# 28. Test GUI

W `gui_mobile_sample_review_probe.py` dodaj scenariusz:

1. jedno invocation z trzema detekcjami,
2. wybór drugiej detekcji,
3. `Pokaż wejście MT`,
4. Canvas zawiera oznaczenie aktywnej detekcji,
5. przełączenie na trzecią detekcję zmienia oznaczenie,
6. przełączenie na crop usuwa box,
7. `NO_DETECTION` nie pokazuje boxa,
8. `execution_error` pokazuje komunikat i nie wymaga decyzji do `COMPLETED`.

Nie opieraj testu wyłącznie na screenshot comparison.

---

# 29. Regression tests

Uruchom co najmniej:

```text
python -m pytest   tests/test_mobile_mt_blind_review.py   tests/test_mobile_human_review.py   tests/test_mobile_report_full_rows.py -q
```

oraz:

```text
python tests/gui_mobile_sample_review_probe.py
```

---

# 30. Aktualna paczka Android

Jeżeli dostępna jest `.alprsession` z mobilki:

```text
355ee2d26358ad0bca3c188546b8d784227ad881
```

użyj jej do testu importu.

`execution_error` może być testowany syntetycznie.

---

# 31. Eksport review

`summary.csv` i derived metrics w `review.json` mają zawierać:

```text
mt_execution_error_invocations
```

Nie zapisuj błędu jako decyzji operatora — pochodzi z `attempts.csv`.

---

# 32. Dokumentacja

Zaktualizuj:

```text
docs/mt_invocation_blind_review_hardening.md
```

lub dodaj krótki raport finalnego hardeningu.

Opisz:

- `execution_error` ≠ `NO_DETECTION`,
- precedence cancellation/error,
- mapping boxa source/ROI → letterbox MT,
- box jako pomoc operatora,
- brak wpływu na GT/MZ/CER.

---

# 33. Czego NIE robić

Nie:

- zmieniaj Androida,
- twórz nowego formatu `.alprsession`,
- zmieniaj samples v2,
- modyfikuj source ZIP,
- zmieniaj `subject_key`,
- zmieniaj CER,
- zmieniaj definition of ALPR success,
- odsłaniaj OCR przed GT,
- licz `execution_error` jako model miss,
- licz częściowego failed invocation jako success/false detection,
- rysuj boxa na cropie MZ,
- zgaduj geometrii przy brakujących polach,
- przebudowuj całego Z4.

---

# 34. Definition of Done

Zadanie zakończone, gdy:

1. `execution_error` jest rozpoznawany na poziomie `MtInvocationGroup`.
2. Failed invocation jest poza mianownikiem jakości MT.
3. Failed invocation nie jest `NO_DETECTION`.
4. Istnieje `mt_execution_error_invocations`.
5. Failed invocation nie wymaga ręcznej oceny do ukończenia review.
6. Operator widzi box aktualnie ocenianej detekcji na wejściu MT.
7. Box korzysta z rzeczywistej transformacji ROI → letterbox.
8. Zmiana child row zmienia box.
9. Box nie pojawia się na cropie MZ.
10. `NO_DETECTION` nie ma boxa.
11. Blinded GT nadal działa.
12. Stare paczki i sidecary nadal się otwierają.
13. SHA źródła pozostaje niezmieniony.
14. Ranking publikuje nowy licznik po `COMPLETED`.
15. Wszystkie wymagane testy przechodzą.
16. Agent tworzy jeden czysty commit kandydujący do pilotażu.

---

# 35. Raport końcowy agenta

Podaj:

```text
1. HEAD przed zmianą,
2. zmienione pliki,
3. semantykę execution_failed,
4. precedence cancelled / execution_error,
5. zmianę mianownika MT,
6. nową statystykę,
7. wzór mapowania detection -> MT input,
8. zachowanie UI dla 0/1/N detekcji,
9. wyniki testów,
10. commit SHA gotowy do audytu/pilotażu,
11. ograniczenia.
```

Nie wykonuj jeszcze terenowego pilotażu jako części tego zadania.
Po commicie nastąpi osobny audyt Android ↔ desktop i dopiero potem właściwy test end-to-end.
