# Przebudowa Wizarda

## Cel

Przebudować wizard kampanii tak, aby:

- nie dublował logiki roboczej z `Z2`, `Z3` i `Z4`,
- był czytelnym nawigatorem procesu projektu,
- korzystał z jednego źródła prawdy o stanie projektu,
- był odporny na dalsze zmiany UI w zakładkach roboczych.

Nowa zasada:

- `Wizard` prowadzi,
- `Z2 / Z3 / Z4` wykonują pracę,
- `CampaignManager` przechowuje stan projektu,
- zakładki robocze raportują status gotowości i wynik.

## Główny Problem Dzisiaj

Obecny wizard:

- ma własną logikę przebiegu pracy,
- częściowo dubluje to, co dzieje się już w `Z2`, `Z3`, `Z4`,
- opiera się na dawnych założeniach o układzie i przepływie,
- coraz częściej "rozjeżdża się" z rzeczywistym interfejsem.

W praktyce oznacza to, że zmiana w zakładce roboczej wymaga później ręcznego "doganiania" wizarda.

## Nowa Filozofia

Wizard ma być cienką warstwą sterującą.

Nie powinien:

- mieć własnych pół-edytorów,
- kopiować ustawień z zakładek,
- przechowywać osobnej prawdy o gotowości etapów,
- wymuszać układu roboczego innego niż w docelowych zakładkach.

Powinien:

- pokazać etap projektu,
- pokazać, co jest gotowe i czego brakuje,
- skierować użytkownika do właściwej zakładki,
- po powrocie odczytać aktualny stan i zaktualizować kartę etapu.

## Jedno Źródło Prawdy

Docelowo stan kampanii powinien składać się z dwóch warstw.

### 1. Stan trwały projektu

Źródło: `CampaignManager`

To zostaje jako główny zapis:

- aktywny projekt,
- numer iteracji,
- aktywny krok,
- wybrany tor iteracji: `plate` / `char`,
- status kroków,
- ścieżki do najważniejszych artefaktów projektu.

### 2. Stan roboczy zakładek

Źródło: `Z2`, `Z3`, `Z4`

Zakładki nie zapisują "kroku wizarda", tylko raportują:

- czy mają poprawnie ustawione źródła,
- czy etap jest gotowy do uruchomienia,
- czy wynik już istnieje,
- czy wymaga korekty,
- jaki jest główny następny krok.

## Nowy Model Wizarda

Zamiast rozbudowanego dashboardu z własną logiką, wizard powinien mieć karty etapów.

### Karta 0. Projekt

Pokazuje:

- nazwę projektu,
- numer iteracji,
- status projektu,
- datę utworzenia / zakończenia,
- szybkie akcje projektu.

Akcje:

- otwórz projekt,
- nowy projekt,
- wyjdź z projektu,
- zakończ projekt,
- wznowienie projektu.

### Karta 1. Paczka Wejściowa

Cel:

- przygotować zbiór zdjęć wejściowych dla bieżącej iteracji.

Wizard pokazuje:

- czy paczka istnieje,
- ile zdjęć ma iteracja,
- czy krok jest zatwierdzony.

Akcja główna:

- `Przejdź do przygotowania paczki`

Ta karta nie powinna próbować budować własnego mini-edytora ingestu. Może co najwyżej pokazać skrócone podsumowanie i przycisk otwierający właściwe miejsce.

### Karta 2. Tor Iteracji

Cel:

- ustalić, czy iteracja buduje model tablic czy model znaków.

Wizard pokazuje:

- wybrany tor: `tablice` / `znaki`,
- co ten tor oznacza,
- jaki będzie dalszy przebieg.

Akcja główna:

- `Wybierz lub zmień tor iteracji`

Ta karta jest decyzją projektową, a nie narzędziem roboczym.

### Karta 3. Z2 Autoanotacja Tablic

Cel:

- przygotować lub poprawić run anotacji tablic.

Wizard pokazuje:

- czy Z2 ma gotowe źródła,
- czy run anotacji już istnieje,
- czy krok czeka na zatwierdzenie,
- czy potrzebna jest korekta ręczna.

Akcje:

- `Otwórz Z2`
- `Wróć do korekty`
- `Zatwierdź etap`, jeśli zakładka raportuje gotowość

Wizard nie pokazuje własnych ustawień modeli ani własnych mini-kroków auto/manual.

### Karta 4. Z3 Znaki

Karta warunkowa.

Pokazujemy ją tylko wtedy, gdy tor iteracji to `znaki`.

Cel:

- wyciąć tablice,
- dopasować znaki,
- poprawić wynik,
- przygotować paczkę do datasetu znaków.

Wizard pokazuje:

- czy źródła do Z3 są gotowe,
- czy PZ1 jest wykonane,
- czy PZ2 wymaga korekt,
- czy PZ3 ma gotowy eksport.

Akcje:

- `Otwórz Z3`
- `Wróć do korekty`
- `Przejdź do eksportu`

Wizard nie powinien dublować mechanizmów OCR, YOLO, podglądu boxów ani eksportów.

### Karta 5. Z4 Dataset i Trening

Cel:

- zbudować dataset,
- uruchomić trening,
- przejrzeć wynik,
- domknąć iterację.

Wizard pokazuje:

- czy dataset istnieje,
- czy trening wystartował,
- czy istnieją gotowe runy,
- czy iteracja może zostać zakończona.

Akcje:

- `Otwórz Z4`
- `Przejdź do datasetu`
- `Przejdź do treningu`
- `Zamknij iterację`

## Dozwolone Stany Kart

Każda karta powinna korzystać z jednego wspólnego słownika stanów:

- `locked` - zablokowane przez wcześniejszy etap
- `ready` - można wejść i pracować
- `in_progress` - praca rozpoczęta, ale etap niezamknięty
- `needs_attention` - coś wymaga korekty lub decyzji
- `done` - etap ukończony
- `skipped` - etap pominięty zgodnie z torem

To powinno zastąpić dzisiejsze mieszanie statusów tekstowych i specjalnych warunków w UI.

## Kontrakt Między Wizardem a Zakładkami

Docelowo każda zakładka robocza powinna wystawiać metodę w stylu:

`get_wizard_stage_status()`

Zwracany obiekt powinien mieć prostą strukturę:

- `stage_key`
- `state`
- `title`
- `summary`
- `details`
- `primary_action_label`
- `can_approve`
- `approve_label`
- `result_refs`

Przykład dla `Z2`:

- `state = "in_progress"`
- `summary = "Run anotacji istnieje, ale etap nie został jeszcze zatwierdzony."`
- `primary_action_label = "Otwórz Z2"`
- `can_approve = True`

Wizard nie liczy tego sam. Wizard tylko renderuje wynik.

## Nawigacja

Wizard powinien mieć tylko dwa typy akcji:

### 1. Nawigacja

- otwórz właściwą zakładkę,
- przejdź do właściwego podetapu,
- ustaw fokus na konkretnej sekcji.

### 2. Decyzja projektowa

- wybór toru iteracji,
- zatwierdzenie etapu,
- reset etapu,
- zakończenie iteracji,
- zakończenie projektu.

Wizard nie powinien wykonywać złożonych operacji roboczych samodzielnie.

## Co Usuwamy Z Obecnego Wizarda

W ramach przebudowy docelowo usuwamy z wizarda:

- rozbudowane, własne opisy przebiegu Z2 / Z3 / Z4,
- logikę duplikującą układ zakładek roboczych,
- ręcznie składane mini-przepływy zależne od starych ekranów,
- specjalne wyjątki wizarda wynikające z dawnego układu interfejsu.

Zostawiamy tylko:

- status,
- podsumowanie,
- decyzje,
- nawigację.

## Docelowy Układ Ekranu Wizarda

Proponowany układ:

### Lewa kolumna

- projekt,
- iteracja,
- tor,
- główne akcje projektu.

### Prawa kolumna

- pionowa lista kart etapów,
- na każdej karcie:
  - nazwa etapu,
  - status,
  - krótki opis,
  - najważniejszy brak albo wynik,
  - 1 główny przycisk,
  - opcjonalny przycisk pomocniczy.

To ma być bardziej "panel sterowania iteracją" niż dashboard pełen własnych podsystemów.

## Etapowanie Wdrożenia

### Etap 1. Kontrakt

Najpierw definiujemy wspólny model kart i stanów.

Do zrobienia:

- wspólne enum stanów kart,
- wspólna struktura `stage_status`,
- jedna metoda renderująca kartę etapu.

### Etap 2. Cienki Wizard

Przepisujemy wizard tak, aby:

- renderował tylko karty,
- nie miał już własnych ścieżek roboczych,
- korzystał z `CampaignManager` i statusów zakładek.

### Etap 3. Adaptery Z2 / Z3 / Z4

Dopisujemy do zakładek metody raportujące stan dla wizarda.

### Etap 4. Czyszczenie

Usuwamy starą logikę dashboardu, roadmapy i wszystkie gałęzie dublujące obecny UX.

## Minimalny Zakres Pierwszego Wdrożenia

Najbezpieczniejszy pierwszy krok:

- zostawić obecny `CampaignManager`,
- zostawić obecne przejścia do zakładek,
- przepisać tylko UI wizarda na nowe karty,
- na początku liczyć statusy częściowo z `CampaignManager`, a częściowo z lekkich adapterów zakładek,
- dopiero później wycinać stary kod.

## Decyzje Projektowe Na Start

Na tę chwilę przyjmujemy:

- wizard nie jest miejscem pracy, tylko miejscem decyzji i nawigacji,
- `Z2`, `Z3`, `Z4` pozostają głównymi narzędziami operacyjnymi,
- `CampaignManager` pozostaje trwałym źródłem prawdy o stanie projektu,
- tor `plate` pomija kartę `Z3`,
- karta `Z4` zawsze istnieje, ale jej treść zależy od toru iteracji.

## Następny Krok

Po akceptacji tej architektury:

1. przygotować prosty model danych kart etapu,
2. zbudować nowy szkielet UI wizarda,
3. podpiąć pierwsze statusy dla:
   - projektu,
   - paczki wejściowej,
   - toru iteracji,
   - Z2,
   - Z4,
4. dopiero później dopiąć `Z3` i przypadki naprawcze.

---

# Dziennik Stabilizacji - 2026-06-12

## Kierunek Bieżący

Na tym etapie priorytetem pozostaje stabilizacja istniejącego systemu, bez dokładania nowej dużej architektury. Model warstwowy UI odkładamy do backlogu jako kierunek docelowy, a teraz pracujemy punktowo nad tym, co realnie przeszkadza w pracy:

- czas ładowania dużych projektów,
- ciężkie przejścia między grafem kampanii i zakładkami roboczymi,
- lagi w Z2 i Z3/PZ2,
- regresje po autoanotacji,
- niespójne copy starego wizarda i nowej maszyny stanów,
- niepotrzebne przebitki dawnych elementów UI.

## Ostatnie Zmiany Wykonane

### Graf Kampanii I Maszyna Stanów

- Wprowadzono graf przejść kampanii jako równoległy system sterowania względem dawnego wizarda.
- Bramka grafu reprezentuje konkretne przejście, a nie ogólny etap.
- Bramka ma domeny: zasoby, akcje i zatwierdzenie.
- Dodano aktywację bramki przez elektrodę oraz rozróżnienie bramek aktywnych i nieaktywnych.
- Ograniczono dostępność zasobów i akcji dla bramek nieaktywnych, aby użytkownik najpierw świadomie wybrał ścieżkę.
- Rozpoczęto usuwanie dawnych elementów wizarda, które dublowały logikę maszyny stanów.
- Poprawiano lagi grafu przy zoomie, przesuwaniu węzłów, przesuwaniu badge i przeliczaniu łączników.
- Dopisano animację prowadzącą użytkownika po aktualnych bramkach i etapach, jako jednorazowy znacznik uwagi.

### Z2 W Kampanii

- Stabilizowano wejście do Z2 z bramek grafu, szczególnie T04/T06.
- Usuwano przebitki trybu swobodnego w wejściu kampanijnym.
- Redagowano copy Z2 tak, aby mówiło językiem bramek grafu, a nie dawnych etapów E2/E3.
- Przywrócono prawy panel Z2 w trybie kampanii po regresji, w której zostawało samo CTA powrotu do grafu.
- Odróżniono stan ładowania prawego panelu od właściwego stanu po załadowaniu danych.
- Dodano brakujący delegat `_get_current_preview_plate_count_state`, który blokował finalizację UI po zakończeniu autoanotacji.
- Przyspieszono odtwarzanie dużych runów Z2 przez:
  - cache dla ukrytych/efektywnych źródeł znakowych,
  - lżejsze budowanie listy podglądu dla dużych runów,
  - odroczenie ciężkiego odtwarzania danych,
  - pomijanie pełnego skanu brakujących obrazów w dużych, prawie kompletnych runach.
- W logach NEON zejście z wejścia do Z2 poprawiono z czasów rzędu kilkudziesięciu sekund do kilku sekund dla samego otwarcia zakładki, przy czym pełne odtworzenie dużych anotacji nadal jest obszarem do dalszej optymalizacji.
- Zablokowano niepożądane zaznaczanie pozycji listy podczas otwartego modala autoanotacji, jeśli nie jest aktywny tryb ręcznego wyboru z listy.
- Przywrócono logikę, że podczas trwania autoanotacji użytkownik nie powinien zwyczajnie wracać do grafu, tylko powinien mieć świadome zatrzymanie procesu.

### Z2 Canvas, Fullscreen I Korekta Narożników

- Przyspieszono start dragu narożnika w fullscreen/superkorekcie przez ograniczenie hit-testów kursora przy każdym ruchu myszy.
- Usunięto dodatkowy redraw przy przejęciu narożnika do dragu.
- Ograniczono koszt historii undo podczas jednej serii korekt narożników: w trybie ciągłej korekty zapis historii wykonywany jest raz na obraz, a nie przy każdym kolejnym narożniku.
- Odchudzono wyjście z fullscreen:
  - stabilizacja rozmiaru canvasu nie wykonuje już wielu kolejnych `fit_to_view`,
  - overlay/dock/bramka nie są odświeżane trzykrotnie pod rząd,
  - toolbar i status edytora są odświeżane asynchronicznie,
  - prawy panel nie jest przywracany podwójnie.

### Z3/PZ2 I Praca Na Znakach

- Rozdzielano język dawnego modelu etapów od języka bramek grafu.
- Poprawiano zachowanie badge, etykiet, separatora rzędów i statusu rzędu tablicy.
- Rozpoznano problem filtrów 1R/2R/2R? jako źródło wrażenia znikania anotacji po restarcie lub zmianie statusu rzędu.
- Ustalono kierunek: przełącznik 1R/2R/AUTO nie powinien być sztucznym przełącznikiem typu tablicy, tylko statusem wynikającym z położenia belki i ręcznej pracy użytkownika.
- Ustalono, że belka rzędowości powinna być elementem edycyjnym, a ręczna zmiana powinna nadawać status manualny.

### Z4, Augmentacja I Dataset

- Rozwijano modal syntetycznego zwiększania datasetu jako osobny edytor efektów, a nie stały ciężki element PZ1.
- Dodawano efekty: błoto, deszcz, noc, reflektory, relief, połysk mokrego błota, zacienienie od góry i uproszczone refleksy.
- Ustalono, że parametry ustawione przez użytkownika są bazą, a obrazy generowane syntetycznie powinny mieć niewielki rozrzut wokół tej bazy.
- Rozpoznano problem, że dataset augmentowany musi powiększać zbiór źródłowy, zachowując semantykę nazw plików i nie nadpisując istniejących wariantów.
- Poprawiano problemy z modalami augmentacji, fullscreenem, sterowaniem reflektorami i przenoszeniem ustawień efektu między losowanymi obrazami.

## Otwarte Problemy Stabilizacyjne

- Pełne odtworzenie dużego runu Z2 nadal potrafi być odczuwalnie długie, szczególnie przy tysiącach anotacji.
- Należy dalej obserwować prawy panel Z2 po wejściu z grafu i po zakończeniu autoanotacji.
- Trzeba dopilnować, aby autoanotacja miała jasną akcję zatrzymania i nie pozwalała na przypadkowe opuszczenie procesu.
- W Z3/PZ2 trzeba dalej porządkować model rzędowości tablic, aby status 1R/2R/AUTO był konsekwencją danych, a nie osobnym mylącym przełącznikiem.
- Należy kontynuować usuwanie starych elementów UI, które nadal mogą przebijać spod maszyny stanów.

---

# Backlog Architektoniczny

## Warstwowy Model UI Dla Z2/Z3

Pomysł do rozważenia po stabilizacji obecnego systemu: przejście na warstwowy model interfejsu, w którym ekran nie jest przebudowywany przez przepinanie widgetów, tylko składany z warstw.

Robocze nazwy podejścia:

- `layered UI`,
- `layer manager`,
- `scene graph`,
- `compositing`,
- `retained-mode UI`,
- `overlay stack`.

Proponowany podział warstw:

- warstwa bazowa: canvas z obrazem/tablicą,
- warstwa anotacji: ramki, boxy, belki, badge i etykiety,
- warstwa HUD: kompas, asysta, statusy, ikony FS,
- warstwa paneli bocznych: lewy i prawy panel,
- warstwa modalna: blokada interakcji i okna decyzji,
- warstwa interakcji: aktywny tryb pracy, hit-testy, drag, skróty klawiaturowe.

Docelowa korzyść:

- przejście fullscreen/non-fullscreen nie przebudowuje układu,
- panele boczne są tylko ukrywane/pokazywane,
- HUD jest przełączany niezależnie,
- canvas i anotacje zachowują stan bez kosztownego odtwarzania,
- interakcje są obsługiwane przez jeden kontroler warstw, zamiast przez wiele rozproszonych wyjątków.

Decyzja na teraz:

- nie wdrażamy tego w bieżącej stabilizacji,
- traktujemy to jako kierunek docelowy po opanowaniu obecnych lagów i regresji,
- jeśli wrócimy do tematu, pierwszym kandydatem powinien być Z2, bo tam koszt przepinania fullscreen/non-fullscreen i paneli jest dziś najbardziej widoczny.

## Refiner Boxów Znaków Dla Tablic Perfect

Pomysł do wdrożenia jako osobny moduł po ustabilizowaniu bieżącego pipeline Z3/PZ2: iteracyjny refiner boxów znaków uruchamiany wyłącznie dla tablic ze statusem `perfect`.

Założenie:

- tablica `perfect` daje nam prawdę docelową, czyli wiemy, jaki znak powinien znajdować się w danym slocie,
- YOLO daje hipotezę pozycji i rozmiaru boxa,
- OCR/YS/klasyfikator znaku służy jako kontrola, czy po modyfikacji box nadal odpowiada oczekiwanemu znakowi,
- obraz tablicy służy do oceny realnego pokrycia znaku, czyli tego, ile "tuszu" znaku znajduje się w boxie.

Docelowy przebieg:

- startujemy od aktualnego boxa OCR/YOLO dla znanego znaku, np. `2`,
- lokalnie przesuwamy, zwężamy, poszerzamy i korygujemy wysokość boxa,
- po każdym kroku oceniamy, czy box obejmuje większą część realnego znaku,
- jednocześnie sprawdzamy, czy odczyt/klasyfikacja nadal wskazuje oczekiwany znak,
- jeśli pokrycie rośnie i znak nadal jest poprawny, kontynuujemy,
- jeśli znak przestaje pasować albo jakość pokrycia spada, cofamy się do ostatniego dobrego wariantu i zatrzymujemy kaskadę.

Najważniejsza reguła:

- zła poprawka jest gorsza niż brak poprawki, więc refiner nie może na siłę poprawiać boxa, jeśli traci zgodność z oczekiwanym znakiem.

Korzyść:

- przypadki typu `FZI24222`, gdzie prosta geometria YOLO/OCR myli sąsiednie znaki albo obejmuje tylko fragment znaku szerokim boxem, powinny być rozwiązywane lokalnie i kontrolowanie,
- mechanizm nie powinien obciążać całej detekcji, bo działa tylko na tablicach `perfect` i tylko wtedy, gdy mamy sensowną prawdę docelową.

Decyzja na teraz:

- traktujemy refiner jako osobny moduł, nie jako dalsze rozbudowywanie prostego matchera YOLO-box-backend,
- bieżący matcher może pozostać lekkim zabezpieczeniem, ale docelowa precyzyjna korekta powinna należeć do refinera.

## Promocja I Import/Eksport AZ

Temat do wdrożenia jako element stabilizacji toru znaków: `AZ`, czyli anotacje znaków na wyodrębnionych tablicach, powinny stać się pełnoprawnym artefaktem projektu podobnie jak `AT`, `MT` i `MZ`.

Problem:

- obecnie użytkownik może wykonać realną pracę w Z3/PZ2, ale kolejna iteracja nie zawsze traktuje te anotacje jako zasób projektu,
- `AZ` jest zależne od konkretnego wyodrębnienia tablic, więc nie może być przenoszone tak swobodnie jak model,
- zewnętrzny import samych boxów znaków jest ryzykowny, jeśli nie wiemy, z jakiego `AT` i jakiego manifestu cropów powstał.

Decyzja architektoniczna:

- `AZ` nie walidujemy bezpośrednio względem surowych obrazów,
- `AZ` walidujemy względem manifestu wyodrębnionych tablic,
- zewnętrzny import `AZ` musi być hermetycznym pakietem powiązanym z tablicami, a nie luźnym folderem boxów,
- ryzykowne dopasowania odrzucamy zamiast wystawiać użytkownikowi skomplikowane opcje ratunkowe.

Docelowy kontrakt pakietu:

- `AZ`,
- kotwica `AT`,
- manifest wyodrębnienia tablic,
- metadane projektu i iteracji,
- wersja prostowania/cropowania,
- liczniki tablic, znaków, manuali, auto i perfect,
- daty utworzenia oraz źródło pakietu.

Przepływ wewnętrzny:

- wykrywać istniejące `AZ` w projekcie,
- przypisywać `AZ` do iteracji i źródłowego manifestu tablic,
- promować zgodne `AZ` do kolejnej iteracji jako kandydat zasobu,
- pokazywać w zasobach bramek prosty status: `jest`, `brak`, `częściowe`, `niezgodne`,
- nie nadpisywać manuali/perfect bez jawnej decyzji użytkownika.

Przepływ importu zewnętrznego:

- użytkownik wskazuje pakiet anotacji znaków,
- program sam sprawdza kompletność i zgodność pakietu,
- UI pokazuje prostą tabelę: pakiet, pasuje do tablic, znaki, manual, auto, perfect, pominięte, status,
- import przyjmuje tylko część bezpiecznie dopasowaną,
- import trafia domyślnie do kontroli, nie bezpośrednio jako wynik zamknięty/perfect.

Szacunek czasowy:

- promocja wewnętrzna `AZ`: 1-2 dni,
- manifest/pakiet `AZ` jako kontrakt: około 1 dzień,
- eksport pakietu `AZ`: 0.5-1 dnia,
- import pakietu `AZ`: 1.5-2 dni,
- spięcie z zasobami bramek, historią projektu i copy: około 1 dzień.

Kolejność wdrażania:

- najpierw promocja wewnętrzna `AZ`,
- potem format hermetycznego pakietu,
- dopiero na końcu import/eksport zewnętrzny i UI wyboru pakietu.
