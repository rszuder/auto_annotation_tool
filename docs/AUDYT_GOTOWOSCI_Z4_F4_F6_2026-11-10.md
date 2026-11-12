# Audyt gotowości Z4 do pełnego planu eksperymentów F4–F6

**Data audytu:** 10.11.2026  
**Repozytorium Desktop:** `C:\Users\48572\Desktop\dyplom\start4`  
**Repozytorium Android:** `C:\Users\48572\AndroidStudioProjects\ALPR_v1`  
**System:** Windows 10  
**Zakres:** F4, F5A, F5B, F6 oraz przygotowanie wyników F7  
**Tryb audytu:** tylko odczyt kodu, archiwów, manifestów, ocen i istniejących wyników testów  
**Status całości:** **PARTIAL**

Dokument utrwala audyt przedstawiony w rozmowie. Utworzenie tego pliku nie oznacza implementacji opisanych rekomendacji ani ponownego wykonania testów, pomiarów lub odbioru GUI.

## 1. Werdykt

**Z4 jest dobrą wspólną bazą dla F4–F6, ale obecnie nie jest gotowym, kompletnym weryfikatorem całego planu.**

Nie ma potrzeby budowania drugiego Canvas ani wracania do rozbudowy Z2. Istnieją już mechanizmy odczytu źródeł, edycji, identyfikacji, zapisu, historii, obliczeń i eksportu. Brakuje przede wszystkim spójnego kontraktu niezależnego GT, powiązania materiału z obserwacjami oraz końcowych metryk na poziomie obserwacji.

Możliwość ukończenia pracy bez dużej przebudowy jest oceniana pozytywnie, ale warunkowo: **kod nie odtworzy dowodów, których nie zapisano**. Nierozstrzygalne przypadki muszą pozostać N/A. Nie proponuje się powtarzania zakończonych pomiarów.

Wspólny weryfikator powinien opierać się na jednym kontrakcie ocen i istniejącym Canvas. Różnice między eksperymentami powinny dotyczyć źródeł, jednostki obserwacji, kwalifikacji i agregacji wyników, a nie mnożenia edytorów i magazynów GT.

### Znaczenie statusów

| Status | Znaczenie w tym audycie |
|---|---|
| **READY** | Funkcja i wymagane dowody są potwierdzone w określonym zakresie. Nie oznacza akceptacji całego eksperymentu ani GUI. |
| **PARTIAL** | Funkcja istnieje, ale ma ograniczenia lub brakuje części wymaganych dowodów. |
| **MISSING** | Funkcji nie ma albo nie obsługuje wymaganego kontraktu. |
| **NOT_VERIFIED** | Nie można jeszcze potwierdzić wymaganego stanu na podstawie sprawdzonych danych. |
| **N/A** | Funkcja nie dotyczy danego eksperymentu albo konkretna miara nie jest dostępna; przy miarach należy zachować powód. |

Nie klasyfikowano funkcji jako READY wyłącznie na podstawie testu syntetycznego. Istnienie kodu, zaliczenie testu, zatwierdzenie raportu i odbiór operatora są odrębnymi dowodami.

## 2. Ustalenia z rzeczywistych danych

| Obszar | Potwierdzony stan |
|---|---|
| Magazyn Desktop | **83 raporty**. |
| F4 — `E-MOB-QINT8-01` | 12 archiwów; wszystkie SHA zgodne z indeksem. Wszystkie 12 ocen ma `COMPLETED` i tryb `assisted`. |
| Eksporty F4 | 12 eksportów zgodnych z aktualnymi sidecarami. Sprawdzono **570 plików** wskazanych w manifestach eksportu — bez błędów SHA. |
| Zakres metryk F4 | Eksporty zawierają **231 zakwalifikowanych jednostek z 237**. Osiem wyników ma status `COMPLETE`, cztery `PARTIAL`. Zatwierdzenie raportu nie oznacza dostępności każdej miary. |
| F5A | **36 archiwów** o zgodnych SHA; po 12 sesji R0, R1 i R2. Zapisane polityki ROI odpowiadają wariantom. Wszystkie używają `TV_BBOX_CROP`. |
| Materiał F5A | **40 plików i 40 unikalnych SHA**. Zbiory SHA odpowiadają manifestom Sortowni i TV. |
| Zdarzenia F5A | **386 zdarzeń scen**, nie 360: 17 sesji ma 10 zdarzeń, 15 ma 11, dwie mają 12, jedna 13, jedna 14. |
| Powiązania klatek F5A | Tylko **130 z 1281** rekordów wywołań MT ma stamp identyczny z reprezentatywną SCENE_FRAME swojego zdarzenia. Sama zgodność stampu nie przesądza jeszcze o kwalifikacji do metryk. |
| K02/B | Potwierdzone: **10 scen, 44 MT, 51 MZ, 53 FINAL**, cztery nierozstrzygnięte role i trzy anulowane wywołania. Żadne z 44 wejść MT nie ma stampu reprezentatywnej SCENE_FRAME. |
| Oceny właściwego F5A | W sprawdzonym produkcyjnym katalogu ocen Z4 brak sidecarów dla tych 36 archiwów. |
| Zachowane GT fotografii | `current_work.alprgt` zawiera zakres 40 obrazów, ale jeden zapisany rekord obrazu: świadome `NO_PLATES` dla pierwszego DAY_0. Nie jest to ukończone GT czterdziestu zdjęć. |
| Niezależność materiału | Manifest Sortowni ma `independence.status=INCOMPLETE`: brakuje pełnego kontraktu wymaganych modeli i ich rodziców. |
| F5B i F6 | Sprawdzone katalogi `F5B-AZ-A12-01` i `E-FINAL-ALPR-01` nie zawierają plików. Nie potwierdzono wykonanej kohorty F5B ani niezależnego final_test. |

**Numer bloku obserwacji nie może zastępować identyfikatora fotografii.** Rozbieżność 386 zdarzeń wobec 360 planowanych ekspozycji pokazuje to na rzeczywistych danych.

### 2.1. Źródła danych

Sprawdzono przede wszystkim:

- `Workspace\7_rankings\mobile_packages\mobile_package_experiments.json`;
- produkcyjny katalog `Workspace\7_rankings\mobile_packages\human_reviews`;
- oryginalne archiwa wskazane przez indeks dla `E-MOB-QINT8-01` i właściwego `F5A-ROI-A12-01`;
- istniejące eksporty F4 w `C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\E-MOB-QINT8-01\03_wyniki`;
- `F5A-ROI-A12-01\01_materialy\02_MATERIAL_ZATWIERDZONY\sorting_manifest.json`;
- `F5A-ROI-A12-01\01_materialy\03_POKAZ_TV\manifest_blokow.json`;
- `F5A-ROI-A12-01\01_materialy\02_MATERIAL_ZATWIERDZONY\current_work.alprgt`;
- katalogi planowanych F5B i F6.

W archiwach odczytywano metadane sesji i raportu, manifesty modeli, rekordy scen, ról MT, prób oraz telemetrię. Weryfikacja SHA archiwów względem indeksu i plików eksportu względem ich manifestów nie jest deklaracją nowego odbioru GUI ani ponownego wykonania pomiarów.

### 2.2. Tożsamość badanego K02/B

```text
C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\03_uzupelnienia\R1\PAIRED_ROI_01\r02\F5A_R1_r02_BLOK_B_K02.alprsession
```

- `session_id`: `exp-1794265037188-43dc06b8`;
- SHA-256: `140c20115cf34c67de7e591752b540d152ec07fea2bf7488a8546e97d8899a10`;
- tryb: `static`;
- polityka: `r1_one_roi`;
- wejście: `TV_BBOX_CROP`;
- stabilność: `NOT_ASSESSED`, czyli brak podstaw do deklarowania potwierdzonej stabilności.

## 3. Inwentaryzacja istniejących mechanizmów Z4

Oznaczenia C1–C8 są również używane w macierzy gotowości.

| Mechanizm i kod | Faktycznie obsługiwany zakres | Źródła i trwałość | Dowody oraz ograniczenia |
|---|---|---|---|
| **C1. Importer i bundle:** [mobile_package_experiments.py](../auto_annotation_tool/ranking/mobile_package_experiments.py), `ReportBundleReader`, `read_mobile_report_bundle()`, `plan_mobile_session_import()`, `import_mobile_session_plan()` | Odczyt archiwów, walidacja, indeksowanie, import folderów, identyfikacja duplikatów. `MobileReportBundle` przechowuje próby, próbki, zdarzenia, ślady, sceny, role MT, metadane modeli i TV. | ZIP, manifesty i SHA; indeks w `mobile_package_experiments.json`. Oceny pozostają osobno. | Istniejące testy UX02: 91 PASS. Rzeczywiste 48 archiwów F4/F5A zgodne z zapisanymi SHA. Stary raport nie otrzymuje automatycznie brakujących dowodów scen. |
| **C2. Oceny i zapis:** [mobile_human_review.py](../auto_annotation_tool/ranking/mobile_human_review.py), `MobileReviewSession`, `MobileHumanReview`, `_save_change_locked()` | Indeks źródeł, decyzje, rewizje, kontrola tożsamości i atomowy zapis. | Sidecar `human_reviews/<SHA>.review.json`; `subjects`, `attempt_annotations`, `invocation_annotations`, `scene_annotations`, `sample_annotations`. | Dwanaście rzeczywistych ocen F4 odpowiada eksportom. Testy zapisu/wznowienia istnieją. Zapisanej oceny nie można bezwarunkowo przenieść na inne archiwum lub obraz. |
| **C3. Pełna scena:** [mobile_scene_frame_review.py](../auto_annotation_tool/ranking/mobile_scene_frame_review.py), `add_plate()`, `edit()`, `confirm_empty()`, `restore()`, `coverage()` | Wiele fizycznych tablic, jawny brak tablic, tekst lub powód N/A, geometria lub powód jej braku, historia. | `alpr.mobile.scene_frame_review.v1`, `scene_annotations`, identyfikatory `PGT:…`, `source_binding`, `scene_history_v1`. Wymaga zapisanej SCENE_FRAME. | Testy pełnych scen Tk: 13 PASS; nowa nawigacja: 31 PASS. **Zapis jest obecnie ASSISTED, nie niezależny.** Brak odbioru pełnego F5A przez operatora. |
| **C4. Canvas MT i fizyczne GT:** [mobile_canvas_review.py](../auto_annotation_tool/ranking/mobile_canvas_review.py), `scene()`, `_store()`; [mobile_candidate_stacks.py](../auto_annotation_tool/ranking/mobile_candidate_stacks.py) | Edycja GTR/GTZ, wybór FINAL, relacje wskazań do fizycznych tablic, korekty, usuwanie, historia i autosave. | Istniejące adnotacje wywołania, `canvas_review_v1`, rejestr fizycznych GT i powiązanie ze źródłem. | Użyte w rzeczywistych ocenach F4. Zakres to konkretny obraz/wywołanie/ROI; nie jest to globalna tożsamość tablicy przez całą sesję. |
| **C5. Metryki:** [mobile_mt_object_evaluation.py](../auto_annotation_tool/ranking/mobile_mt_object_evaluation.py), `score_unit_v2()`, `evaluate_session()`; [mobile_object_mz_quality.py](../auto_annotation_tool/ranking/mobile_object_mz_quality.py), `score_readout()`; [mobile_pose_metrics.py](../auto_annotation_tool/ranking/mobile_pose_metrics.py) | TP/FP/FN, duplikaty FINAL, geometria BBOX/Pose, Exact i CER kwalifikowanych odczytów. | Źródłowo potwierdzone role, zapisane GT i relacje. Wyniki pochodne są eksportowane z identyfikatorem polityki. | Rzeczywiste eksporty F4. Polityka `F4-EVAL-2.0` jest retrospektywna i ASSISTED; nie zastępuje pełnego E2E sceny. |
| **C6. Bloki obserwacji:** [mobile_canvas_observation_blocks.py](../auto_annotation_tool/gui/mobile_canvas_observation_blocks.py), `build_blocks()`, `render()`, `select()` | Grupowanie statycznych sesji według dowodów zdarzeń; osobne źródła sceny i MT; diagnostyka niepewnych powiązań. | Model przejściowy w pamięci. Nie zapisuje GT ani nowych metryk. | 31 testów PASS, w tym prywatny K02. Nie dowodzi stabilności, tożsamości fotografii ani wspólnej geometrii klatek. |
| **C7. Analiza i porównanie:** [mobile_analysis.py](../auto_annotation_tool/gui/mobile_analysis.py), `_source()`, `analyze()`; [mobile_comparison_core.py](../auto_annotation_tool/gui/mobile_comparison_core.py), `load_session_export()`, `validate_selection()` | Kontrola źródeł, świeżości eksportów, konfiguracji i kohort; porównania sesji; osobne scenariusze. | Archiwum, zatwierdzony eksport, rewizja sidecara, SHA modeli/APK i rejestr F4. | Są rzeczywiste eksporty i porównania F4. E2E pozostaje `SCENE_UNMAPPED`. Opcja „F5B” w słowniku pytań nie oznacza kompletnej obsługi F5B. |
| **C8. Eksport do pracy:** [mobile_thesis_report.py](../auto_annotation_tool/ranking/mobile_thesis_report.py), `export_thesis_bundle()`; [mobile_analysis_export.py](../auto_annotation_tool/gui/mobile_analysis_export.py), `export_analysis()` | CSV/JSON, raporty, wykresy i materiały do pracy, manifesty zależności. | Eksport powiązany ze źródłem, rewizją oceny i polityką metryk. | 570 sprawdzonych zależności rzeczywistych eksportów F4. Eksport nie uzupełnia brakujących mianowników ani dowodów niezależności. |

### 3.1. Oceniona scena a kompletne GT

W obecnym modelu trzeba rozróżniać **„oceniono obecność/geometrię sceny”** od **„GT jest kompletne do wszystkich metryk”**.

`add_plate()` ustawia potwierdzenie obiektu, a kompletność sceny opiera się na `scene_confirmed`. Nie wymusza to automatycznie kompletnego tekstu każdej tablicy. `progress()` pełnej sceny zwraca ponadto `metric_complete=False`.

Dotychczasowych znaczników kompletności operacyjnej nie należy bez nowego kontraktu traktować jako potwierdzenia niezależnej, wyczerpującej referencji dla końcowej oceny.

### 3.2. Trwałość i tożsamość

Obecny zapis wiąże ocenę z archiwum, sesją i właściwym źródłem obrazu. Pełna scena zachowuje `scene_event_id`, SHA archiwum, wpis obrazu, rozmiar oraz `source_stamp`; z tych danych wynika `source_binding`.

Historia pełnej sceny ma własne stany i kursor cofania/ponawiania wewnątrz dotychczasowego sidecara. Nie wymaga tworzenia fikcyjnego wywołania MT. Z kolei oceny MT pozostają przypisane do rzeczywistych wywołań, ich źródeł i ROI.

Istniejących ocen nie należy przenosić do nowego magazynu ani nadpisywać podczas integracji niezależnego GT.

## 4. Macierz gotowości funkcjonalnej

`READY` dotyczy wyłącznie wskazanego zakresu, nie całego eksperymentu ani odbioru GUI.

| Eksperyment | Wymagana funkcja | Obecny stan | Dowód w kodzie | Dowód w danych | Brak | Minimalne konieczne działanie |
|---|---|---|---|---|---|---|
| Wspólne | Tożsamość archiwum i trwałość ocen | **READY** | C1–C2 | SHA 48 archiwów; 12 zgodnych ocen i eksportów F4 | Nie obejmuje niezależności GT | Zachować istniejący kontrakt |
| Wspólne | Niezależne GT pełnej sceny przed predykcjami | **MISSING** | C3 zapisuje `independent_gt=False`; C4 jest ASSISTED | Oceny F4 są asystowane | Pełny etap niezależnego GT w Z4 | Odizolować etap GT w tym samym Canvas i wersjonować pochodzenie |
| Wspólne | Negatywy, wiele tablic, tekst/geometria N/A | **PARTIAL** | C3–C4 | Testy źródłowych fixture; zachowane NO_PLATES w GT Pack | Odbiór na pełnej kohorcie F5A | Użyć istniejących decyzji; zweryfikować kompletność dla konkretnej miary |
| F4 | Pary FP32/INT8 i checkpointy | **READY** | `mobile_f4_variant.resolve()`, `validate_selection()` | 12 archiwów; wspólny checkpoint MT i MZ; jedno SHA APK | Nie dowodzi identycznych obrazów | Zachować rejestr SHA/scenariusz/powtórzenie |
| F4 | Pełne INT8 kontra mixed/hybrid | **PARTIAL** | `tflite_precision.analyze_tflite_bytes()` i kontrola manifestów | Manifesty MT/MZ: statyczne grafy `INT8`; wykonanie `UNVERIFIED` | Dowód arytmetyki wykonanych kerneli | Oddzielić klasyfikację grafu od dowodu wykonania |
| F4 | Te same sceny i parowanie obrazów | **PARTIAL** | Ostrzeżenia C7 | DAY/NIGHT i powtórzenia są zidentyfikowane | Pełne parowanie fotografii/klatek | Raportować ograniczenie; używać wyłącznie udowodnionych par |
| F4 | Exact, CER, geometria, no-read | **PARTIAL** | C5 | 231/237 zakwalifikowanych jednostek; cztery eksporty PARTIAL | Pełny mianownik całych scen | Zachować warunkowe miary i jawne wyłączenia |
| F4 | Czasy MT/MZ/pipeline, pamięć, rozmiar | **PARTIAL** | C7; telemetria Androida | Czasy, rozmiary i PSS w części sesji | PSS nie wszędzie; nie każdy czas MZ jest czasem pojedynczego wywołania | Pokazywać jednostkę, liczność i N/A |
| F4 | DAY/NIGHT i agregacja powtórzeń | **PARTIAL** | Rejestr F4, wykresy per scenariusz | Po trzy powtórzenia wariantów w scenariuszach | Jednoznaczna agregacja naukowa ponad sesjami | Ustalić poziom agregacji i nie traktować powtórzeń planszy jako niezależnych obiektów |
| F5A | Materiał i kohorta R0/R1/R2 | **PARTIAL** | C1, `mobile_experiment_identity.from_bundle()` | 40 SHA; 36 zgodnych sesji | Pełna kontrola niezależności materiału | Domknąć inwentarz modeli, rodziców i użytych zbiorów |
| F5A | Nawigacja po zdarzeniach | **PARTIAL** | C6 | K02 i rejestry 386 zdarzeń | Odbiór operatora na całej kohorcie | Sprawdzić różne liczby zdarzeń i przypadki przejściowe |
| F5A | Fotografia → obserwacja | **MISSING** | Brak pełnej mapy konsumowanej przez C7 | Jest manifest kolejności TV | Potwierdzone przypisanie do rzeczywistych klatek | Powiązać SHA fotografii ze zdarzeniem i klatką; nie używać samej kolejności |
| F5A | GT fotografii → CameraX | **MISSING** | `mobile_tv_bbox_evidence` obsługuje przesunięcie cropu | `H_TV=NOT_APPLIED`; różne stampy | Zweryfikowana transformacja i jej zakres ważności | Wykorzystać istniejącą kalibrację jako wejście, zweryfikować mapowanie treści obrazu |
| F5A | Pominięcia poza ROI | **PARTIAL** | C3 `coverage()` | 197/386 scen ma wykonane MP ze zgodnym stampem | Pozostałe źródłowe powiązania i GT | Liczyć pokrycie tylko na właściwej klatce |
| F5A | Jedna fizyczna tablica raz na obserwację | **PARTIAL** | Fizyczne GT i relacje C3–C5 | Działa wewnątrz jednostki oceny | Tożsamość między klatkami/wywołaniami | Powiązać z referencyjnym ID tablicy, bez scalania po OCR |
| F5A | Kompletne E2E per observation | **MISSING** | C7 jawnie zwraca `SCENE_UNMAPPED` | Brak zakończonego GT właściwej kohorty | Okna, reguła wyniku, pełny mianownik | Dodać wersjonowaną agregację obserwacji |
| F5B | Ciągłość tablicy przez kolejne klatki | **PARTIAL** | Android `ResearchSampleIdentity`; źródłowe indeksy C2 | Brak właściwej kohorty F5B | Potwierdzenie tożsamości przy zmianie/zerwaniu tracku | Adapter sekwencji w istniejącym Canvas |
| F5B | Zdarzenia AZ i zoom przed/po | **PARTIAL** | `MainActivity`, `MetricsCollector`, `ResearchSessionStore` | Kod zapisuje zdarzenia i współczynnik zoomu | Pełne powiązanie zdarzenia z konkretną obserwacją i klatką | Domknąć kontrakt przed planowanym F5B |
| F5B | Pierwszy poprawny wynik i wynik w oknie | **PARTIAL** | C2 ma pomocnicze miary per subject | Brak danych właściwego F5B | Czas dostępności wyniku, początek okna i stabilna tożsamość | Rozdzielić istniejące przybliżenie od docelowej miary |
| F5B | Kontrolowane OFF/ON w analizatorze | **MISSING** | C7 nie klasyfikuje pełnej kohorty F5B | Katalog F5B pusty | Specyficzna kwalifikacja i agregacja | Rozszerzyć istniejący analizator o kontrakt OFF/ON |
| F6 | Niezależna kohorta final_test | **NOT_VERIFIED** | Są kontrole inwentarzy w kalibracji | Katalog finalny pusty; statusy `NOT_VERIFIED` | Manifest niezależnego zbioru | Zatwierdzić kohortę przed końcową oceną |
| F6 | Zamrożenie konfiguracji i pochodzenie | **PARTIAL** | Manifesty modeli, konfiguracja wykonania, SHA APK | Dobre dowody F4/F5A | Konkretny, zatwierdzony pakiet finalny | Zamrozić wskazane artefakty i wszystkie istotne ustawienia |
| F6 | Raport wszystkich kwalifikowanych scen | **MISSING** | C7 jawnie odrzuca F6 jako porównanie F4 | Brak finalnego raportu | Niezależny kontrakt oceny końcowej | Adapter raportu F6 nad wspólnymi danymi i scorerami |
| F7 | Materiały do pracy | **READY** w istniejącym zakresie | C8 | Rzeczywiste eksporty F4 o poprawnych SHA | Nowe wyniki F5A/F5B/F6 wymagają swoich kontraktów | Rozszerzać zawartość eksportu, zachowując mechanizm |

Grupowanie statyczne według zmian sceny ma status **N/A dla dynamicznego F5B**. Dotychczasowy adapter prawidłowo nie włącza go bezwarunkowo.

## 5. Wspólny kontrakt czynności operatora

Rekomendowane są dwie fazy pracy na tym samym Canvas: ustalenie referencji i późniejsza weryfikacja inferencji. Nie powinny prowadzić do ponownego zatwierdzania decyzji już jednoznacznie zapisanych.

### 5.1. Faza A — referencja przed ujawnieniem predykcji

1. Operator widzi pełny obraz bez wskazań MP/MT i tekstów MZ.
2. Wybiera świadome `NO_PLATES` albo oznacza fizyczne tablice.
3. Dla każdej tablicy zapisuje geometrię albo przyczynę jej niedostępności.
4. Zapisuje tekst albo przyczynę N/A tekstu. Puste pole pozostaje nieuzupełnione.
5. Aplikacja ustala kompletność na podstawie istniejących decyzji, bez kolejnego obowiązkowego kliknięcia dla każdej tablicy.
6. Rewizja referencji i moment ujawnienia predykcji pozostają audytowalne.

Kompletność referencji powinna oznaczać rozstrzygniętą obecność tablic oraz — dla każdego obiektu — tekst/N/A i geometrię/N/A. Nie wolno wymuszać sztucznych narożników ani fikcyjnych tekstów.

### 5.2. Faza B — weryfikacja inferencji

Po ujawnieniu wyników operator rozstrzyga:

- niejednoznaczne wskazania FINAL;
- relacje wskazań do fizycznych tablic;
- duplikaty wskazań tej samej tablicy;
- niepewne powiązania źródłowe;
- przypadki wymagające interpretacji obrazu lub jawnego powodu N/A.

Operator nie przepisuje ponownie ustalonego GT. Nie liczy ręcznie TP/FP/FN, CER, IoU, NMCE, liczności ani opóźnień. Aplikacja oblicza je z zapisanych decyzji i dowodów źródłowych.

### 5.3. Podział odpowiedzialności

| Decyzja lub obliczenie | Operator | Aplikacja |
|---|---|---|
| Świadomy brak tablic na scenie | Potwierdza `NO_PLATES` | Zapisuje decyzję i sprawdza jej spójność |
| Fizyczne tablice, geometria i tekst referencyjny | Ustala lub podaje powód N/A | Zachowuje ID, źródło i historię |
| Niejednoznaczna tożsamość fotografii/tablicy | Rozstrzyga na podstawie dowodów | Nie scala po samym OCR, podobieństwie lub numerze wiersza |
| Niejednoznaczne relacje FINAL ↔ GT | Potwierdza relację albo odrzuca wskazanie | Stosuje ustaloną politykę dopasowania i zliczania |
| TP/FP/FN, duplikaty, Exact, CER, IoU, NMCE | Nie liczy ręcznie | Oblicza dla kwalifikowanej populacji |
| Czasy i liczba wywołań | Nie szacuje braków | Odczytuje rzeczywistą telemetrię, zachowując jednostkę i domenę czasu |
| Brak dowodu wykonania lub nieustalona rola | Nie tworzy zastępczego faktu | Utrzymuje N/A i powód |

### 5.4. Zaślepienie i niezależność

Obecny `blinded_gt_v1` **nie wystarcza do uznania całego Canvas za niezależną ocenę**. `predictions_visible()` chroni tekst predykcji w dotychczasowej ścieżce, ale:

- Canvas MT jest oparty na źródłowych wskazaniach modelu;
- jego zapis przechodzi na tryb asystowany albo blokuje zmianę zablokowanej oceny zaślepionej;
- pełna scena ma wprost `ASSISTED_SCENE_FRAME` i `independent_gt=False`.

Nie wolno zmieniać wcześniejszym ocenom etykiety ASSISTED na niezależne. Osobnego wykazania wymagają:

1. **niezależność sposobu anotowania** — referencja bez ujawnionych predykcji;
2. **niezależność materiału** — rozłączność z treningiem, walidacją, kalibracją i materiałem użytym do wyboru konfiguracji.

### 5.5. Zero, N/A i nieukończona ocena

Brak tablic, nieuruchomione MZ, wykonane MZ z pustym wynikiem, anulowanie i brak dowodu to różne przypadki.

- Pusty wykaz polygonów bez decyzji nie oznacza `NO_PLATES`.
- N/A tekstu nie usuwa automatycznie tablicy z oceny detekcji.
- N/A geometrii nie musi usuwać tablicy z oceny tekstu.
- Sam BBOX nie zastępuje referencyjnego polygonu Pose.
- Brak dowodu wykonania nie jest wykonanym odczytem z pustym tekstem.
- Niepełne źródło nie jest poprawnie ocenioną sceną negatywną.

## 6. Gotowość F4

Istnieje solidna podstawa do retrospektywnego porównania wariantów. Zweryfikowano wspólne checkpointy MT i MZ we wszystkich dwunastu archiwach oraz jedno SHA APK.

| Dowód | Wartość |
|---|---|
| Checkpoint MT | `25636b5d97d9562f7381b719fbb5ec63ecd7630e16d31a824438171d889978cf` |
| Checkpoint MZ | `631bb1453554cdb6b15eca724baa392e2acffb350899107f892dc11f937dbbf8` |
| APK | `4a78a026cebb0bf18b8b579a75b332c8953f0071a18d3ee1af391a25d9bb1944` |

Manifesty przypisują wariantom INT8 dowody statycznego grafu `INT8/full_integer_graph=true`. Jednocześnie zapisują `execution_precision=UNVERIFIED`; telemetria określa swój zakres jako `RUNTIME_OBSERVATIONS_NOT_KERNEL_PROOF`.

**Klasyfikacja statycznego grafu i dowód arytmetyki rzeczywiście wykonanych kerneli nie są równoważne.** Nie należy nazywać obu poziomów dowodu jednym potwierdzeniem „pełnego wykonania INT8”.

F4 można opracować bez powtarzania pomiarów, z zachowaniem następujących ograniczeń:

- jakość pochodzi z ocen ASSISTED i kwalifikowanych jednostek;
- wspólny scenariusz nie dowodzi identyczności każdej klatki;
- pomiar etapu MZ w śladzie nie musi być pomiarem pojedynczego wywołania;
- maksimum dostępnych próbek PSS nie oznacza ciągłego pomiaru szczytu pamięci;
- median i percentyli sesji nie wolno przedstawiać jako percentyli wspólnej populacji bez ponownego obliczenia z odpowiednich próbek;
- DAY/NIGHT należy rozdzielać według potwierdzonego materiału/scenariusza, nie zgadywać z samej nazwy wariantu lub profilu modelu;
- powtórzenia tej samej planszy nie są niezależnymi fotografiami.

Wynik F4 należy przedstawiać jako retrospektywne porównanie w udokumentowanym zakresie, z licznością zakwalifikowanych jednostek, odrzuceń i N/A. Zatwierdzone eksporty pozostają wartościowymi wynikami, ale nie stają się przez to niezależnym F6.

## 7. Gotowość F5A

### 7.1. Rozdzielenie błędów MP/ROI, MT i MZ

Należy rozdzielić trzy kategorie:

1. Tablica poza wybranymi ROI — **brak pokrycia wejścia MT**.
2. Tablica w kwalifikowanym ROI, bez prawidłowej detekcji FINAL — problem detekcji MT.
3. Prawidłowo przypisana detekcja i niepoprawny odczyt — problem odczytu MZ.

Pierwsza kategoria nie jest automatycznie błędem samego detektora pojazdów MP. Może wynikać z polityki wyboru jednego/dwóch ROI. **Pełna ocena precision/recall pojazdów MP wymagałaby referencji pojazdów**, której obecny model GT tablic nie zastępuje.

Do celu F5A można wykorzystać ocenę pokrycia tablic przez wybrane ROI, jasno nazywając tę miarę. `coverage()` rozróżnia m.in. `COVERED`, `OUTSIDE_ROI`, `PARTIAL_ROI` i brak udowodnionego pokrycia. Wymaga właściwego związku geometrii GT i obserwacji MP z konkretną klatką.

### 7.2. Ograniczenie wielokrotnego anotowania

Rekomendacja: przygotować GT **40 fotografii raz**, a następnie powiązać je z obserwacjami.

Plan daje dziewięć ekspozycji każdej fotografii: trzy warianty razy trzy powtórzenia — nie 36 ekspozycji każdej fotografii. Obecne 386 zdarzeń wymaga jednak rzeczywistego mapowania.

Tekst i identyfikator tablicy można współdzielić dopiero po potwierdzeniu tożsamości fotografii. Geometrii nie wolno kopiować bezpośrednio:

- `TV_BBOX_CROP` opisuje wycięcie i przesunięcie;
- nie opisuje transformacji oryginalnej fotografii na sfotografowaną powierzchnię TV;
- trzeba uwzględnić perspektywę, sposób wyświetlenia i ewentualne marginesy;
- transformacja musi mieć zweryfikowany zakres ważności i być powiązana z właściwą geometrią źródłową;
- blok obserwacji nie stanowi dowodu niezmienności geometrii wszystkich jego klatek.

Istniejąca kalibracja TV jest przydatnym wejściem do takiego mechanizmu, ale sama deklaracja `H_TV=NOT_APPLIED` nie oznacza rozwiązanej transformacji fotografii do CameraX.

### 7.3. Sceny bez MT i niepełne dowody

Blok z zerem MT musi pozostać w populacji obserwacji. Nie oznacza automatycznie braku tablic. Operator musi móc ocenić pełną scenę, w tym tablice pominięte przed etapem MT.

Anulowane wywołania oraz nieustalone role pozostają zachowane. Nie wolno przekształcać nieustalonego rekordu w FINAL, ani przenosić wyniku do następnej sceny na podstawie czasu zakończenia inferencji.

Obecny scorer potrafi traktować duplikaty FINAL w ramach jednostki oceny. Nie zastępuje to rozpoznania jednej fizycznej tablicy między kolejnymi klatkami i wywołaniami.

### 7.4. Brakująca ścieżka E2E

Aktualna ścieżka nie jest jeszcze kompletna:

```text
40 fotografii o znanych SHA
→ 36 potwierdzonych sesji
→ 386 udokumentowanych zdarzeń scen
→ pełne klatki CameraX i odrębne wejścia MT
→ ROI oraz wyniki MT/MZ
→ brak kompletnego, niezależnego GT i mapowania fotografii do obserwacji
→ SCENE_UNMAPPED dla pełnego E2E
```

Potrzebne są: jednostka obserwacji, reguła okna, reguła wyboru wyniku, referencyjna tożsamość fizycznej tablicy, pełna populacja pozytywów/negatywów i jawne wyłączenia. Dopiero wtedy można wyprowadzić porównywalny wynik E2E R0/R1/R2.

Nie należy w tym celu przepisywać historycznej polityki dopasowania F4. Nowa agregacja obserwacji powinna być wersjonowana i korzystać z istniejących poprawnych składników oceny.

## 8. Gotowość F5B i odmienność obserwacji dynamicznych

### 8.1. Dane już zapisywane przez Androida

W bieżącym lokalnym kodzie istnieją m.in.:

- `auto_zoom_started`, zdarzenia powrotu i ponownego MZ;
- `track_id` i `elapsed_ms` w zdarzeniach;
- `capture_source` oraz `camera_zoom_ratio`;
- identyfikatory prób, encji, tracków, generacji i stampy;
- techniczne miary czasu pierwszego wyniku.

Główne miejsca w Androidzie, względem `app/src/main/java/com/example/alpr_v1`:

| Plik | Znaczenie |
|---|---|
| `MainActivity.java` | Sterowanie AutoZoom i emisja zdarzeń rozpoczęcia, ponowienia oraz powrotu. |
| `metrics/MetricsCollector.java` | `recordEvent()`, czas sesji, `recognition_latency`, telemetria i eksport pól śladów. |
| `experiment/ResearchSessionStore.java` | Trwały zapis prób i metadanych, w tym `attempt_started_elapsed_nanos`, źródła i współczynnika zoomu. |
| `experiment/ResearchSampleIdentity.java` | Budowa `subject_key` z sesji, generacji, encji/tracku albo próby. |

Obecność tych pól nie jest jeszcze kompletnym kontraktem obserwacji dynamicznej. Nie potwierdzono go na wykonanej kohorcie F5B.

### 8.2. Dwie istotne pułapki czasowe

1. Androidowe `time_to_first_confirmed_ms` oznacza wewnętrzne potwierdzenie wyniku, **nie zgodność z niezależnym GT**.
2. Desktopowe `time_to_first_exact_ms` w `calculate_review_statistics()` liczy różnicę **czasów rozpoczęcia prób**, względem pierwszej ocenialnej próby podmiotu. Nie jest to czas dostępności poprawnego wyniku od początku okna obserwacji.

Nie należy prezentować pomocniczych istniejących miar pod nową nazwą sugerującą silniejszy kontrakt.

### 8.3. Tożsamość tablicy w czasie

`subject_key` wykorzystuje generację sceny oraz identyfikator encji/tracku. Jest dobrym identyfikatorem technicznym, ale nie samodzielnym dowodem ciągłości fizycznej tablicy po zmianie tracku lub zoomu.

Przed F5B trzeba ustalić:

- początek i koniec obserwacji fizycznej tablicy;
- relację kolejnych klatek i prób do tej obserwacji;
- rzeczywiste źródło rozmiaru tablicy przed AutoZoom;
- powiązanie żądania i zastosowania zoomu z właściwą klatką;
- czas dostępności pierwszego wyniku oraz pierwszego wyniku zgodnego z GT;
- regułę wyniku w ustalonym oknie;
- liczbę interwencji i wywołań, także przy braku poprawy lub pogorszeniu;
- zasady porównania OFF/ON.

Należy wykorzystać istniejące zapisy i uzupełnić tylko brakujące dowody przed planowanym eksperymentem. Statycznego grupowania po zdarzeniach nie należy automatycznie stosować do F5B.

## 9. Gotowość F6 i raportowanie F7

### 9.1. Niezależny final_test

Nie potwierdzono istnienia niezależnego final_test na podstawie sprawdzonych manifestów i danych. Sprawdzony katalog `E-FINAL-ALPR-01` jest pusty, a istniejące źródła zawierają statusy `NOT_VERIFIED` dotyczące final_test.

Potrzebne są:

- identyfikacja i zatwierdzenie kohorty;
- kontrola rozłączności wobec treningu, walidacji, kalibracji oraz materiału użytego do wyboru konfiguracji;
- uwzględnienie wszystkich modeli i rodziców modeli;
- niezależne GT i jego wersja;
- ocena wszystkich kwalifikowanych scen;
- ustalone przed oceną reguły wyłączeń i braków danych.

Nie wolno ogłosić final_test tylko dlatego, że aplikacja ma pole o takiej nazwie albo eksport został zatwierdzony.

### 9.2. Zamrożenie konfiguracji

Można wykorzystać istniejące manifesty modeli, SHA artefaktów i APK, konfiguracje wykonania oraz mechanizmy eksportu. Dla F6 potrzebny jest jednak konkretny, zatwierdzony pakiet końcowy obejmujący modele, APK i wszystkie ustawienia istotne dla wyniku.

Po obejrzeniu final_test nie należy dobierać zwycięskiej konfiguracji na podstawie tego samego zbioru. Raport F6 musi być odrębny metodologicznie od porównywania wariantów F4/F5A/F5B, ale może korzystać z tych samych mechanizmów danych, Canvas i obliczeń.

### 9.3. F7 — wyniki do pracy

Eksport CSV/JSON, raporty, wykresy i manifesty już istnieją i mają rzeczywiste zastosowanie w F4. Należy je zachować.

Materiały do pracy powinny ujawniać:

- jednostkę obserwacji i mianownik każdej miary;
- liczbę jednostek zakwalifikowanych, nieocenionych, wyłączonych oraz N/A;
- pochodzenie GT: ASSISTED albo potwierdzony kontrakt niezależny;
- wersję GT i rewizję oceny;
- SHA źródła, modeli i APK;
- politykę dopasowania/agregacji;
- ograniczenia porównywalności i zależność powtórzeń.

Eksport nie powinien ukrywać braków pod zerami ani usuwać niekompletnych przypadków z opisu populacji.

## 10. Minimalna ścieżka ukończenia pracy

### A. Konieczne do zakończenia aktualnego F5A

| Działanie | Dlaczego i czy blokuje ocenę naukową | Minimalny zakres | Reużycie i ryzyko |
|---|---|---|---|
| **A1. Referencja GT** | Blokuje twierdzenie o niezależnej jakości. | Etap referencji bez predykcji, kompletność tekst/geometria/N/A, wersja i pochodzenie GT. Zachować istniejące NO_PLATES. | Ten sam Canvas, historia, decyzje i istniejący GT Pack/sidecar. Ryzyko średnie: nie migrować ani nie przemianowywać ASSISTED. |
| **A2. Mapa fotografii i obserwacji** | Blokuje mianownik fotografii i porównanie tych samych obiektów. | Powiązanie SHA fotografii z rzeczywistym zdarzeniem i klatką; jawna obsługa dodatkowych zdarzeń i przejść. | Manifest TV, obecna lista bloków, źródła SHA. Ryzyko wysokie przy automatycznym dopasowaniu po kolejności. |
| **A3. Transport geometrii** | Blokuje współdzielenie polygonów i ocenę pokrycia na innych klatkach. | Zweryfikowana transformacja wraz z zakresem ważności, kontrolą geometrii i możliwością korekty. Nierozstrzygalne przypadki N/A. | Kalibracja TV, adapter cropu, `source_binding`, istniejące narzędzia edycji. Nie zmieniać dotychczasowych współrzędnych źródłowych. |
| **A4. Wynik obserwacji** | Blokuje pełne E2E R0/R1/R2. | Reguła okna i wyboru wyniku, jedna fizyczna tablica na obserwację, negatywy, no-read, błędy oraz kompletność dowodów. | Istniejące scorery jako składniki; osobna wersja agregacji, bez przepisywania wyników F4. Ryzyko wysokie dla mianowników. |
| **A5. Porównanie i eksport** | Potrzebne do wniosków o wariantach. | Zamrożona lista 36 źródeł, mapowanie DAY/NIGHT, jawne liczności i reguły agregacji powtórzeń. | Obecny analizator i eksporter. Ryzyko umiarkowane, jeśli zachowane zostaną stare protokoły. |

### B. Konieczne dopiero do F5B

| Działanie | Dlaczego i czy blokuje ocenę naukową | Minimalny zakres | Reużycie i ryzyko |
|---|---|---|---|
| **B1. Kontrakt czasowy** | Blokuje rzetelny czas pierwszego poprawnego wyniku. | Przed planowanym F5B określić obserwację, początek/koniec okna, powiązanie zdarzeń AZ, źródło rozmiaru tablicy przed zoomem i czas dostępności wyniku. Uzupełnić tylko brakujące pola istniejącego zapisu Androida. | `ResearchSessionStore`, `MetricsCollector`, bieżące ślady i zdarzenia. Ryzyko: mieszanie domen czasu i generacji. |
| **B2. Sekwencja i OFF/ON** | Blokuje kontrolowane porównanie dynamiczne. | Nawigacja kolejnych źródeł w tym samym Canvas, potwierdzenie ciągłości tablicy, klasyfikacja kohorty i agregacja OFF/ON. | Istniejące indeksy prób, timeline, GT i analizator. Nie używać statycznych bloków jako zastępstwa. |

### C. Konieczne do niezależnego F6

| Działanie | Dlaczego i czy blokuje ocenę naukową | Minimalny zakres | Reużycie i ryzyko |
|---|---|---|---|
| **C1. Niezależna kohorta** | Bezwzględnie blokuje deklarację final_test. | Manifest zbioru i kontrola rozłączności wobec treningu, walidacji, kalibracji oraz materiału użytego do wyboru konfiguracji, dla wszystkich modeli i rodziców. | Istniejące inwentarze SHA i kontrole kalibracji. Sam katalog lub nazwa zbioru nie wystarcza. |
| **C2. Zamrożenie i raport** | Blokuje odtwarzalność końcowego wyniku. | Zamrozić modele, APK, ustawienia i reguły oceny; wersję GT; populację i wyłączenia. Dodać raport F6 nad wspólnymi mechanizmami. | Manifesty, sidecary, scorery, eksport C8. Bez drugiego edytora i bez rankingu wariantów po obejrzeniu final_test. |

### D. Opcjonalne usprawnienia UX lub diagnostyki

Czytelniejsze podpisy, wyszukiwanie, filtry N/A i wygodniejsze przejścia można realizować w istniejących oknach. Nie blokują poprawności metryk, jeśli dane są jednoznaczne, i nie zastępują działań A–C.

Rekomendacje nie obejmują refaktoryzacji całej aplikacji, nowych eksperymentów ani powtarzania zakończonych pomiarów. Nie proponuje się ponownego zatwierdzania decyzji zapisanych jednoznacznie na Canvas.

## 11. Zagrożenia dla poprawności naukowej

1. Uznanie 386 zdarzeń za 386 niezależnych fotografii albo wymuszenie mapowania do 360 pozycji po numerze.
2. Przenoszenie geometrii między różnymi stampami, ponieważ należą do jednego bloku.
3. Nazwanie dotychczasowego ASSISTED niezależnym GT.
4. Potraktowanie `COMPLETED` jako dowodu pełnego mianownika wszystkich metryk.
5. Zliczanie tej samej tablicy wielokrotnie przez kolejne wywołania MT, ROI lub tracki.
6. Pominięcie scen bez MT, co sztucznie poprawiłoby jakość wariantu.
7. Uznanie `NOT_RUN`, anulowania lub braku dowodu za zwykły negatyw albo zero.
8. Uznanie potwierdzenia algorytmicznego za pierwszy poprawny wynik względem GT.
9. Łączenie powtórzeń i różnych podzbiorów jakości bez ujawnienia ich zależności i liczności.
10. Uznanie zgodności SHA plików materiału za pełne potwierdzenie jego niezależności od wszystkich modeli i ich rodziców.
11. Uznanie statycznego dowodu INT8 za dowód precyzji wszystkich wykonanych kerneli na urządzeniu.
12. Traktowanie samej dostępności funkcji w GUI jako potwierdzenia jej pełnego kontraktu naukowego.

## 12. Testy, ograniczenia walidacji i bezpieczeństwo

### 12.1. Istniejące wyniki testów

W czasie audytu nie uruchamiano testów zapisujących ani aplikacji. Odczytano istniejące raporty JUnit z ostatniego zadania:

| Zestaw | Wynik |
|---|---|
| Bloki obserwacji | **31/31 PASS** |
| Pełne sceny Tk | **13/13 PASS** |
| Postęp operatora | **21/21 PASS** |
| Importer folderów UX02 | **71/71 PASS** |
| Preferencje importera | **20/20 PASS** |
| Rdzeń ocen i raportów | **230 PASS, 5 FAIL** |

Raporty odczytano z:

```text
C:\Users\48572\AppData\Local\Temp\z4_observation_blocks_wsd05h0k
```

W szczególności: `focused_verified.xml`, `scene_tk.xml`, `progress.xml`, `import_folder.xml`, `import_preferences.xml` oraz `core.xml`.

Szersze regresje pozostają częściowo niezaliczone, zgodnie z [raportem wdrożenia bloków obserwacji](Z4_BLOKI_OBSERWACJI_ODBIOR_2026-11-10.md). Nie zamieniono historycznych testów ani obecności kodu w odbiór operatora. Sprawdzono również, że pliki objęte ostatnim raportem zmian nadal miały te same SHA w chwili audytu.

### 12.2. Ograniczenia odbioru

- Nie przeprowadzono nowego odbioru wizualnego GUI.
- Nie wykonano nowych pomiarów urządzeniowych.
- Nie uznano testów syntetycznych za dowód gotowości całej rzeczywistej kohorty.
- Nie potwierdzono niezależnego final_test.
- Odczyt lokalnego kodu Androida nie dowodzi, że każda jego aktualna funkcja została wykonana w starszych archiwach.
- Rzeczywiste archiwa i ich metadane wykonania mają pierwszeństwo przed wnioskowaniem z bieżącego kodu, nazw katalogów lub nazw wariantów.

### 12.3. Kontrola niezmienności podczas audytu

Kontrola przed i po audycie objęła **1916 plików**:

| Grupa | Liczba plików |
|---|---:|
| Kod Desktop | 491 |
| Testy | 550 |
| Dokumentacja | 66 |
| Źródła Androida | 762 |
| Chronione dane | 47 |
| **Łącznie** | **1916** |

Zbiorcze kontrole SHA, rozmiarów i czasów modyfikacji nie wykazały zmian podczas opisanego audytu. Nie wykonano importu, pomiarów, uruchomienia modeli ani operacji Git zmieniających pracę.

Utworzenie niniejszego dokumentu jest późniejszym, osobno zleconym zapisem raportu. Nie zmienia ustaleń audytu i nie obejmuje zmian kodu ani danych produkcyjnych.

## 13. Konkretna kolejność dalszych prac

1. **Uzgodnić jednostkę wyniku i kontrakt GT/E2E aktualnego F5A.** Ustalić populację, okna, negatywy, N/A, regułę wyniku i rozdzielenie ocen ASSISTED od niezależnych.
2. **Domknąć kontrolę materiału oraz mapowanie 40 fotografii na 386 zdarzeń i właściwe klatki.** Nie przypisywać fotografii według samego numeru bloku.
3. **Ukończyć referencję GT i zweryfikować transport geometrii**, zachowując istniejące decyzje, identyfikatory, źródła i historię.
4. **Dodać agregację obserwacji i zakończyć ocenę oraz eksport F5A.** Niewykazywalne miary pozostawić N/A; nie przepisywać historycznych wyników F4.
5. **Przed planowanym F5B domknąć jego kontrakt dynamiczny** i brakujące dowody czasowe. Wykorzystać istniejący Canvas oraz zapis prób i zdarzeń.
6. **Po wyborze konfiguracji zamrozić ją, zatwierdzić niezależną kohortę F6 i dopiero wtedy przeprowadzić ocenę końcową.** Nie dobierać konfiguracji na podstawie final_test.
7. **Opracować F7 z eksportów** zawierających mianowniki, wyłączenia, wersje GT, konfiguracje i ograniczenia każdego eksperymentu.

## 14. Dokumenty powiązane

- [Audyt K02 i dowodów stabilności](Z4_K02_AUDYT_BLOKOW_STABILNEJ_SCENY_2026-11-10.md) — wcześniejszy audyt źródeł; brak dowodów stabilności nie został rozwiązany przez grupowanie nawigacyjne.
- [Wdrożenie bloków obserwacji i odbiór K02](Z4_BLOKI_OBSERWACJI_ODBIOR_2026-11-10.md) — zakres implementacji, testy i instrukcja odbioru operatora.
- [Importer UX02](F5A_IMPORTER_UX02_ODBIOR_2026-11-09.md) — istniejący tor importu.
- [Postęp operatora F5A](F5A_OPERATOR_PROGRESS_ODBIOR_2026-11-09.md) — rozdzielenie zapisanych decyzji człowieka od technicznej dostępności/N/A.
- [Polityka F4-EVAL-2.0](experiments/F4_EVAL_2_0_OPERATOR_ASSISTED_OBJECT_20261101.md) — zakres retrospektywnej oceny ASSISTED.
- [Kompletność operacyjna F4](experiments/F4_FRAME_COMPLETION_ELIGIBILITY_20261102.md) — odrębność kompletności decyzji od niezależnej, wyczerpującej referencji sceny.

Dokumenty powiązane są źródłami uzupełniającymi. Niniejszy plik zawiera samodzielny raport audytu, macierz gotowości, kontrakt pracy operatora i rekomendowaną kolejność działań.
