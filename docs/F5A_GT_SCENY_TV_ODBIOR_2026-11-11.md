# F5A — jedno GT sceny TV w Z4

Zakres: zwykłe wejście „Przejdź do weryfikacji zdjęć” dla F5A z istniejącym,
zweryfikowanym powiązaniem A2. Odbiór operatora: **NOT_VERIFIED**.

## Przebieg i wykorzystany kod

Lista główna zawiera 10 ekspozycji sesji. Canvas, D, GTZ, PPM, statusy fragmentu
tekstu i geometrii, undo/redo, autosave, zoom oraz pan pochodzą z istniejącego
Z4 (`CanvasReviewEditor`, `PhotoReferenceWindow`, `PhotographCanvasSource`).
Nie powstał drugi silnik rysowania. Warstwa scenowa korzysta z operacji
`PhotoReference`, ale zapisuje wyłącznie istniejący sidecar raportu mobilnego.

A1 jest propozycją treści: identyfikatory tablic, teksty i statusy. Wczytanie
propozycji nie zapisuje oceny ani nie zwiększa licznika. Geometria JPEG jest
usuwana z propozycji CameraX. Operator zatwierdza tablice i czytelność na
wybranej klatce przez Spację. „Brak tablic” jest jawną decyzją. „Dalej” nie
zatwierdza GT. Zmiana GT unieważnia jego zatwierdzenie; historia pozostaje.

## Grupowanie i dane źródłowe

Jednostką jest `exposure_id` z A2, czyli konkretna fotografia w danym pokazie,
nie `scene_event_id`. Powiązanie wywołania wymaga zgodności jego rzeczywistej
klatki, SHA pełnego CameraX, pełnego `source_stamp` oraz przypisania A2.
Osiem zdarzeń mieszanych zachowuje rozdzielenie fotografii na poziomie klatek.
Opóźniony wynik pozostaje przy fotografii widocznej na wejściu modelu.
Nie używa się czasu zakończenia inferencji ani konwersji zegarów PC/Androida.

A2: 36 sesji, 360 ekspozycji, 40 fotografii, 386 zdarzeń i 1281 rzeczywistych
identyfikatorów MT. Desktop tworzy dodatkowo dwie grupy pomocnicze dla anulowanych
prób z pustym `mt_invocation_id` i `mt_executed=false`. Zachowano je jako
diagnostyczne rekordy N/A, bez dopisywania dwóch wykonań MT.

K02: 10 ekspozycji, 10 fotografii, 56 unikalnych klatek / 66 reprezentacji,
44 wywołania MT. Liczba wykonań MZ pochodzi z istniejących liczników źródłowych;
liczba rekordów prób z `mz_executed` jest raportowana osobno.

## Stała reguła wyniku głównego

`f5a_scene_first_input_frame_v1` jest zapisywana z hashem w warstwie GT i eksporcie
przed obliczeniem wyniku ocenionej sceny. To reguła retrospektywna, nie deklaracja
prerejestracji ani rekonstrukcja końcowego napisu wyświetlonego przez Androida.

Wynik główny wykorzystuje pierwszą zweryfikowaną przez A2 klatkę wejściową MT
według `capture_elapsed_nanos`, następnie stabilnego ID klatki. Zachowuje wszystkie
rzeczywiste wywołania ROI tej klatki w kolejności źródłowej, również nieudane.
Reguła nie zależy od GT, poprawności OCR ani późniejszych lepszych wyników.
Brak udowodnionej kolejności albo brak wejścia MT oznacza N/A, nie sukces ani zero.
Domyślna klatka do anotacji jest tą samą klatką. Operator może wybrać inną z
„Klatek telefonu”, lecz nie zmienia to reguły wyniku głównego.

Sukces ALPR wymaga wszystkich tablic GT, poprawnych pełnych odczytów i braku
dodatkowych FINAL. Przy powtarzających się wskazaniach wybierany jest pierwszy
źródłowy odczyt przypisany do danej tablicy, nigdy najlepszy po poznaniu GT.
„Wykryto przynajmniej raz” jest osobnym polem i nie zastępuje wyniku głównego.
Wynik N/A ma własny mianownik; odsetek w ocenialnym podzbiorze nie jest wynikiem
całych 360 ekspozycji, jeśli część scen pozostaje nieocenialna.

## Zastosowanie GT i kwalifikacja metryk

- Treść GT może dotyczyć wszystkich klatek tej samej fotografii potwierdzonej A2.
- Dokładna geometria dotyczy wskazanej klatki CameraX. Ponowne użycie wymaga
  identycznego SHA całego CameraX i wymiarów. A2 `IDENTITY_ONLY` nie jest transformacją.
- Przy dokładnej geometrii używany jest istniejący matcher BBOX IoU ≥ 0,50,
  bez ponownego filtrowania wyników. Pose/NMCE używa istniejącego pomiaru.
- Niepewna geometria, fragment tekstu, niejednoznaczny crop/odczyt i brak dowodu
  czytelności mają jawne N/A. Tekst GT nigdy nie zastępuje predykcji MZ.
- Nie przypisuje się wielu tablic według zgodności OCR. Niejednoznaczne
  przypisania pozostają N/A albo są rozstrzygane jako wyjątki operatora.
- Ręczny wyjątek TP/FP pozostaje operacyjny; nie tworzy dokładnego IoU ani Pose.
- GT poza ROI nie jest FN tego MT. Pokrycie wybranych ROI na klatce referencyjnej
  jest osobnym dowodem potencjalnej straty ALPR, także przy zerowej liczbie ROI.
  Brak MT lub nieudowodniony wynik końcowy nie jest sztucznie przeliczany na FN.

Po zatwierdzeniu nie ma obowiązku oceny każdego MT. „Sprawdź wyjątki” udostępnia
źródłowe wyniki i rozstrzygnięcia PPM. Nierozstrzygnięte przypadki mogą pozostać N/A.
Wszystkie klatki, zdarzenia i wywołania pozostają w indeksie/eksporcie; samoloty
spoza A1 nie tworzą nowej fotografii GT. Nie ocenia się pojazdów ani nie edytuje ROI.

## Trwałość i eksport

Źródło decyzji: `provenance.f5a_scene_gt_v1` w istniejącym `*.review.json`.
Warstwa zawiera wersję schematu, serię/sesję, SHA A1/A2 i archiwum, klatkę
reprezentatywną, politykę stosowania GT, wersje stanów, kursor undo/redo,
zatwierdzenia i wyjątki. Starsze pola ocen oraz `f5a_assisted_gt_v1` pozostają
bez migracji i nadpisywania. Samo otwarcie lub oglądanie nie tworzy oceny.

Wspólny eksporter `MobileReviewSession.export` dodaje:

- `f5a_scene_gt.json` — stan GT, wszystkie wyniki i mianowniki oraz dowody A2;
- `f5a_scenes.csv` — jeden wiersz na ekspozycję;
- `f5a_calls.csv` — jeden wiersz na rzeczywisty identyfikator MT;
- `f5a_scene_export_manifest.json` — SHA plików i powiązania źródeł.

Starsze pliki eksportu zachowują swoje znaczenie. Wyniki nowego toru scenowego
należy odczytywać z plików `f5a_*`, nie z historycznych podsumowań per MT.

## Odbiór K02

1. Zamknij stary weryfikator; uruchom aktualny kod Desktop. Bez ponownego importu.
2. Raporty z telefonu → R1 / r02 / BLOK_B / K02 → „Przejdź do weryfikacji zdjęć”.
3. Wybierz „Zdjęcie 1 z 10”. Duży obraz to CameraX; miniatura A1 jest referencją treściową.
4. Wybierz tablicę i użyj D do obrysu. GTZ zawiera propozycję A1; popraw ją lub
   wybierz PPM → fragment/nieczytelność. Niepełną geometrię oznacz przez istniejące PPM.
5. Spacja zatwierdza GT tej sceny i uruchamia analizę. Dalej przechodzi do kolejnej
   sceny bez automatycznego zatwierdzania. Negatywna scena: „Brak tablic”.
6. Opcjonalnie „Sprawdź wyjątki”: PPM na wskazaniu → tablica GT / błędne / N/A.
   Czytelność odczytu na innej klatce kwalifikuje się osobno; nie trzeba przerysowywać GT.
7. Sprawdź zamknięcie, wznowienie i eksport. Potwierdzenie wygody GUI pozostaje
   decyzją operatora: **NOT_VERIFIED**.

## Pliki zmiany

Nowe adaptery: `ranking/mobile_f5a_scene_gt.py`, `gui/mobile_f5a_scene_gt.py`.
Integracja: `ranking/mobile_human_review.py`, `ranking/mobile_manual_frame_guard.py`,
`gui/z4_mobile_sample_review.py`, `gui/z4_photo_reference.py`, `gui/mobile_canvas_editor.py`,
`gui/z4_mobile_report_browser_ux.py` (podgląd licznika zapisanych GT scen).
Testy: `tests/test_f5a_scene_gt.py`. A1/A2/archiwa i dane produkcyjne nie są edytowane.

## Wyniki zakończonych sprawdzeń

Łącznie **173 różne przypadki PASS, 0 nierozwiązanych FAIL, 3 SKIP** w wybranym
zakresie, po naprawie wykrytych błędów. To nie jest deklaracja uruchomienia całego
repozytoryjnego zestawu testów.

| Zakres | Wynik |
|---|---:|
| Nowy tor scenowy, w tym natywny Tk i pełny indeks 36 sesji | 17 PASS |
| A1/Canvas, zwykły ręczny Z4, metryki F4 i natywne zatwierdzanie F4 | 134 PASS, 3 SKIP |
| Zachowanie poprzedniego adaptera i zapisów A3 | 5 PASS |
| Przeglądarka raportów i jej dotychczasowe statusy | 17 PASS |

Trzy SKIP dotyczą opcjonalnych testów starszych/prywatnych migawek A1, dla
których nie podano zmiennych fixture. Odczyt rzeczywistego A1, A2 i wszystkich
36 archiwów sprawdzono oddzielnie w testach nowego toru. Testy zapisujące
korzystały wyłącznie z prywatnych kopii albo danych syntetycznych.

Testy nowego toru obejmują 360 ekspozycji, 1281 identyfikatorów MT (1280
przypisanych do fotografii, 1 N/A), 8 zdarzeń mieszanych, dwa zachowane rekordy
przed MT oraz dwie reprezentacje klatki z samolotami spoza GT. Zmiana czasu
zakończenia inferencji nie zmienia powiązania wejścia z fotografią. Natywny Tk
sprawdził prawdziwe zdarzenia klawiatury/myszy, rysowanie, GTZ, nieczytelność,
fragment tekstu, geometrię częściową, NO_PLATES, wyjątki PPM, zmianę aktywnej
fotografii, zoom, dopasowanie, zapis, wznowienie z wejścia przeglądarki i eksport.

Kontrola SHA-256, rozmiaru i mtime: **1949 chronionych plików bez zmian**.
Nie wykonano commit/push, migracji ocen, nowego pomiaru ani inferencji.

Dowody lokalne tego wykonania:
`C:\Users\48572\AppData\Local\Temp\f5a_scene_gt_lrwfjg9v`:
`regression1.log`, `final_focused.log`, `final_scene_browser.log`,
`final_scene_browser.xml`, `final_integrity.json`, `task_only.patch`.
Pierwszy log zachowuje wykryty błąd eksportu; końcowy test wejścia przeglądarki,
wznowienia i eksportu przeszedł po poprawce. Zrzuty Tk pokazują prywatne dane
testowe, nie produkcyjne oceny.

**Odbiór GUI operatora: NOT_VERIFIED.** Po domknięciu F5A następnym etapem jest
F6; F5B pozostaje pominięte. Żadnego nowego eksperymentu nie uruchomiono.
