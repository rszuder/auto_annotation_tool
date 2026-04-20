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
