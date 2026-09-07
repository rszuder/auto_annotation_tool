# Czasy zatwierdzania T06 — 2026-09-07

Zbadano zatwierdzenie i przejście do E1 następnej iteracji na danych projektów `demo`, `pisto` oraz `train_yolo26n_pose`. Testy podstawiały stan wejściowy i odpowiedź na modal decyzji; nie wykonywały treningu. Zapisy kierowano do `output`, a zapis do oryginalnych projektów blokował mechanizm audytowy procesu.

## Wyniki

Poniższe pomiary lokalne wykonano z profilerem. Nie obejmują uruchomienia aplikacji ani czasu użytkownika na podjęcie decyzji. Profiler zwiększa koszt szczególnie pętli Python; wyniki służą porównaniu przyczyn przed i po zmianie, nie są gwarancją czasu na innym komputerze. Całość GUI obejmuje obsługę akcji, przygotowanie iteracji, odświeżenie grafu i krótki okres stabilizacji pętli zdarzeń.

| Scenariusz i zakres | Przed | Po |
| --- | ---: | ---: |
| `demo`, IT2 → IT3, bez treningu, nowe wejście — całe przejście GUI | 24,115 s | 1,348 s |
| Najdłuższa przerwa w obsłudze zdarzeń GUI w tym scenariuszu | 18,627 s | 0,581 s |
| `pisto`, IT11 → IT12, wybór 200 obrazów z dużej puli — backend | 99,165 s | 4,957 s |
| `train_yolo26n_pose`, IT1 → IT2, manifest 9087 obrazów roboczych — backend | 23,707 s | 1,690 s |

Końcowa macierz GUI:

| Wariant | Callback zatwierdzenia | Całe przejście | Najdłuższa przerwa zdarzeń |
| --- | ---: | ---: | ---: |
| Demo IT2 → IT3, znaki, bez treningu, nowe wejście | 0,274 s | 1,348 s | 0,581 s |
| Demo IT2 → IT3, tablice, bez treningu, nowe wejście | 0,285 s | 1,464 s | 0,813 s |
| Demo IT2 → IT3, po treningu, handler Z4 | 0,308 s | 1,922 s | 0,652 s |
| Pisto IT11 → IT12, kolejnych 200 obrazów z puli | 0,098 s | 3,575 s | 0,259 s |
| Train IT1 → IT2, przekazanie 9087 obrazów roboczych, tablice | 0,360 s | 2,420 s | 0,364 s |
| Demo IT2, anulowanie | 0,017 s | 0,408 s | 0,051 s |

W wariancie po treningu użyto produkcyjnej funkcji zakończenia Z4 z podstawionym gotowym stanem i pominięciem niezwiązanych kontrolek treningu. Pozostałe pomiary GUI używały rzeczywistego okna aplikacji, grafu i Z2. Warianty wejścia `new_input` i `reuse_input` wymuszano w testowej odpowiedzi modala; nie zmieniano rzeczywistych aktywnych iteracji projektów.

## Przyczyny i zmiany

1. Graf był odświeżany sześć razy podczas jednego przejścia. Generowanie tokenu zbioru i liczenie obrazów wykonywały ponad 160 tys. sprawdzeń plików. Dodano wspólny indeks nazw i liczników oparty na `os.scandir`; ponowny odczyt sprawdza znaczniki katalogów, również podkatalogów. Dodanie, usunięcie lub zmiana nazwy z zewnątrz unieważnia wynik. Token zachowuje wcześniejszy format i zasady normalizacji nazw.
2. Zakończenie T06 przebudowywało jeszcze graf starej iteracji. Usunięto ten pośredni etap. Nowy E1 odświeża istniejący kontener w trybie lekkiego otwarcia, bez dodatkowych opóźnionych pełnych przebudów.
3. Reset niewidocznego Z2 wyszukiwał stare runy i sprawdzał ich eksport, co w osobnym pomiarze zajęło 6,25 s. Nadal zerowany jest stan roboczy Z2; odświeżanie jego przycisków następuje podczas wejścia do modułu.
4. Planer dla 200 obrazów wykonywał 1 755 500 wywołań oceny kandydata. Teraz aktualizuje wyniki w tablicach NumPy; bliskie wyniki i remisy rozstrzyga dotychczasowa funkcja skalarna. Skanowanie kandydatów korzysta z metadanych wpisów katalogu zamiast wielokrotnie rozwiązywać każdą ścieżkę.
5. Przekazywanie 9087 obrazów wykonywało ponad 27 tys. `Path.resolve`, w tym dla nieistniejących logicznych celów nowej iteracji. Katalogi nadrzędne rozwiązywane są raz, a manifest przechowuje odwołania do źródeł. Obrazy nie są kopiowane. Znacznik oczekującego zestawu jest czyszczony dopiero po poprawnym zapisie manifestu.
6. Przygotowanie iteracji pozostaje w wątku roboczym; UI pokazuje stan przygotowania. Log `[T06 PERF]` podaje osobno czas przygotowania oraz finalizacji UI, bez czasu oczekiwania na decyzję użytkownika.

## Zachowanie danych i walidacja

- Porównano zapisane plany `pisto` przed i po: **identyczne 200 obrazów, kolejność, oceny, szczegóły ocen i końcowy histogram**.
- Porównano manifesty zestawu roboczego: **identyczne 9087 obrazów, ich kolejność, ścieżki źródłowe i token zbioru**. Różni się wyłącznie testowy katalog logicznego celu.
- Testy nowych obliczeń porównują wynik z wcześniejszym algorytmem dla różnych balansów, limitów i remisów.
- Testy indeksu sprawdzają cache, duplikaty nazw, zakres rekursji, różne katalogi oraz zmiany plików w podkatalogach.
- Testy przejścia sprawdzają pojedyncze odświeżenie, brak kosztownych zapytań w ukrytym Z2, zakończenie z treningiem i bez treningu oraz zachowanie zestawu przy błędzie zapisu manifestu.
- Główna grupa: **156 testów i 20 podtestów**. Regresje Z2/Z3: **95 testów i 4 podtesty**. Jeden test Tk wymagał ponowienia w osobnym procesie po błędzie inicjalizacji `icons.tcl`; ponowienie przeszło.
- `python -m auto_annotation_tool.campaign_graph_sanity`: **OK**.
- Sześć końcowych wariantów GUI: `errors: []`, prawidłowy etap i iteracja; anulowanie zachowuje IT2/E4.

Narzędzie pomiarowe: `output/t06_performance_probe.py`. Profile i wyniki: `output/t06_performance/{baseline,fixed,final,optimized_stage}/`. Bazowy pomiar przekazania obrazów roboczych znajduje się w `final/train_yolo26n_pose_1_reuse_input_backend`; wykonano go przed ostatnią optymalizacją ścieżek, której wynik jest w `optimized_stage`.
