# SPEC_MULTI_PLATE_EVAL_ROI_V1 — kontrakt danych i ewaluacji ALPR

**Wersja robocza 2026-10-18 / pierwszy krok P0.** Jest to specyfikacja wdrożeniowa, **nie zatwierdzony protokół naukowy**. Nie przyznaje zgody na badanie `final_test`, zmianę modeli, GT ani historii eksperymentów. Zaplanowane kroki patrz handoff AKT-13.

## 1. Co rzeczywiście istnieje

- `samples/attempts.csv`: `mt_invocation_id`, `source_sequence`, `source_timestamp_nanos`, `source_timestamp_domain`, `visual_epoch`, `camera_transform_generation`, `roi_policy`, `roi_left/top/right/bottom`, `input_width/height`, `input_scale`, `input_pad_x/y`, `mt_detection_count/index`, `mt_status`, `mt_input_evidence_entry`.
- W `alpr_session_20261017_204443.alprsession`: 8 wywołań MT, z ROI R0 `(0,0,480,640)`, 8 dowodów wejścia MT 512×512, 7 detekcji i 7 cropów. Wszystkie ROI są zapisane **per wykonane wywołanie MT**, nie na każdy frame kamery.
- `samples/evidence/*.jpg` jest wejściem MT **po crop/resize/letterbox**; nie wolno traktować go jako potwierdzonego oryginalnego obrazu źródłowego dla R1/R2. W historycznych ZIP nie ma niezależnego obrazu całej klatki.
- `multi_plate_v1` to ręczne przypisania operatora na obrazie wejścia MT. Nie ma niezależnego zamrożonego GT wszystkich tablic całego kadru ani formalnego matching polygon IoU.

## 2. Niezależne jednostki

1. `FRAME`: klucz `(session_id, source_sequence, source_timestamp_domain, source_timestamp_nanos, visual_epoch, camera_transform_generation)`. Dwa wywołania na tej samej klatce muszą współdzielić ten klucz; brakujące pola wykluczają automatyczne połączenie.
2. `MT_INVOCATION`: unikalne `mt_invocation_id`; dany ROI w źródłowych współrzędnych; 0..N surowych wyników; `mt_executed=false` ≠ `mt_status=NO_DETECTION`.
3. `MT_DETECTION`: `(mt_invocation_id, mt_detection_index)` z oryginalną geometrią/score i stanem filtracji. Indeks 0 nie oznacza TOP-1 MZ.
4. `GT_PLATE`: stały `gt_plate_id` w FRAME, quad w źródłowej orientacji i tekst; rewizje oraz pochodzenie niezależnego GT. Powiązanie nie jest geometrią GT.
5. `MZ_ATTEMPT`: wskazuje konkretną detekcję MT i wynik wykonania lub NOT_RUN; nie generuje CER dla niewykonanej inferencji.

## 3. Kontrakt Androida v2 — do wdrożenia po audycie bieżącego kodu

- Osobny `samples/source_frames/{frame_key}.jpg` (lub bezstratny format) z oryginalnym logicznym pełnym obrazem **tego konkretnego wywołania** oraz `sha256`, `width`, `height`, orientacją, `mirrored`, `pixel_coordinate_space` i `frame_key`. Zapis dla badań w ograniczonym próbkowaniu, z raportem narzutu, nie co klatkę i bez nowej inferencji.
- Ścieżka do oryginalnego pełnego obrazu **różna** od `mt_input_evidence_entry`; manifest rozróżnia oba typy. Brak → `NO_FULL_SOURCE_FRAME_EVIDENCE`.
- Ścisła transformacja source-frame→ROI→input 512×512→detekcje. `roi_left/top/right/bottom` w źródle, letterbox `scale,padX,padY`; jawny obrót/lustrzane odbicie. Nie zgadywać odwrotnej transformacji przy brakach.
- Zapis wszystkich detekcji MT przed wyborem celu MZ, osobny trace decyzji filtracji/selektora `TOP-1`, status MZ `EXECUTED/NOT_RUN/UNAVAILABLE` dla wskazania.
- Wersja schematu i testy wstecznego importu; historycznych archiwów **nie migrować in-place**.

## 4. Desktop i Z2

- Weryfikacja odbywa się na **całej klatce**, nie na pojedynczej detekcji; GT01..GTn w niezależnym modelu Z4. Adapter interakcji Z2: hit-testing ramek/narożników, zaznaczenie, drag całego quad, dodaj, usuń wybrany obrys, undo/redo. Bez bezpośredniej zależności od `annotations.xml` Z2.
- Prawe pole zawsze dotyczy **wybranego GT**: obrys, tekst, własne decyzje i stabilny GT ID, powiązana predykcja MT (id/index), wykonanie MZ lub brak, lokalizacja względem ROI.
- Jedna klatka może mieć wiele MT invocations: ROI warstwa tylko do odczytu dla każdego wywołania, dowiedzione granice i legenda; gdy brak pełnego obrazu, wyraźny komunikat, nie „pełna klatka”.
- Dwa obrysy na *jedną detekcję*: model MT niezmienny i jedna aktualna korekta operatora. Wiele **różnych tablic** może być równocześnie na klatce, identyfikatory nie są indeksami sortowania.
- Dla niezależnego GT wymagane osobne, naprawdę **zaślepione** rysowanie przed pokazaniem predykcji. Anotacja po ujawnieniu modelu pozostaje `ASSISTED_DIAGNOSTIC` i nie może być przemianowana na niezależną bez nowego przebiegu.

## 5. Warunki formalnej ewaluacji — domyślnie blokada

- Zamrożony protokół `ALL_PLATES` lub `TARGET_PLATE`, który jednoznacznie określa populację i cel; uzgodniony próg polygon IoU i reguły dopasowania 1:1 (późniejsze dopasowanie nie może zależeć od kolejności kliknięć). Próg **do zatwierdzenia**, nie domyślnie 0.5 w kodzie.
- Dla każdej tablicy GT dowód pełnej klatki oraz kompletnego GT z kwalifikacją widoczności. `OUT_OF_MT_ROI` nie jest FN danego wywołania. Częściowe pokrycie → `PARTIAL_ROI_COVERAGE` do ustalenia, nie domysł.
- `MT_EXECUTED` z `NO_DETECTION` i jedną kwalifikującą się GT wewnątrz ROI może stanowić FN dopiero z prawidłowym niezależnym GT; `MT_NOT_RUN` nigdy nie jest FN modelu.
- Przypisanie operatora ≠ wynik automatycznego matching geometrycznego. Brak pozytywnych dowodów → `NOT_EVALUABLE` z kodem i mianownikiem `null` (nie 0). Deduplikacja kilku ROI w jednym FRAME jest osobna od wyniku per invocation.
- Mikro-CER `sum(edit_distance)/sum(GT_characters)` tylko z wykonanym MZ i uprawnionym GT tekstu; `MZ_NOT_RUN` nie wchodzi do CER. Wynik E2E ma oddzielny mianownik i decyzję, czy obejmuje wszystkie tablice czy jeden cel.
- Raportowanie: osobno **przypisania asystowane operatora** i **formalna jakość**. Wyniki nigdy nie są sumowane w jedną liczbę.

## 6. Status pierwszego patcha `Z4MOBSAFE030`

- `mobile_roi_evaluation.py`: audyt konkretnego wywołania, ROI, transformacji i tego, czy dowód jest tylko wejściem MT. Nigdy nie nazywa wejścia 512×512 pełną klatką.
- `mobile_multi_plate_verification.py`: istniejąca liczba przypisań jest zachowana jako `operator_diagnostic`, a formalne `tp,fp,fn,gt_plates` są `null` z `formal_status=NOT_EVALUABLE`; brak nowego pomiaru modelu.
- `mobile_scientific_review.py`: raport GUI/Markdown opisuje diagnostykę i stan blokady bez mylących naukowych TP/FP/FN. Eksport JSON zawiera kody przyczyn i kontekst ROI.
- Z4 i Android nadal nie mają pełnego edytora per FRAME; nie nazywać P1 ani testów na telefonie wykonanymi. Nie zmienia się `READY_FOR_EVALUATION` formularza ani surowych danych.

## 7. Następny krok P0/P1

1. Uruchomić read-only audyt **bieżącego lokalnego Androida**, potwierdzić dokładne miejsce zmiany `source_frame`, `Detection`, `ResearchAttemptBatch`, `ResearchSessionStore`, `ResearchArchive`; porównać z paczką 17.10.
2. Osobny SHA-gated patch Android dla pełnej klatki, źródłowych wymiarów/orientacji/SHA oraz wszystkich surowych MT + selektorów; Java JVM test i test urządzeniowy A12, narzut pamięci/latencji.
3. Desktop importer v2 + transformacje + wieloramkowy adapter Z2; dopiero potem podpisany protokół i formalne metryki.
4. Odbiór z dowiedzioną klatką zawierającą co najmniej 5 tablic i R0/R1, dwa ROI na tej samej klatce, MZ=1, brak klatki, brak dowodu GT, `NO_DETECTION`, `NOT_RUN`, umyślne ROI poza granicą, odwrócona orientacja i kilku detekcji jednej tablicy.
