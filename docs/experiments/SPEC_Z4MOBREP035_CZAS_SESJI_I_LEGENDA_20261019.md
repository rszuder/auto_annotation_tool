# Z4MOBREP035 — czas sesji, chwile zapisania pomiarów i zrozumiała legenda

**Data:** 2026-10-19
**Status:** implementacja Desktop gotowa do `--check/--apply`, odbiór GUI operatora pozostaje do wykonania.
**Zakres:** jedynie wizualizacja źródłowych śladów czasowych w `Raporty ALPR → Dane źródłowe → Czasy szczegółowe`. Niczego nie zapisujemy w archiwach Androida, raportach ani sidecarach GT.

## 1. Kontrakt metrologiczny

- `total_ms` z `traces.csv`: zmierzony czas przetworzenia pojedynczej próby w potoku ALPR. **Nie** jest czasem całej sesji.
- `plate_inference_ms`: czas **inferencji sieci MT** służącej do lokalizacji tablic. Preprocessing/postprocessing są oddzielnymi pomiarami.
- `character_inference_ms`: czas **inferencji sieci MZ** służącej do odczytu znaków. Preprocessing/postprocessing są oddzielnymi pomiarami.
- Długość całej sesji z `session.json.started_at/finished_at` lub spójnych źródłowych pól `report.json.session_started_ms`, `session_finished_ms`, `session_duration_ms`.
- Pozycja czasowa próbki pochodzi z `traces.csv.elapsed_ms`, walidowanego względem `timestamp_ms` i początku sesji. Gdy `elapsed_ms` nie ma, wolno użyć różnicy wiarygodnego `timestamp_ms` i zapisanego `session_started_ms`.
- `elapsed_ms` i `timestamp_ms` są **znacznikami zapisu pomiaru przetwarzania**. Nie wolno opisywać ich jako laboratoryjnie potwierdzonego czasu ekspozycji matrycy kamery. Nie przenosimy ani nie interpolujemy momentów pomiarów.
- Przy brakujących / powtarzających się / niezgodnych znacznikach czasowych oś czasu sesji jest wyłączona, a aplikacja korzysta z dotychczasowej osi ID klatki lub oryginalnego sposobu awaryjnego wyznaczania osi.

## 2. Zmiany interfejsu

1. Obok checkboxa `Łącz punkty sąsiednich klatek` są dwie opcje X: **Czas sesji** (domyślna, gdy można potwierdzić) i **ID klatki**.
2. Oś czasu pokazuje rzeczywistą chronologię od **0 do końca sesji**, w minutach i sekundach. Nie rozkłada pomiarów kategoriami, a luki są widocznymi okresami bez zapisanej próbki.
3. Nad wykresem wyświetla się czas trwania sesji oraz źródłowe godziny rozpoczęcia i zakończenia po przeliczeniu na lokalną strefę czasową komputera.
4. Wskazanie myszy na punkt podaje jego źródłowy ID klatki, czas od rozpoczęcia sesji, godzinę zapisu pomiaru (jeśli można ją potwierdzić), serię oraz wartość w ms.
5. Legenda jest zrozumiała: `ALPR: cały proces`, `MT: inferencja modelu tablic`, `MZ: inferencja modelu znaków` (przy małych szerokościach krótsze etykiety zachowują rozwinięcia w semantyce dokumentu).
6. Opcja łączenia sąsiednich **ID** klatek działa niezależnie od współrzędnych wyświetlania. Sam checkbox nie zmienia zoomu, przesunięcia, osi X ani zakresu Y. Natomiast świadome przełączenie **innego rodzaju osi X** resetuje nieporównywalny zakres zoomu.
7. Odrębna stopka osi X pozostaje zakotwiczona tak jak w Z4MOBREP034, bez jej ponownego pakowania.

## 3. Przypadek referencyjny P1-R0-FP32-B 2026-10-19

`session.json`: start 2026-10-18T23:19:09.654Z, koniec 2026-10-18T23:20:09.659Z → **60,005 s** (na komputerze w Polsce: 19.10, 01:19:09–01:20:09 UTC+02).

Zapisane osiem obserwacji na osi czasu:

| ID klatki | Czas zapisania pomiaru od startu |
|---:|---:|
| 384 | 0,737 s |
| 386 | 2,440 s |
| 387 | 10,371 s |
| 388 | 11,957 s |
| 389 | 20,858 s |
| 390 | 31,160 s |
| 391 | 38,560 s |
| 585 | 51,249 s |

Klatka 585 ma pozycję przy około 51 s, a nie wyłącznie daleki identyfikator `585`. Przedział 51,249–60,005 s to koniec sesji **bez zarejestrowanej kolejnej próbki**. Nie jest to automatycznie błąd inferencji ani awaria akwizycji.

## 4. Kontrola odbiorcza

- [ ] Otwórz sesję 19.10 w `Czasy szczegółowe` — oś `Czas sesji`, widoczne 0–1:00 i osiem punktów trzech serii.
- [ ] Najedź na punkt klatki 387 — opis powinien wskazać `+0:10,371` od początku sesji, a nie moment ekspozycji kamery.
- [ ] Wybierz `ID klatki` — zobacz źródłowe identyfikatory i zachowany tryb kategorii przy dużych lukach.
- [ ] W wybranym przybliżeniu kilkakrotnie przełącz `Łącz punkty sąsiednich klatek` — ani punkty, ani zoom, ani pan nie powinny się przesunąć.
- [ ] Zwęż górny panel separatorem — stopka i pasek kontekstu sesji pozostają widoczne.
- [ ] Sprawdź historyczne archiwum bez spójnego czasu sesji: oś `Czas sesji` jest niedostępna, bez fałszywego czasu i bez nadpisywania danych.

## 5. Gwarancje

- Ścieżki edytora GT, weryfikacji ROI i P2A/P2B są nietknięte.
- Nie przeliczamy zewnętrznych agregatów ani metryk zapisanych w źródle.
- `final_test` i formalne eksperymenty pozostają poza zakresem.
- Instalator tworzy kopie bezpieczeństwa i odmawia wdrożenia przy niezgodnym SHA.
