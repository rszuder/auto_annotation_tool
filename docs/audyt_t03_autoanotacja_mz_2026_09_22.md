# T03 i autoanotacja Z2 — MZ_finalny_2026

Sprawdzenie z 22.09.2026 na projekcie `MZ_finalny_2026_17596F` (1000 obrazów).

## Przyczyny

- Wejście z T03 przekazywało `restore_preview=True`. Przygotowanie źródeł,
  odtwarzanie sesji i pełne odświeżenia wykonywały się jeszcze przed pokazaniem Z2.
  Dodatkowo panel odczytywał historię ręcznych runów także w torze auto.
- `open_campaign_step2_entry` planowało przez `after_idle` automatyczne przygotowanie
  ręcznego XML. W projekcie run `173924` jest `manual_template`, bez asysty pojazdów.
  To przygotowanie runu korzystało ze wspólnego mechanizmu startu anotacji.
  Samo wejście do karty nie powinno tworzyć runu.
- Modal kopiował głęboko wszystkie anotacje przy otwarciu i anulowaniu, ponownie
  obliczał ochronę tych samych pozycji i odbudowywał listę przy zwykłym anulowaniu.
- Run `174512` ma tryb `B: Tylko tablice`, ale zawiera 1231 ramek `vehicle`.
  Pochodzą z wcześniejszych anotacji dołączanych przy scalaniu wyników; wyłączenie
  asysty nie uruchamiało nowego modelu pojazdów. Użytkownik potwierdził, że objawem
  były pozostające ramki.
- Ochrona ręcznych anotacji była częściowo stosowana przed modalem. Plan bez
  poprawki zawężał 1000 obrazów do 2, więc wyłączenie ochrony w modalu nie mogło
  przywrócić pozostałych obrazów. Dodatkowy merge mógł odtworzyć stare detekcje.
- Callback przy rozpoczęciu wypełniania listy mógł uruchomić drugie wypełnianie.
  Pierwsze przejmowało token drugiego i również dopisywało wiersze. Log projektu
  zawiera przypadek 1800 wierszy przy 1000 anotacjach.

## Zmiany

- Nawigacja z bramek odkłada listę/podgląd do czasu pokazania Z2 i unika
  powtórnego sprawdzania źródeł w warstwie nawigacji. Odświeżenie akcji czeka na
  przygotowane dane także przy wejściu bez istniejącego runu.
- Wejście do Z2 nie planuje startu ręcznego XML ani autoanotacji.
- Historia ręcznych runów jest odczytywana dla ręcznej kontynuacji.
- Modal korzysta ze wspólnego zestawu chronionych nazw i grup; anulowanie bez
  zmiany danych nie kopiuje anotacji ani nie odtwarza listy.
- Wybór asysty jest przekazywany w wyniku modala do tworzenia silnika detekcji.
  Przebieg bez asysty usuwa pomocnicze detekcje pojazdów z nowego wyniku, również
  po dołączeniu zachowanych anotacji. Polygony i atrybuty tablic zostają zachowane.
- Ochrona zakresu jest rozstrzygana w modalu. Stare detekcje wybranych do ponownego
  przetworzenia zdjęć nie nadpisują nowego wyniku.
- Wypełnianie listy zachowuje własny token i przerywa pracę po zastąpieniu przez
  nowsze wywołanie, także wewnątrz callbacków.

## Pomiary i walidacja

Profilowanie Tk na danych projektu, z wyłączonym zapisem sesji/projektu i bez
uruchamiania modeli. Są to czasy przygotowania interfejsu w sondzie, nie pomiar
całego przebiegu YOLO ani gwarancja czasu na każdej maszynie.

| Operacja | Przed | Po |
| --- | ---: | ---: |
| Przygotowanie wejścia z istniejącym runem | 8,54 s | 1,45 s |
| Otwarcie modala zakresu, 1000 anotacji | 1,52 s | 0,50 s |
| Otwarcie i anulowanie tego modala | 2,62 s | 0,52 s |

Lista/podgląd doładowują się po przełączeniu karty. Osobna próba wejścia ręcznego
bez runu: 1,86 s, `manual_prepare_deferred_to_user=True`, zero wywołań startu.

- Zakres testów poprawki: 138 testów i 4 podtesty przeszły; jeden test inicjalizacji
  Tk wymagał ponowienia w osobnym procesie.
- Szerszy przebieg Z2/kampanii przed ostatnim uzupełnieniem odraczania źródła:
  377 testów i 79 podtestów przeszło; 8 błędów inicjalizacji Tk przeszło po
  izolowanym powtórzeniu (17 testów w tych plikach).
- Dwa pozostałe błędy dotyczą niezmienionego `test_z2_plate_gt_inline.py`:
  `test_char_route_defaults_gt_mode_on` i `test_plate_route_defaults_gt_mode_off`.
  Powtarzają się osobno. Testy oczekują obowiązkowego GT dla znaków i wyłączonego
  GT dla tablic, podczas gdy kod już w HEAD definiuje GT jako opcjonalne i zawsze
  dostępne. Nie zmieniano tego kontraktu ani tych testów.
- `git diff --check` bez błędów białych znaków.

Sonda: `output/z2_t03_profile.py`; szczegółowe profile i wyniki:
`output/z2_t03_*`. Oryginalnych runów użytkownika nie przepisywano. Usunięcie
starych ramek pojazdów dotyczy nowego wyniku po uruchomieniu autoanotacji bez asysty.
