# F5A / Z4 — jedna ocena ekspozycji, GT A1 i dowody MT/MZ

Data: 12.11.2026. Sesja kontrolna: **R1 / r02 / BLOK_B / K02**, `exp-1794265037188-43dc06b8`.

**Odbiór operatora: NOT_VERIFIED. Protokół produkcyjny nie został zatwierdzony przez Codex. Nie wykonano produkcyjnych ocen.**

## 1. Wykorzystane elementy

Pozostały istniejące `SceneReviewWindow`, `SceneCanvasSource`, `CanvasReviewEditor`, drzewo, pasek przebiegu, powiązania A2 oraz wykres „Czasy szczegółowe”. Używany jest ten sam renderer obrazu i ten sam mechanizm zoomu/pan. Zachowano starszy tryb geometrii CameraX i jego testy; zwykły Z4 oraz A3 nie zostały zastąpione.

Zapis korzysta z dotychczasowego `MobileReviewSession._save_change()`: blokady, kontroli rewizji i zapisu atomowego. Eksport nadal przechodzi przez `MobileReviewSession.export()`.

Brakowało decyzji o rozliczeniu całej ekspozycji niezależnej od geometrii CameraX, pokazania A1 jako podstawowego obrazu, oddzielenia raw od konsensusu, jawnego protokołu i eksportu tej oceny.

## 2. Zmienione pliki

| Plik | Zakres |
|---|---|
| `auto_annotation_tool/gui/mobile_f5a_scene_gt.py` | Domyślny widok oceny ekspozycji, oryginalne A1 tylko do odczytu, trzy działania, protokół, nawigacja, raw/konsensus, kolory, korekty i wznowienie kontekstu. |
| `auto_annotation_tool/ranking/mobile_f5a_scene_gt.py` | Przeniesiona z GUI projekcja `timeline_records()`, odczyt dowodów konsensusu, sekcja decyzji w istniejącym sidecarze, `exposure_accounting()`, `operator_results()` i rozszerzenie istniejącego eksportu. |
| `auto_annotation_tool/gui/z4_mobile_report_browser_ux.py` | `sidecar_preview()` pokazuje zapisane decyzje zdjęć osobno od wcześniejszych zatwierdzeń geometrycznego GT. |
| `tests/test_f5a_scene_gt.py` | Prywatne testy decyzji, trwałości, dowodów, regresji starszego trybu i natywnego Tk. |
| `docs/F5A_Z4_OCENA_EKSPOZYCJI_20261112.md` | Ten raport. |

Pozostałe wcześniejsze zmiany w lokalnym worktree zachowano. Nie zmieniano silnika Canvas, normalizacji numerów, modeli ani metryk IoU/Pose. Wykorzystano istniejące `normalize_registration()`.

## 3. Przebieg i dowody

- Kliknięcie **Zdjęcia** pokazuje oryginalną fotografię i jej GT A1. Numery, fragmenty, nieczytelność oraz NO_PLATES pozostają jawne. Narożniki A1 są wyświetlane wyłącznie na oryginale.
- Kliknięcie **Klatki** pokazuje CameraX. Kliknięcie **MT/MZ** wybiera rzeczywiste źródło modelu; powiązane ROI i wskazania są tylko do odczytu.
- Drzewo, Canvas i pasek przebiegu mają wspólny aktywny kontekst. Przeglądanie nie zapisuje oceny.
- Szary oznacza klatkę, turkus MT, pomarańczowy MZ, zielony i ✓ potwierdzenie Androida, czerwony i ! anulowanie/błąd. Zaznaczony rekord ma odrębny obrys. ✓ nie oznacza zgodności z GT.
- Zachowany konsensus bez nowego wykonania MZ jest opisany jako **Pamięć / Konsensus — bez nowego MZ**. Nie zwiększa liczby MZ.
- Szczegóły zawierają rzeczywiste ID, SHA, stemple i zdarzenia `consensus_updated` / `consensus_confirmed`. Zmiany konsensusu nie są syntetyzowane.
- Przypisanie zdjęcia pochodzi z konkretnej klatki A2. `scene_event_id` nie zastępuje tego dowodu. Anulowane/spóźnione wywołanie pozostaje przy swoim wejściu.
- Sekundy klatek opisują ich zapisane pobranie. MT/MZ są ułożone przy źródłach jako relacje po ID, a nie rzekome chwile zakończenia. Zegar zdarzeń i wykres pomiarowy mają własne opisy; nie dodano przeliczenia PC/TV/sensora.

K02: **10 zdjęć, 44 MT, 51 zarejestrowanych uruchomień MZ, 21 różnic raw/konsensus, 16 zdarzeń zmiany konsensusu i 5 zdarzeń potwierdzenia**. Liczba uruchomień nie jest deklaracją tylu poprawnie zakończonych rozpoznań. Wszystkie te zdarzenia dają się powiązać przez zapisane identyfikatory. Zachowano 56 unikalnych klatek / 66 reprezentacji A2.

Test wszystkich 36 archiwów zachowuje 1281 rzeczywistych MT, w tym 1280 przypisanych do ekspozycji oraz jedno poza zbiorem fotografii GT. Dwa rekordy bez identyfikatora MT pozostają diagnostyką, a nie wymyślonymi wywołaniami. Osiem zdarzeń obejmujących różne fotografie zachowuje odrębne przypisania klatek.

## 4. Protokół wymagający akceptacji operatora

Przy pierwszej decyzji program przedstawia opis i wymaga jawnego zatwierdzenia. Odczyt już zapisanego zatwierdzenia nie zatwierdza żadnej kolejnej fotografii. W tej samej przeglądarce można wykorzystać wcześniejszą akceptację identycznego protokołu i wersji A1/A2; jej tożsamość pozostaje w zapisie.

**A — przebieg zapisanych kompletów.** Dla każdego udowodnionego wejścia oddzielnie porównywane są raw i zapisany konsensus. Wywołania dotyczące dokładnie tej samej klatki A2 pozostają jednym kompletem; wyniki kolejnych klatek nie są łączone w „najlepszy komplet”. Wykorzystywane są źródłowe role FINAL, bez ponownego NMS. Zachowane są krotności, braki, dodatkowe odczyty i duplikaty.

Jest to porównanie tekstowych multizbiorów, **nie dowód dopasowania do konkretnej fizycznej tablicy**. Nie ma przypisywania według podobieństwa znaków. Fragment lub nieczytelny numer GT wyłącza miarę pełnej kompletności; nadal wykazywane są znane numery i ich braki. Brak opublikowanego wyniku po anulowaniu pozostaje udokumentowanym niepowodzeniem wykonania, osobno od brakującego dowodu.

**B — diagnostyka „co najmniej raz”.** Czy istnieje zapisany, potwierdzony przez Androida konsensus równy pełnemu numerowi GT? Tak/Nie/N/A, z dowodem i przyczyną. Nie jest to końcowy komplet rozpoznania ani wynik HUD. Dla fotografii bez pełnego numeru GT B jest N/A.

**C — wcześniejsza analiza pierwszego MT.** Odczytywany jest niezmieniony `wyniki.json`, którego SHA jest zgodne z `manifest_wynikow.json`, a powiązanie A1/A2 odpowiada bieżącej referencji. Gdy nie można wskazać jednoznacznego zweryfikowanego pliku, C pozostaje N/A. Nie powstaje zastępczy wynik wybrany według GT.

Brak MT przy udowodnionym zerze wybranych ROI jest pokazany wprost. Dla dodatniego A1 oznacza brak wyniku systemu, nie brak tablic. Dla negatywnego A1 nie powstaje fikcyjny odczyt OCR. Nie liczymy jakości MP. Braki numerów nie są automatycznie nazywane FN samego MT. IoU, NMCE i warunkowa jakość OCR pozostają oddzielne; nowy protokół nie tworzy referencyjnej geometrii CameraX.

## 5. Jedna decyzja operatora

| Działanie | Zapis |
|---|---|
| Potwierdź ocenę / Spacja | `CONFIRMED`: operator sprawdził rozliczenie; nie znaczy to, że ALPR rozpoznał poprawnie. |
| Zgłoś błąd | `ERROR_REPORTED`, krótki powód i wybrany dowód; przypadek czeka na wyjaśnienie. |
| Nie można ocenić | `NOT_ASSESSABLE`, obowiązkowy powód. |
| Więcej → popraw przypisanie / ocenę B | `CORRECTED`, powód; zmienia rozliczenie operatora, nie A1/A2 ani predykcję. |
| Ctrl+Z / Ctrl+Y | Cofnięcie / ponowienie zapisanej decyzji. Cofnięcie pierwszej oceny przywraca stan nieoceniony. |

Przycisk **Dalej** i zwykłe przeglądanie nigdy nie zatwierdzają. Ctrl+S nie tworzy nowej oceny: ponawia niedokończony zapis albo przypomina o autosave. Nie trzeba zatwierdzać MT, MZ, klatek ani ROI pojedynczo. Nie ma obowiązkowego rysowania.

## 6. Trwałość i eksport

W dotychczasowym sidecarze, pod `provenance.f5a_scene_gt_v1.exposure_review`, zapisywana jest wersjonowana sekcja `alpr.mobile.f5a_exposure_review.v1`. Nie powstaje drugi magazyn GT. Starsze `reviews` geometrii oraz sekcja A3 pozostają zachowane.

Decyzja zawiera `OPERATOR_EXPLICIT`, sesję/serię, exposure_id, oryginalny i ewentualnie skorygowany SHA fotografii, SHA A1/A2 i archiwum, identyfikator/hash protokołu, autora, czas, rewizję, powód, kontekst i listę obejrzanych dowodów. Historia przechowuje poprzednie wersje także po cofnięciu. Otwarcie wznawia ostatni zapisany kontekst, np. konkretne MZ.

Nieudany zapis nie zwiększa postępu i nie zmienia poprzedniego pliku. Operacja pozostaje w pamięci do „Ponów zapis”; nawigacja jest blokowana do jej rozstrzygnięcia. Diagnostyka zachowuje traceback, ale okno pokazuje krótki komunikat.

Eksport do nowego katalogu rewizji zachowuje dotychczasowe pliki i dodaje:

- `f5a_exposure_reviews.json` — oddzielone propozycje automatyczne, decyzje, korekty, historia, A/B/C, źródła, N/A, czasy i mianowniki;
- `f5a_operator_decisions.csv` — wszystkie zdjęcia, w tym `UNREVIEWED`;
- `f5a_recorded_outputs.csv` — komplety raw/konsensusu i niepowodzenia dla zapisanych wejść;
- `f5a_source_timings.csv` — oryginalne rekordy czasowe, bez utożsamiania ich z pobraniem klatki.

Manifest eksportu zawiera SHA plików. Podsumowanie zweryfikowane obejmuje wyłącznie `CONFIRMED`/`CORRECTED`; zgłoszone błędy, operatorskie N/A i nieocenione zdjęcia mają odrębne liczniki. Mianowniki A dotyczą wejść, B ekspozycji. Eksport jednej sesji nie deklaruje oceny całych 360 ekspozycji. Wcześniejszy raport pierwszego MT nie jest nadpisywany.

## 7. Testy i ograniczenia

Wszystkie testy zapisujące korzystały z prywatnych kopii i sidecarów oraz izolowanego profilu użytkownika.

| Zakres | Wynik |
|---|---|
| Aktualny zestaw `test_f5a_scene_gt.py` | **47/47 przypadków ma końcowy PASS**, na podstawie przebiegu głównego i testów uzupełniających po poprawkach. Zestaw obejmuje wszystkie 36 sesji / 8 mieszanych zdarzeń, K02, raw/konsensus, protokół, decyzje, błędy zapisu, powtórzenie zapisu, historię, sidecar JSON, eksport, natywne zdarzenia Tk, korektę i jej cofnięcie, NO_PLATES oraz brak klatki. |
| Zoom/pan i starszy zapis GT — ponowienie | **3 PASS**: 1000×700, 1450×780 oraz zapis/wznowienie starszego geometrycznego GT. |
| Nawigacja i korekta, oba tryby R0/R2 | **5 PASS**. |
| N/A przy brakującej klatce, stary i nowy tryb | **2 PASS**. |
| Regresje danych/importu, przeglądarki, A3 i ręcznego Canvas | **172 PASS / 3 FAIL / 0 SKIP**; 54 testy natywne wyłączone z tego przebiegu. Wszystkie 3 FAIL odtworzono na kopii kodu sprzed zadania. |
| Zwykła ręczna weryfikacja, brak oceny MP i wykresy | **41 PASS / 2 FAIL** w pierwszym przebiegu; oba FAIL były timeoutami uzyskania fokusu Tk. Osobne ponowienie tych dwóch przypadków: **2 PASS**. |

W przebiegu głównym dedykowanego zestawu wystąpiły dwa błędy: przerwanie zoomu w małym oknie przy zmianie wysokości opisu oraz timeout testu inline starszego trybu. Po ustabilizowaniu wysokości istniejących etykiet oba testy przeszły. Nie zmieniono mechanizmu zoomu. Dodatkowy test brakującej klatki wykrył odwołanie hover do poprzedniej transformacji; wyczyszczenie centrum widoku wraz z bitmapą usunęło ten callback. Końcowy rejestr pokrycia zawiera tylko aktualne 47 nazw testów i ostatni wynik każdego z nich — nie sumuje powtórzeń jako nowych przypadków.

Trzy istniejące błędy szerszych regresji dotyczą `test_mobile_p2b2_canvas_review.py`:

- `test_flags_keep_geometry_and_gt_and_distinguish_model_vs_operator` — stary oczekiwany tekst komunikatu;
- `test_correcting_gt_invalidates_checked_scene` — oczekiwanie dotyczące `verification_issues`;
- `test_zero_detection_requires_whole_roi_confirmation` — oczekiwanie licznika starego zatwierdzenia ROI.

Ich oczekiwań ani implementacji nie zmieniano. **Nie deklarujemy pełnej zielonej regresji całego repozytorium.**

Logi JUnit, zestawienie `final_test_coverage.json`, kopia kodu sprzed zadania, dokładny diff tego zadania i audyt źródeł znajdują się w:

`C:\Users\48572\AppData\Local\Temp\z4_f5a_operator_zl0lh36n`

Kontrola końcowa: **2384/2384 chronione pliki bez zmian SHA-256, rozmiaru i mtime** (`protected_final.json`). Porównanie kodu z kopią początkową wykazało zmiany wyłącznie w trzech wymienionych plikach programu i jednym pliku testów; dodatkowo utworzono ten dokument. Nie modyfikowano źródeł Androida, APK, modeli, archiwów, produkcyjnego A1/A2/A3 ani historycznych ocen i wyników. Nie uruchamiano inferencji, treningu, pomiarów, commit/push/reset/checkout/clean/stash.

Kontrolne SHA-256:

```text
A1 reference_v1.json:
e7af93284b427925fa072e5f5315a4caecb5c90bb4095038d72fddaf6c1c7e82
A2 mapping.json:
49c7d0956d687f5caed62dfef5bcf31652b8d6b5843e31b984a0e2237e4b0848
K02 F5A_R1_r02_BLOK_B_K02.alprsession:
140c20115cf34c67de7e591752b540d152ec07fea2bf7488a8546e97d8899a10
```

Odbiór operatora pozostaje **NOT_VERIFIED**. Brak pełnej historii wyboru/czyszczenia HUD w archiwach nadal uniemożliwia uznanie konsensusu za udowodniony końcowy wynik telefonu.

## 8. Krótki odbiór K02

1. Uruchom ponownie Desktop z `C:\Users\48572\Desktop\dyplom\start4`, aby wczytać aktualny kod.
2. W **Raporty z telefonu** wybierz R1 / r02 / BLOK_B, notatka `BLOK_B · 10x30 s · KOREKTA_K02`; sprawdź session_id `exp-1794265037188-43dc06b8` w szczegółach.
3. Otwórz istniejącą weryfikację **F5A — GT sceny**. Domyślnie zobaczysz oryginalne A1 i dziesięć zdjęć. Nie wybieraj asysty A3.
4. Wybierz zdjęcie, następnie MT lub MZ z drzewa albo paska. Sprawdź raw, konsensus i potwierdzenie Androida. Na zdjęciu 2 sprawdź oba numery; na 5 jawne NO_PLATES; na 6 zmiany konsensusu. Szczegóły odsłaniają dowody źródłowe.
5. Przed pierwszą decyzją przeczytaj i samodzielnie zatwierdź protokół. Wybierz jedną ocenę zdjęcia. Błąd/N/A wymaga krótkiego powodu. Niczego nie trzeba rysować.
6. Sprawdź Ctrl+Z/Y, Dalej bez oceny, zoom/pan, zamknięcie i wznowienie na ostatnim zapisanym dowodzie. Po rzeczywistej ocenie użyj Eksportu do nowego katalogu.

Te czynności są instrukcją odbioru, a nie deklaracją jego zaliczenia.
