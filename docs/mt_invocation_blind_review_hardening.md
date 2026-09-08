# MT invocation i zaślepione GT — raport wdrożenia

## 1. Baza

HEAD przed zmianą: `3f66c4be68846b139d78a24a3a1ac1c747d30781`, gałąź `main`, czyste drzewo.
Kontrakt: `handoff_desktop_mt_invocation_blind_review_hardening_v1.md`.
Sprawdzono aktualne kolumny Android samples v2 oraz `ResearchAttemptBatch` i `AcquisitionAttemptRecord`.

## 2. Pliki

- `ranking/mobile_mt_invocations.py`: nowy model, walidacja grup i statystyki MT.
- `ranking/mobile_human_review.py`: indeks wywołań, decyzje operatora, tryby, szkice/GT i eksport.
- `ranking/mobile_package_experiments.py`: tryb review w pochodzeniu publikowanej jakości; struktura rankingu bez przebudowy.
- `ranking/__init__.py`: eksport `MtInvocationGroup`.
- `gui/z4_mobile_sample_review.py`: zaślepienie, jawne GT, wspólny kontekst MT i ocena liczby tablic.
- `gui/z4_mobile_report_browser.py`: opis nowej jednostki MT i tryb weryfikacji w jakości.
- `tests/test_mobile_mt_blind_review.py`: testy hardeningu; aktualizacja istniejących testów review i próby GUI.
- Dokumentacja: kopia audytu, niniejszy raport, odnośnik w opisie bazowej weryfikacji.

## 3. MtInvocationGroup

Grupy powstają raz dla całej sesji, po odczycie istniejącego readera. Klucz to `mt_invocation_id`,
a przy jego braku `attempt_id`. Tożsamość nie zależy od OCR, konsensusu ani GT.
Grupa zawiera sesję, scenę, zbiór subjectów, sekwencję i czas wejścia, geometrię ROI/input,
referencje dowodów wejścia, rekordy detekcji, liczbę detekcji i stan wykonania/anulowania.
Jedna grupa może obejmować kilka subjectów. Grupowanie nie zmienia tożsamości samych subjectów.

Sprzeczności session/scene/visual epoch/camera generation/sequence/timestamp/ROI/input powodują błąd.
Liczba detekcji musi być jednakowa, a indeksy unikalne i kompletne: `0..N-1`.
Wywołanie z zerową liczbą detekcji ma jeden rekord bez indeksu detekcji.
Brak obu pól ordinal/count jest zgodnym wstecznie wariantem; częściowe lub sprzeczne pola nie są ignorowane.

Dowód liczby tablic pochodzi z `mt_input_evidence_entry`. Dla starszego formatu można użyć
pełnego obrazu `samples/evidence/...`, jeżeli nowego pola nie ma. Sam crop tablicy nie zastępuje obrazu wejściowego.
Android może zapisać wspólne wejście pod różnymi nazwami dla dzieci — zachowywane są wszystkie referencje,
a UI w pierwszej kolejności pokazuje dostępny plik. Nie wybiera arbitralnie tożsamości/geometrii pierwszego dziecka.

## 4. Dokładny mianownik MT

`evaluable_mt_invocations` obejmuje każde wywołanie dokładnie raz, gdy:

- backend MT był wykonany,
- żaden rekord grupy nie jest stale/cancelled,
- żaden rekord grupy nie zawiera niepustego `execution_error`,
- operator oznaczył całe wejście jako `visible_plate_count=one` i `evaluable=true`,
- dowód wejścia jest dostępny w archiwum.

`mt_localization_success_rate = mt_successful_invocations / evaluable_mt_invocations`.
Brak mianownika daje wynik niedostępny. Ta miara nie jest mAP ani pełnym recall wielu tablic.
Ocena wejścia MT jest niezależna od tego, czy nadano transkrypcję GT subjectowi.

## 5. Wiele detekcji

Sukces to co najmniej jedna niepominięta detekcja `VALID_QUAD` oceniona jako rzeczywista tablica.
Trzy poprawne detekcje w jednej grupie dają jeden sukces i jeden element mianownika.
Brak sukcesu + `NO_DETECTION` daje jedno wywołanie bez detekcji. W przeciwnym razie
`DETECTION_INVALID_QUAD` ocenione jako tablica daje wywołanie z błędną geometrią.
Fałszywe detekcje liczone są osobno, per dziecko, także gdy inne dziecko tej samej grupy daje sukces.
Wywołanie z samymi fałszywymi detekcjami nie daje sukcesu. `none` oznacza, że zwrócone detekcje są fałszywe.

## 6. Wiele tablic

Ocena `multiple` jest wspólna dla całego wywołania, także w widokach różnych subjectów.
Grupa nie wchodzi do głównego mianownika i zwiększa `mt_multi_plate_invocations`.
`uncertain` zwiększa osobny licznik niejednoznacznych wywołań; `none` również nie wchodzi do mianownika.
Nie powstaje oszacowanie recall wielu tablic bez GT bbox.

Nowe pola raportu: `evaluable_mt_invocations`, `mt_successful_invocations`,
`mt_no_detection_invocations`, `mt_invalid_quad_invocations`, `mt_multi_plate_invocations`,
`mt_uncertain_invocations`, `mt_false_detections`, `mt_localization_success_rate`.
Stare nazwy liczników pozostają wyłącznie aliasami kompatybilności. UI używa wywołań.

## 7. Blinded review

Nowy sidecar: `review_mode=blinded_gt_v1`. Przed pierwszym jawnym zatwierdzeniem GT:

- kolumna predykcji pokazuje „ukryta do czasu GT”,
- nie ma tekstu predykcji/konsensusu, dopasowania ani wyniku exact/incorrect/no-read,
- przycisk „Zgodne z predykcją” jest ukryty, a jego handler nie pozwala przepisać predykcji,
- status MT pozostaje widoczny; status MZ jest ukryty, ponieważ może zdradzać brak odczytu.

Autosave po 750 ms oraz zapis przy zmianie tablicy, innych akcjach i zamykaniu zachowują
`draft_ground_truth`. Szkic nie staje się GT używanym do metryk.
„Zapisz GT” / Enter jawnie zapisuje GT z `gt_confirmed=true`, odsłania predykcje i przelicza wyniki
bez ponownego otwierania okna. Kolejne korekty GT nadal korzystają z autosave.
Wyczyszczenie GT ponownie ukrywa predykcje. Przełączenie na inną, nieocenioną tablicę usuwa poprzednie porównanie.

Tryb diagnostyczny `assisted` można wybrać jawnie w „Sesja i modele” przed rozpoczęciem decyzji.
Po pierwszym zapisie danych decyzji/szkicu tryb jest zablokowany w UI i domenie.
Tryb jest przechowywany w sidecarze, `review.json`, `summary.csv` oraz jakości publikowanej po `COMPLETED`.

## 8. Zgodność i zachowanie danych

Sidecar bez `review_mode` odczytywany jest jako `assisted`; otwarcie nie nadpisuje jego pliku.
Brak `mt_invocation_id` daje grupowanie per `attempt_id`; brak `attempts.csv` pozostawia MT niedostępne.

Dawne `plate_visibility=visible` nie dowodzi, że w całym wejściu była dokładnie jedna tablica,
nawet gdy zapisano tylko jedną detekcję. Dlatego nie jest automatycznie zamieniane na `one`.
Ukończone historyczne review zachowuje status i swoje decyzje, ale takie grupy nie wchodzą do nowej
głównej miary MT; są oznaczone `decision_source=legacy_cardinality_unknown`.
W starszym review w toku operator uzupełnia nową ocenę wejścia. Jawne pominięcia są zachowywane.
Metadane `mt_review_policy` zachowują pochodzenie tej zgodności także po kolejnym zapisie.

Atomowy zapis, SHA binding, oryginalna `.alprsession`, parser ZIP i provenance pozostają zachowane.
Decyzje wywołań są zapisane w `invocation_annotations`, oddzielnie od `attempt_annotations` dzieci.
Logika MZ/CER i pola ALPR/czas/AZ pozostają bez zmian dla tego samego zatwierdzonego GT i ocen dzieci.
W trybie blinded nowy szkic celowo nie daje jeszcze podstaw do obliczeń MZ.
Quality trafia do rankingu dopiero po ukończeniu. Latency/memory pozostają bez zmian.

## 9. Testy

```text
python -m pytest tests/test_mobile_mt_blind_review.py tests/test_mobile_human_review.py tests/test_mobile_report_full_rows.py -q
python tests/gui_mobile_sample_review_probe.py
```

Zakres: T1–T8; spójność geometrii/tożsamości; indeksy, liczby i kompletność dzieci;
grupa przecinająca subjecty; fallbacki; pełne wejście vs crop; B1–B7; blokada trybu;
stare sidecary; eksport/quality/review mode; niezmienność SHA; regresja MZ, CER, ALPR, czasu i AZ.

Natywna próba korzysta z syntetycznej paczki o aktualnych kolumnach samples v2.
Sprawdza trzy detekcje jednego wywołania, osobne wywołanie bez detekcji, mianownik równy 2,
zaślepiony autosave, jawne GT, przełączanie tablic, starszy tryb assisted, eksport, ranking i reopen.
Zapisy są ograniczone do `output/mobile_sample_review_audit`; nie wykonuje terenowego pilotażu.
Wyniki: **68 testów przeszło**; natywna próba zakończona z `errors: []`.

## 10. Commit pilotażowy

SHA końcowego commita jest podane w odpowiedzi końcowej agenta. Wdrożenie przygotowuje desktop
do pilotażu; nie zastępuje zebrania i oceny rzeczywistej sesji terenowej.

Końcowe rozdzielenie błędów wykonania MT od braków detekcji oraz ramki aktywnej detekcji
opisuje [raport finalnego hardeningu](execution_error_detection_overlay_final_hardening.md).
