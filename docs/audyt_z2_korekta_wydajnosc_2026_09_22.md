# Z2: lagi korekty, superzoomu i startu autoanotacji

Uzupełnienie wcześniejszego audytu T03 po ponownym zgłoszeniu użytkownika.
Badano 1000 anotacji projektu `MZ_finalny_2026`, w tym nowszy run `182503`.
Sondy pracowały na kopiach XML i stanu projektu w `output/z2_interaction_probe`.

## Potwierdzone przyczyny

1. Zamknięcie niezmienionej karty GT przy przejściu do następnej tablicy wywoływało
   `_commit_record(final=True)`, a następnie odświeżenie bramki. W pomiarze callback
   GT trwał 2,31 s i czterokrotnie pobierał/kopiował anotacje XML. Nazwany
   „lightweight” refresh nadal wykonywał ciężką pracę.
2. Automatyczny zapis jednej poprawionej ramki był synchroniczny: pełny eksport
   1000 obrazów, ponowne parsowanie do DOM tylko dla formatowania XML oraz
   wyszukiwanie historii runów. Zmierzone blokowanie: 1,9–2,6 s.
3. Odczyt katalogu projektu za każdym razem wykonywał `mkdir` dla całego drzewa
   workspace. Jeden zapis powodował około 1800 takich wywołań.
4. Korekta polygonów czyściła również cache zdekodowanych obrazów, utrudniając
   szybkie przełączanie tablic i wykorzystanie wcześniejszego doładowania zdjęć.
5. Worker publikował wynik do UI przed zwolnieniem blokady listy. Tk ignoruje
   `delete` i `insert` dla nieaktywnej listy. Po jej późniejszym odblokowaniu
   pozostałe partie dopisywały się do starych wierszy: 1000 anotacji / 1800 wierszy.
   Poprawka tokenu z pierwszego audytu nie usuwała tej drugiej przyczyny.
6. Zakończenie autoanotacji ponownie wczytywało gotowy XML, scalało kopie w GUI
   i odświeżało niewidoczny graf kampanii. Start tworzył kilka kopii tej samej puli.

## Poprawki

- Niezmienione GT nie uruchamia zapisu ani odświeżenia bramki. Faktyczna zmiana GT
  odświeża bramkę raz, po zakończeniu edycji i poza aktywnym przeciąganiem.
- Autosave kopiuje zmienione obrazy i zapisuje je poza wątkiem Tk. Zachowuje
  pozostałe elementy XML, stabilne ID, GT i atrybuty. Nowy plik zastępuje stary
  dopiero po udanym zapisie. Błąd nie usuwa niezapisanych zmian.
- Liczniki wersji edycji zapobiegają oznaczeniu nowszej poprawki jako zapisanej
  przez starszy worker. Ręczny zapis czeka na wcześniejszy autosave. Zamknięcie
  aplikacji kończy zapis poprawek przed anulowaniem callbacków.
- Aktualizacja metadanych po autosave czeka, jeśli użytkownik właśnie koryguje ramkę.
- Historię runów odczytuje widoczny tor ręcznej kontynuacji. Getter katalogu nie
  tworzy ponownie całego drzewa workspace; nowe i brakujące korzenie są obsługiwane.
- Edycja anotacji zachowuje cache obrazów oparty o ścieżkę, mtime i rozmiar pliku.
- Najpierw zwalniana jest blokada listy, potem publikowany jest kompletny wynik.
  Scalanie pełnego widoku następuje w workerze przed zapisem; UI korzysta z gotowych
  obiektów, bez ponownego odczytu XML. Graf odświeża się po powrocie do niego.
  XML zachowuje także puste wyniki detekcji, żeby ponowne otwarcie odpowiadało liście Z2.
- Start korzysta z jednej kopii stanu do odtworzenia i zachowania chronionych ramek.

## Walidacja

- 103 testy i 4 podtesty zakresu poprawki: wszystkie przeszły. Obejmują zapis
  podczas następnej edycji, błąd zapisu, atomową podmianę XML, jawny zapis po
  autosave, zamykanie aplikacji, niezmienione GT, zachowanie geometrii/ID oraz
  kolejność odblokowania listy i publikacji wyniku.
- Szersza próba: 394 testy i 79 podtestów przeszły; 2 błędy w niezmienionym
  `test_campaign_iteration_performance.py` powtórzyły się osobno. Dotyczą wykrywania
  natychmiastowych zmian zagnieżdżonych katalogów przez `ImageDirectoryIndex`.
  Implementacja indeksu i te testy są identyczne z HEAD. Tego odrębnego problemu
  nie zmieniano. Plik z wcześniej zgłoszonymi dwoma starymi oczekiwaniami GT nie
  należał do tej szerszej próby.
- Sonda z rzeczywistym Tk, obrazem i serią przesunięć czterech narożników:
  callback GT blokujący na 2,31 s zniknął po poprawce. Zaobserwowane droższe
  callbacki dotyczyły już renderowania obrazu, około 30–60 ms.
- Zlecenie zapisu w tle jednego obrazu: około 3,7 ms w wątku GUI. To czas zlecenia,
  nie całego zapisu dyskowego. Jawny pełny zapis w sondzie skrócił się do około
  0,4 s dzięki uproszczeniu serializacji i usunięciu zbędnych odczytów historii.
- Przygotowanie startu autoanotacji na puli 1000 obrazów, zakres 2 obrazów:
  około 1,3 s do zaplanowania workera; uruchomienie workera potwierdzone. Silnik
  detekcji był zastąpiony atrapą, więc pomiar nie obejmuje ładowania YOLO ani inferencji.
- Zakończenie runu w sondzie: 1000 anotacji i dokładnie 1000 wierszy; gotowy wynik
  nie został ponownie odtworzony z XML. Finalizacja UI około 1,95 s, końcowe partie
  listy doładowane po niej.
- `git diff --check` bez błędów białych znaków.

Sonda: `output/z2_interaction_profile.py`. Profile porównawcze:
`before_canvas`, `after_async`, `after_gt`, `finish_final`, `start_optimized`.
Dotychczasowych anotacji projektu nie przepisywano. Pomiary nie zastępują
obserwacji długiej pracy użytkownika w uruchomionej głównej aplikacji.
