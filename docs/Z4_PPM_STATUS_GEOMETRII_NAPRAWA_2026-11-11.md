# Z4 — naprawa PPM: status bez utraty narysowanej ramki

Data: 11.11.2026. Implementacja i testy zakresu: **PASS**. Odbiór wizualny operatora: **NOT_VERIFIED**.

Dokument zastępuje opis menu i kontraktu nowych zapisów z `Z4_A1_PPM_GEOMETRIA_FRAGMENT_NUMERU_2026-11-11.md`. Nie zastępuje ani nie migruje historycznych danych.

## Przyczyna regresji i jej odtworzenie

Poprzednie `PhotographCanvasSource.context_menu()` wiązało powody geometrii z `begin_geometry()`. Wybranie powodu nie było zmianą statusu: uruchamiało narzędzie orientacyjnego prostokąta/punktu i oczekiwało na kolejne LPM. `location_release()` przekazywało nową lokalizację do `PhotoReference.edit()`, które ustawiało `quad=null` i zastępowało położenie prostokątem/punktem.

Oryginalne cztery punkty pozostawały tylko w historii. Renderer i hit-test czytały aktywny `quad`, więc poprzednia ramka znikała; nowa lokalizacja otrzymywała osobny sposób prezentacji i inne położenie etykiety. PPM w miejscu dawnej, już nierozpoznawanej ramki mógł trafić w tło. Gałąź dodawania z `oid=None` tworzy nowy ID, podczas gdy zmiana z rozpoznanym ID edytowała ten sam obiekt. Historia nie zapisuje surowych kliknięć, więc nie przypisujemy konkretnego ciągu gestów operatorowi.

Na zabezpieczonym kodzie sprzed poprawki odtworzono rzeczywisty przepływ menu na syntetycznym materiale:

- po wyborze powodu `location_draft` był aktywny;
- po przeciągnięciu `quad` zmieniał się z czterech punktów na `null`;
- aktywny rekord nie zawierał oryginalnego obrysu lokalizacji;
- w tym kontrolowanym wariancie z prawidłowo trafioną ramką ID pozostał ten sam — problem utraty obrysu występował również bez duplikacji.

Dowód: `old_flow_reproduction.json` oraz `probe_old_flow.py` w katalogu dowodowym opisanym niżej. Poprawka usuwa błędne powiązanie statusu z narzędziem rysowania, nie ukrywa overlayu.

## Nowy przepływ PPM/LPM

Po D i czterech punktach obiekt ma **Dokładną** geometrię. PPM na ramce, etykiecie albo polu inline zachowuje konkretny ID trafionego obiektu, niezależnie od wcześniejszego zaznaczenia.

```text
Numer
  Pełny numer
  Fragment numeru
  Numer nieczytelny
Geometria
  Ucięta krawędzią zdjęcia
  Częściowo zasłonięta
  Granice niewyraźne
  Nie można ustalić pełnego obrysu
  [dla orientacyjnego obrysu] Przywróć dokładną geometrię
Usuń tablicę
```

Wybór statusu zapisuje nową wersję tej samej tablicy, zachowuje jej punkty i tekst, zamyka menu i kończy wszystkie robocze zamiary rysowania. Adapter czyści punkty szkicu, cel rysowania, roboczą lokalizację, stan przeciągania oraz oczekujące otwarcie tekstu po rysowaniu. Canvas wraca do zwykłego trybu z wybraną tablicą.

Następne LPM na tle nie tworzy tablicy. Nowe oznaczenie wymaga D lub świadomego użycia „Dodaj tablicę”. PPM istniejącej ramki nie oferuje przejścia do punktu ani ponownego rysowania czterech narożników.

Starszy obiekt bez obrysu nadal może otrzymać obrys przez „Uzupełnij obrys (D)”. Gdy nie ma nawet lokalizacji obszarowej/punktowej, dostępne jest „Wskaż położenie punktem” z dotychczasowym powodem N/A. Tło oferuje rysowanie obrysu oraz awaryjny punkt z jednoznacznym wyborem „Nie mogę wskazać obszaru — punkt”. Nie ma zagnieżdżonych, powtarzanych list powodów dla punktu.

## Zachowanie danych i kwalifikacja geometrii

Magazyn pozostaje ten sam: `reference_v1.json`. Nowa semantyka wymaga schematu **`alpr.photo_reference.v3`** i `decision_version: 3` w nowych/zmienionych rekordach geometrii. Odczyt nadal obsługuje v1/v2. Sam odczyt nie dodaje pól ani nie zapisuje migracji.

| Pole | Znaczenie |
|---|---|
| `localization_quad` | Zachowane, narysowane przez operatora cztery punkty lokalizacji, w tej samej kolejności i źródłowych współrzędnych. |
| `quad` | Wyłącznie dokładna referencja geometryczna. `null`, gdy geometria jest orientacyjna. |
| `geometry_status` | `EXACT`, `CUT_OFF`, `OCCLUDED`, `BLURRED`, `UNDETERMINED`. |
| `geometry_exclusion_reason` | Jawny powód niepewności; pusty tylko dla dokładnej geometrii. |
| `geometry_kind` | Dla zachowanego orientacyjnego obrysu: `APPROXIMATE_QUAD`; dla dokładnego: `EXACT_QUAD`. Dotychczasowe rodzaje lokalizacji pozostają czytelne. |

Przykład zmiany „Ucięta”: `localization_quad` zawiera **dokładnie poprzednie wartości `quad`**, natomiast `quad=null`, `geometry_status=CUT_OFF`, `geometry_kind=APPROXIMATE_QUAD`. Nie prostujemy ani nie zastępujemy punktów BBOX-em. „Przywróć dokładną geometrię” kopiuje te zachowane punkty do `quad` po jawnej decyzji operatora.

Starego prostokąta orientacyjnego lub punktu nie awansujemy automatycznie na dokładne narożniki. Przy braku narysowanych czterech punktów przywrócenie dokładności jest niedostępne; potrzebny jest świadomy obrys D. Stare `quad=null` bez lokalizacji pozostaje poprawne i nie otrzymuje losowych współrzędnych.

`CanvasReviewEditor._current_quad()` używa obrysu lokalizacji **tylko do renderowania, hit-testu i edycji punktów**. Kanoniczne `scene.objects[].quad` pozostaje `null`; nie zmieniono scorerów. Orientacyjny obrys ma odrębny tag renderowania `photo_approximate_outline`, a nie tag dokładnego `operator_quad`. Korekta narożnika orientacyjnego obrysu nie przywraca sama dokładności.

Tekst jest niezależny: zmiana geometrii zachowuje `gt_text`, `partial_text`, `text_state` i powód nieczytelności. Fragment nadal jest przechowywany poza pełnym `gt_text`, więc nie staje się pełnym numerem GT. Podpis: `Numer: fragment GWE`.

Przy pierwszym przejściu istniejącego dokumentu do v3 powstaje kopia jego dokładnych wcześniejszych bajtów: `reference_v1.pre-v3-<SHA256>.json`. Brak możliwości wykonania kopii blokuje zapis. Pozostają blokada równoległego zapisu, kontrola SHA, zapis atomowy, rewizja, wersje historii i undo/redo. Starsze wersje historii nie są przepisywane.

## Wizualizacja

| Zapisany status | Podpis ramki | Kolor | Linia |
|---|---|---|---|
| `EXACT` | Dokładna | turkusowy `#38E4D3` | ciągła |
| `CUT_OFF` | Ucięta | pomarańczowy `#FF9F43` | przerywana |
| `OCCLUDED` | Zasłonięta | fioletowy `#CF8BFF` | przerywana |
| `BLURRED` | Niewyraźna | niebieski `#65B5FF` | przerywana |
| `UNDETERMINED` | Obrys N/A | szary `#B8C0CC` | przerywana |

Brak jakiejkolwiek zapisanej lokalizacji ma podpis „Lokalizacja N/A”. Zaznaczenie dodaje uchwyty i akcent grubości, zachowując kolor semantyczny. Ramka oraz jej etykieta korzystają z dotychczasowego renderera i przeliczeń `to_source`/`to_canvas`; nie powstał drugi Canvas ani nowy panel.

## Odczyt fotografii 39 i stanu 39/40

Zabezpieczony aktualny plik: **v2, rewizja 422**, 874812 bajtów. W chwili odczytu zapisane stany spełniały formalne kryterium **40/40**. Nie zmieniono licznika ani danych, aby uzyskać ten wynik. Nie jest to potwierdzenie kompletności sceny po wcześniejszych usunięciach.

Fotografia ma SHA `450b50a3cd05fe97b1b6b23e0c139c8ee6bf85ae0b9d82e9d82a505254142ab1` i pozycję 39 w manifeście TV.

| Obiekt | Ustalenie z historii |
|---|---|
| `PGT:f87de896a38641f7ad531d71fb8a3321` — pierwotne `GWE` | Narysowany quad i tekst nadal istnieją w historycznych wersjach. Rewizja 415 zawiera usunięcie tego obiektu z aktywnej sceny. Nie przywracano go. |
| `PGT:fb0a8b175fc543ccab23c55b8223258d` | Dodany w 412, zamieniony na orientacyjny obszar w 413, usunięty w 414. Tekst był pusty/nierozstrzygnięty. |
| `PGT:f9bd5e8224b84a12a532398e595bb136` | Dodany w 416 jako piąty obiekt; w stanach 416–421 pusty tekst `UNRESOLVED` powodował „Uzupełnij” i 39/40. Rewizja 422 zawiera jego usunięcie. |
| `PGT:83730c297830460e99db006c5b3685fd` | Obecnie czwarty aktywny obiekt, z dokładnym quadem i świadomie nieczytelnym numerem. To **inne ID niż usunięte GWE**. |

Nie dysponujemy zapisem surowych gestów ani aktualnego stanu niezapisanego szkicu w pamięci uruchomionej aplikacji. Nie przypisujemy intencji operatorowi na podstawie samych zdarzeń. Jeżeli uruchomione wcześniej okno nadal pokazuje 39/40, może prezentować starszy stan albo szkic; nie należy wymuszać 40/40. Decyzja o ewentualnym odzyskaniu usuniętego GWE wymaga świadomej decyzji operatora.

## Zmienione pliki i funkcje

- `auto_annotation_tool/ranking/photo_reference.py`: `geometry_status`, `localization_outline`, `_explicit_geometry`, `_set_geometry_status`, `PhotoReference.set_geometry_status`; walidacja v3, `add/edit/_change/_save`, kopia przed zapisem nowego schematu.
- `auto_annotation_tool/gui/z4_photo_reference.py`: `context_menu`, `set_geometry_status`, `_end_drawing`, `geometry_style`, `edit`, `geometry_na`, `draw_target`, `text_caption`, renderowanie starszych lokalizacji.
- `auto_annotation_tool/gui/mobile_canvas_editor.py`: `_current_quad`, renderer obrysu/podpisu i inicjalizacja przeciągania narożnika. Działanie dla mobilnego profilu pozostaje oddzielone przez `reference_source`.
- `tests/test_z4_photo_reference_context.py`: aktualizacja oczekiwań dla uproszczonego menu, podpisu fragmentu i schematu v3; zachowane dotychczasowe przypadki trwałości/EXIF/lokalizacji.
- `tests/test_z4_photo_geometry_status.py`: 29 nowych przypadków regresji, w tym niezależność tekstu/geometrii, ID/punkty/style, PPM/LPM, szkice, retry, backup, historia, wznowienie i odczyt aktualnej prywatnej kopii.
- Niniejszy raport.

## Testy

Wszystkie zapisy testowe wykonywano w odseparowanym profilu i katalogu roboczym, na syntetycznych źródłach lub prywatnych kopiach JSON. Produkcyjnego JSON nie używano jako celu zapisu.

| Zakres | PASS | FAIL | SKIP |
|---|---:|---:|---:|
| A1 | 25 | 0 | 0 |
| Poprzednie przypadki PPM/EXIF/zapisu po dostosowaniu kontraktu | 31 | 0 | 0 |
| Nowa regresja statusu geometrii, łącznie z dwoma testami awarii | 29 | 0 | 0 |
| Mobilny Canvas, pełna scena, nawigator i ochrona wyboru | 47 | 14 | 0 |
| Trwałość, scene evidence, historia i GT Pack | 129 | 3 | 0 |
| Odtworzenie powyższych niepowodzeń na kodzie sprzed poprawki | 0 | 17 | 0 |

**GT fotografii: 85/85 PASS.** Szerszy zestaw nie jest w całości zielony. Wszystkie 17 niepowodzeń odtworzono na świeżej kopii kodu sprzed tej poprawki: 9 w `test_z4_one_navigator`, 5 w starszym `test_mobile_p2b2_canvas_gui`, 3 w `test_mobile_p2b2_canvas_review`. Nie naprawiano tych niezwiązanych rozbieżności w ramach zadania.

Testy potwierdzają jeden widoczny polygon na ID, niezmienione punkty po PPM, pięć odrębnych kolorów, odpowiedni styl linii, stabilny hit-test, brak dodatkowego obiektu po LPM, anulowanie wcześniej uzbrojonego szkicu przy zmianie statusu, brak awansu orientacyjnej geometrii przy edycji narożnika, zachowanie tekstu, undo/redo, wznowienie, zoom/pan/resize, EXIF i krawędzie, zgodność starych zapisów oraz N/A dokładnej geometrii.

Bindingi i polecenia menu testowano z zastąpieniem samego natywnego `tk_popup`, żeby test nie czekał na ręczne zamknięcie menu Windows. Wygląd i wygoda rzeczywistego menu pozostają do odbioru operatora. Nie uruchamiano modeli ani nowych metryk.

## Ochrona produkcji i dowody

Kopia wykonana **przed modyfikacją kodu**:

`C:\Users\48572\AppData\Local\Temp\z4_geometry_status_fix_izl6glmm\production_reference_before.json`

Źródło produkcyjne:

`C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\01_materialy\04_GT_FOTOGRAFII_Z4\reference_v1.json`

SHA-256 przed i po:

`b063288d187101121b5e2644f1f97fb3b944eda0ab1fd9db39e8d86324d20195`

Rozmiar i `mtime_ns=1794363676777015700` pozostały takie same. Kontrola 141 chronionych plików nie wykazała zmian SHA, rozmiaru ani czasu modyfikacji. Zakres kontroli obejmuje wskazany zestaw fotografii, manifestów, referencji, istniejących ocen i wcześniej chronionych artefaktów; nie oznacza pełnego skanowania wszystkich archiwów F4/F5A.

Katalog dowodów zawiera `before.patch`, `status_before.txt`, pełną kopię kodu/testów `baseline/`, kopie zmienianych plików, `photo39_history.json`, raport kontroli `verification_receipt.json`, `old_flow_reproduction.json` oraz logi/XML: `photo_second`, `failure_guards`, `mobile_gui`, `persistence`, `baseline_failures`.

Zachowano niezwiązane lokalne modyfikacje. Nie zmieniano Z2, Androida, modeli, scorerów, fotografii ani manifestów. Bez reset/checkout/clean/commit/push.

## Odbiór operatora

1. Jeżeli w starym oknie trwa rysowanie, anuluj szkic przez Esc. Uruchom ponownie Desktop, aby wczytać nowy kod. Wejdź w **Raporty z telefonu → GT fotografii** i otwórz ten sam materiał.
2. Próby zmian wykonaj na prywatnej referencji lub na obiekcie, który świadomie zamierzasz poprawić. Narysuj D cztery punkty, wpisz numer i zatwierdź Enter. Ramka ma być turkusowa z podpisem „Dokładna”.
3. PPM na ramce → Geometria → Ucięta krawędzią zdjęcia. Ma pozostać ta sama ramka, z tymi samymi punktami i numerem, teraz pomarańczowa/przerywana. Menu ma się zamknąć bez oczekiwania na rysowanie.
4. Kliknij LPM na pustym tle. Nie może powstać kolejna tablica, prostokąt ani szkic. Sprawdź też PPM na etykiecie i polu numeru.
5. Sprawdź pozostałe statusy, kolor po zaznaczeniu, „Przywróć dokładną geometrię”, Ctrl+Z/Ctrl+Y oraz `Numer → Fragment numeru`. Tekst i geometria muszą zmieniać się niezależnie.
6. Powiększ/przesuń obraz, sprawdź ramkę przy krawędzi, zapisz tekst Ctrl+S, zamknij i ponownie otwórz ten sam materiał. Sprawdź statusy, położenie oraz brak nowego obiektu.
7. Przy fotografii 39 rozróżnij obiekty po ID i historii: obecna tablica 4 nie jest dawnym `GWE`. Niczego nie usuwaj ani nie przywracaj tylko po numerze porządkowym etykiety.

Odbiór wizualny pozostaje **NOT_VERIFIED** do rzeczywistego potwierdzenia operatora.
