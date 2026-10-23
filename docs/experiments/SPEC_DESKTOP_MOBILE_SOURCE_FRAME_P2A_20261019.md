# Desktop P2A — podgląd pełnej klatki Android MT i rzeczywiste ROI

**Data:** 2026-10-19
**Etap:** `DESKTOP_MOBILE_SOURCE_FRAME_P2A`
**Status:** implementacja patcha Desktop; odbiór na Windows i rzeczywistej sesji oczekuje.
**Źródło:** nowy kontrakt Android `samples/frames/` (Android P1), po udanym teście instrumentacyjnym 3/3 oraz audycie nowej sesji R0 (8 wywołań MT, 9 detekcji i 8 pełnych klatek).

## Cel

Pokaż **dokładnie tę bitmapę pipeline'u, która istniała tuż przed wycięciem ROI**, z nieedytowalną ramką ROI oraz **wszystkimi zachowanymi obrysami MT Pose dla jednego wywołania modelu**. Operator może wybrać detekcję kliknięciem w kontur. To nie jest jeszcze anotator niezależnego GT całej klatki.

## Implementacja

- Nie modyfikujemy `mobile_package_experiments.py`; jej aktualna suma SHA jest wymaganą kontrolą środowiska, ponieważ pomocniczy czytnik korzysta z istniejącej walidacji ZIP.
- Nowy moduł `mobile_source_frame_roi.py` odczytuje tylko zadeklarowany wpis `samples/frames/*.jpg`, przez wspólny zweryfikowany indeks ZIP i ograniczenia wielkości po dekodowaniu.
- Każda klatka wymaga pól `source_frame_entry`, `source_frame_status=WRITTEN`, `source_frame_expected=true`, `source_frame_coordinate_space=mt_source_bitmap_xy`, `source_frame_origin=pipeline_bitmap_before_roi`, `source_frame_width_px`, `source_frame_height_px`.
- Wszystkie próby w `mt_invocation_id` muszą odnosić się do *tej samej* klatki, jej `source_sequence`, `source_timestamp_nanos`, rozmiaru i ROI. Rozbieżność → **brak zweryfikowanego widoku** zamiast domysłu.
- ROI pochodzi wyłącznie z `roi_left/top/right/bottom` na bitmapie źródłowej. Weryfikujemy wymiary zdekodowanego JPEG. Nie wolno użyć rozmiaru sieci 512×512 ani pozycjonowania ROI z innego wywołania.
- Oryginalna geometria Pose to `mt_pose_corners_norm` plus `mt_pose_coordinate_space=source_frame_normalized_v1` i `mt_pose_corner_order=TL_TR_BR_BL`. Brak poprawnych czterech punktów → brak obrysu; **nigdy nie rysujemy BBOX jako zastępczej Pose**.
- Część obrazu poza ROI jest przyciemniona. ROI i tablice są wyraźnie rozróżnione: złota ramka obszaru MT i błękitne polygony detekcji.
- Na pasku zdjęcia pojawia się `Cała klatka + ROI` / `← Wejście MT`. W starych sesjach bez klatek przycisk nie jest dostępny, a poprzednia weryfikacja działa bez zmian.
- Źródłowy widok jest **tylko do odczytu**: bez edycji GT, korekty geometrii i metryk. `D` nie rozpoczyna tu rysowania. Kliknięcie MT wybiera odpowiadający mu rekord z zachowaniem pełnej klatki i zoomu.

## Granice naukowe

- Nigdy nie nadpisywać Android `alprsession`, historycznych `*.review.json`, GT, modeli, predykcji i mierzonych czasów.
- Weryfikacja ROI nie daje automatycznie prawdziwych TP/FN. Osobny patch Z4MOBSAFE030 nadal blokuje formalne TP/FP/FN bez pełnych dowodów, niezależnego GT i reguły dopasowania.
- Widok zawiera **wszystkie zapisane MT Pose**, nie wszystkie rzeczywiste tablice na klatce. Pominięte tablice GT będą edytowane dopiero w P2B.
- Źródłem jest bitmapa po transformacjach pipeline'u, **nie surowy sensor aparatu**.

## Plan odbioru na Windows

1. `--check` ma pokazać zgodny SHA dla istniejącego `z4_mobile_sample_review.py` i zależności czytnika.
2. `--apply`, kopia bezpieczeństwa i testy regresyjne `pytest` (P2A + 027/028/029 + 030).
3. Otworzyć sesję `alpr_session_20261019_012023.alprsession`, przejść do obserwacji z dwiema detekcjami jednego MT (wywołanie kończące się `a00000006`).
4. Kliknąć `Cała klatka + ROI`: pełny obraz 480×640, jedna ramka ROI R0 `(0,0,480,640)`, dwie odrębne Pose MT oznaczone MT 1 i MT 2.
5. Kliknięcie MT 2 wybiera detekcję 2, ale zachowuje obraz pełnej klatki. Po powrocie do `Wejście MT` możliwa jest standardowa weryfikacja jednej detekcji.
6. Przetestować starą sesję bez `samples/frames/`: GUI i ręczny edytor dotychczasowy działają bez regresji.
7. Sprawdzić przypadek niezgodnego ROI/rozmiaru: zablokowany podgląd bez fałszywej geometrii.

## P2B — osobny etap, jeszcze NIEWYKONANY

Zaadaptować pełnoklatkowy **anotator GT i prezentację wielu tablic z Z2**, z identyfikatorem `GT01...`, niezależnymi numerami, zaznaczaniem, przesuwaniem rogów, dodawaniem/usuwaniem oraz wersjonowaniem sidecara per klatka/invocation. Niezależny GT nie może odziedziczyć trybu asystowanego bez jawnego oznaczenia provenance. Dopiero potem rozliczenie pokrycia ROI i formalne TP/FP/FN wg IoU i polityki matchingu bez nadinterpretacji. **W Androidzie** wykonać osobny test częściowego ROI (nie tylko R0) przed formalną oceną selekcji.
