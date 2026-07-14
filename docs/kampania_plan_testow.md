# Plan testow kampanii przed faza delikatnej stabilizacji

Ten dokument opisuje minimalny zestaw testow recznych, ktore powinny przejsc po
zamknieciu zmian architektonicznych grafu kampanii. Celem nie jest testowanie
kazdego przycisku osobno, tylko potwierdzenie, ze caly przeplyw dziala od
wejscia w `E1` do powrotu do kolejnej iteracji.

## Kontrola techniczna przed GUI

Przed testami recznymi uruchom:

```powershell
python -B -m compileall -q auto_annotation_tool
python -m auto_annotation_tool.campaign_graph_sanity
```

Wynik oczekiwany:

- kompilacja pakietu bez bledow;
- sanity-check grafu konczy sie komunikatem `OK campaign graph sanity`;
- aktywny graf ma `T01`, `T03`, `T04`, `T05`, `T06`, `T07`;
- `T02` nie wystepuje jako aktywna bramka UI.

## Scenariusz 1: model tablic od obrazow

Cel: sprawdzic trase `plate_training`.

Kroki:

1. W `E1` wybierz bramke `T01`.
2. W pracy bramki wybierz przygotowanie `AT` dla modelu tablic.
3. W zasobach ustaw katalog obrazow.
4. Zatwierdz `T01` i przejdz do `E2/Z2`.
5. W `Z2` przygotuj anotacje tablic, recznie albo autoanotacja.
6. Przekaz zatwierdzone `[OK]` do grafu.
7. Wybierz `T05`, przygotuj wariant datasetu tablic w `Z4/PZ1`.
8. Przejdz do treningu `Z4/PZ2`.
9. Po treningu zamknij iteracje przez `T07`.

Sprawdz:

- `T01` nie pokazuje dawnej semantyki `T02`;
- zatwierdzone obrazy po przekazaniu nie wracaja na liste robocza Z2;
- `T05` mowi o datasecie i treningu modelu tablic;
- historia projektu pokazuje przyrost `AT`, dataset tablic i `MT` we wlasciwej iteracji;
- po `T07` kolejna iteracja startuje w `E1`.

## Scenariusz 2: model znakow od obrazow

Cel: sprawdzic trase `char_from_images`.

Kroki:

1. W `E1` wybierz `T01`.
2. W pracy bramki wybierz przygotowanie `AT` dla modelu znakow.
3. Przygotuj lub uzupelnij anotacje tablic w `Z2`.
4. Zamknij prace Z2 i przejdz przez `T04`.
5. W `Z3` przejdz do pracy nad znakami.
6. W `PZ2` przygotuj anotacje znakow na tablicach.
7. W `PZ3` utworz zrodlowy dataset znakow.
8. Zamknij `T06` i przejdz do `E4Z`.
9. W `Z4` utworz wariant treningowy znakow i uruchom trening.
10. Zamknij iteracje przez `T07`.

Sprawdz:

- przejscie do `Z3/PZ2` nie pokazuje przebitek freemode ani PZ1, jezeli nie sa potrzebne;
- jezeli wymagane jest wyodrebnianie, widoczny jest jeden spojny splash/postep;
- `T06` jasno odroznia prace w `PZ2` od eksportu datasetu w `PZ3`;
- bramka `T06` nie pozwala zatwierdzic bez kompletnego datasetu znakow;
- historia projektu pokazuje `AZ` i ewentualny `MZ` we wlasciwej iteracji.

## Scenariusz 3: model znakow z istniejacego zrodla tablic

Cel: sprawdzic trase `char_from_ready_plates`.

Kroki:

1. W `E1` wybierz `T03`.
2. Potwierdz, ze projekt ma istniejace zrodlo tablic: import `AT`, poprzednia iteracja albo wyodrebnione tablice.
3. Zatwierdz `T03`.
4. Przejdz do pracy `T06` i przygotuj dataset znakow w `Z3`.
5. Zamknij `T06`, przejdz do `E4Z`, przygotuj wariant treningowy i trenuj model znakow.
6. Zamknij iteracje przez `T07`.

Sprawdz:

- `T03` nie sugeruje, ze wykrywa znaki automatycznie;
- copy jasno mowi, ze korzystamy z istniejacego zrodla tablic;
- `T03` nie prowadzi przez `E2/Z2`, jesli nie trzeba ponownie oznaczac tablic;
- historia nie dopisuje sztucznego `AT`, jezeli nie powstalo ono w tej iteracji.

## Scenariusz 4: praca naprawcza i przerwanie

Cel: sprawdzic odporność na zamkniecie programu w trakcie pracy.

Kroki:

1. Wejdz w tryb naprawczy z `T06` albo `T07`.
2. Zatwierdz kilka obrazow `[OK]`, ale nie przekazuj ich formalnie do grafu.
3. Zamknij program krzyzykiem.
4. Uruchom projekt ponownie.
5. Sprawdz bramke, modal pracy i prawa strone karty roboczej.
6. Kontynuuj prace albo swiadomie pomin zalegle zmiany.

Sprawdz:

- bramka sygnalizuje przerwana prace tylko przy wlasciwej bramce;
- przerwane `[OK]` nie sa automatycznie konsumowane agresywnie;
- po formalnym przekazaniu `[OK]` liczniki i lista aktualizuja sie bez podwojnego liczenia;
- po powrocie do grafu status przerwania znika.

## Kryteria akceptacji przed delikatna stabilizacja

- przejscia grafu sa spojne z aktywna sciezka;
- bramki nie pokazuja aktywnego `Zatwierdz`, jezeli kontrakt nie jest spelniony;
- nazwy bramek mowia jezykiem celu uzytkownika, nie dawnych paneli;
- liczniki w bramce, panelach i szufladzie pokazuja te same wartosci;
- historia projektu pokazuje iteracje, trase i realne produkty;
- brak kaskady splashy i przebitek trybu swobodnego;
- po restarcie projektu nie gubimy zatwierdzonych ani przerwanych prac.
