# F5A / A3 — weryfikacja serii wspomagana gotowym GT

Data: 2026-11-11. Repozytorium: `C:\Users\48572\Desktop\dyplom\start4`.

## Aktualny widok operatora — korekta UX

Nagłówek: **R1 · Powtórzenie 2 · Blok B**. Pod nim tylko **Zdjęcia: X/10** oraz **MT: Y/44**, a następnie **Poprzednie / Dalej**. Sesję wybiera się w istniejącej przeglądarce raportów.

```text
Zdjęcie 1 · GT 11
  MT 1 · 1 wskazanie
  MT 2 · 1 wskazanie
  Klatki telefonu (3)       [domyślnie zwinięte]
Zdjęcie 2 · GT 12
  …
```

- **Wskazanie MT:** Trafne / Błędne / Nie można ocenić. Przy jednej tablicy GT nie ma zbędnego wyboru. Przy kilku wybiera się tablicę. Jeśli ma już trafne wskazanie w tym MT, pojawia się jawne pytanie o duplikat.
- **MT:** osobno zachowane są brak wskazań, pominięcie tablicy, pokrycie ROI i N/A. Są dostępne kontekstowo, bez stałego zestawu formularzy.
- **Zdjęcie:** Zgadza się / Popraw / Nie można ustalić. Ocena zdjęcia nie ocenia MT.
- **Blok:** zbiorcze potwierdzenie zdjęć pozostaje dostępne po ich obejrzeniu, wyłącznie dla jeszcze nierozstrzygniętych zdjęć. Nie zatwierdza MT.
- **Sesja:** kończy ją osobny przycisk „Zatwierdź sesję A3”, dostępny po spełnieniu dotychczasowego kontraktu kompletności.

X liczy zdjęcia, których wszystkie źródłowe klatki mają jawną decyzję o zdjęciu; Y liczy MT kompletne według niezmienionego `unit_state`. Jawne N/A jest decyzją, samo obejrzenie nie jest oceną. Poprzednie/Dalej pozostają na wybranym poziomie: zdjęć, MT albo klatek telefonu; nie zapisują ocen. Zapisana decyzja nie wymaga ponownego potwierdzenia.

Canvas zajmuje największą część okna. Lewy panel ma krótkie nazwy, prawy wykorzystuje istniejący obszar oceny. Szczegóły są zwinięte. Nie dodano panelu, modułu ani Canvas. Bieżąca korekta zmienia tylko trzy pliki GUI, istniejący plik testów i ten dokument; backend, A2, GT, historia oraz eksport pozostają bez zmian. Dalsze sekcje opisują zachowany kontrakt pierwszego wdrożenia.

**Weryfikacja tej korekty UX:** A3 **24 PASS / 0 FAIL / 0 SKIP**, regresje Z4/A1 **86 PASS / 0 FAIL / 1 SKIP**. Po końcowej korekcie prezentacji ponownie uruchomiono wszystkie 6 testów natywnego Tk A3: **6 PASS** (18 testów backendowych wyłączonych z tego powtórzenia). Jedyny SKIP dotyczy niepodłączonej opcjonalnej kopii referencji A1. Testy obejmują zapis, wznowienie, eksport, brak zapisu podczas nawigacji, trzy decyzje MT, brak zbędnego wyboru przy jednej tablicy, zachowanie 44 MT i wszystkich źródłowych klatek, liczniki oraz układ 1180×760 i 1649×896.

Aktualne zmiany aplikacji: `gui/mobile_f5a_assisted.py` — prezentacja A3; `gui/mobile_canvas_editor.py` — Spacja przekazana do bieżącej akcji A3; `gui/mobile_canvas_info_badge.py` — prosty opis wyniku i pominięcie nieużywanego HUD technicznego wyłącznie w A3. Zwykły Z4 i A1 zachowują swoje ścieżki. **1920/1920 chronionych plików bez zmian SHA/rozmiaru/mtime; żaden plik backendu nie zmienił SHA.** Dowody: `C:\Users\48572\AppData\Local\Temp\f5a_a3_simple_ux_36waty3b` (`a3_final`, `regression`, `native_final`, `integrity_final.json`, podglądy PNG). Testy wykonywano na prywatnych kopiach. Odbiór operatora nadal **NOT_VERIFIED**.

## Wynik i zakres

Dodano adapter A3 do istniejącego okna **Raporty z telefonu → Weryfikacja próbek**. Wykorzystuje jego rzeczywisty Canvas, ładowanie obrazów, wybór rekordów, powiększanie, PPM, sidecar i eksport. Kanoniczna fotografia z GT jest osobnym, tylko do odczytu podglądem `Label`; nie powstał drugi Canvas ani edytor GT.

**Odbiór GUI operatora: NOT_VERIFIED.** Testy natywnego Tk na prywatnych danych nie zastępują odbioru operatora. Nie wykonano żadnej produkcyjnej oceny A3.

A1 pozostaje odebrane. A2 pozostaje źródłem propozycji, które operator może potwierdzić, poprawić, odrzucić albo wyłączyć z powodem. Nie wykonano homografii JPEG → CameraX ani nowych pomiarów. F5B pomijamy; F6 nie rozpoczęto.

## 1. Krótki audyt istniejącego weryfikatora

| Obszar | Istniejący kod i kontrakt | Wykorzystanie w A3 |
|---|---|---|
| Archiwum i źródła | `ranking/mobile_package_experiments.py`, `MobileReportBundle`; `ranking/mobile_human_review.py`, `MobileReviewSession` | Ten sam odczyt archiwum, identyfikatory sesji, wywołań, wyników, SHA i pola źródłowe. |
| Obserwacje i nawigacja | `gui/mobile_canvas_observation_blocks.py`: `build_blocks`, `render`, `select`, `open_gid`; `gui/z4_mobile_sample_review.py`: `_multi_focus_attempt`, `_select_record`, `_load_image` | Istniejące rekordy i otwieranie CameraX. Adapter zmienia organizację tego samego drzewa na ekspozycje A2 i rzeczywiste wywołania; zwykłe grupowanie pozostaje dostępne poza A3. |
| Canvas, MP/MT/MZ i ROI | `gui/mobile_canvas_editor.py`; `gui/mobile_canvas_clean_view.py`; `ranking/mobile_canvas_review.py`: `context`, `_prediction`; `ranking/mobile_source_frame_roi.py` | Istniejący obraz i warstwy źródłowe. Nakładka MP pochodzi wyłącznie z zapisanego ROI o zgodnym `source_stamp`. |
| Pełna scena i decyzje | `ranking/mobile_scene_frame_review.py`: `scene`, `confirm_empty`, `decide_mt`, `coverage`, `restore`; `ranking/mobile_verification_policy.py`: `visual_decision`, `verification_issues` | Zachowano rozróżnienie świadomej sceny negatywnej, oceny operacyjnej oraz geometrycznej. A3 używa istniejących znaczeń pokrycia ROI, ale nie tworzy zastępczych obrysów CameraX. |
| Tekst i CER | `ranking/mobile_canvas_review.py::_prediction`; `ranking/mobile_object_mz_quality.py::score_readout`; `ranking/mobile_human_review.py::align_plate_text` | Te same źródłowe odczyty i funkcja oceny tekstu, z dodatkowymi warunkami kwalifikacji wynikającymi z kanonicznego GT i jawnego powiązania A3. |
| Zapis, historia, wznowienie | `MobileReviewSession._save_change`, `_save_change_locked`, `_atomic_write` | Ten sam sidecar, blokada zapisu, rewizja i atomowa wymiana. Historia A3 jest wersjonowaną częścią tego sidecara; stare historie pozostają zachowane. |
| Eksport | `MobileReviewSession.export` | Istniejący eksport otrzymuje trzy dodatkowe pliki A3. Dotychczasowe eksporty i algorytmy metryk nie zostały zastąpione. |

**Rzeczywiście brakowało:** przypięcia całej serii do A2 i zamrożonego GT; oddzielnej akceptacji/korekty tożsamości fotografii; rozróżnienia ekspozycji od jej wielu klatek/wywołań; przypisania rzeczywistej detekcji do gotowego obiektu fotograficznego GT; zapisu i eksportu tej relacji bez fikcyjnego obrysu telefonu; bezpiecznej akceptacji obejrzanego bloku oraz jawnie wybranych wywołań; osobnego statusu kompletności A3.

## 2. Rzeczywiste wejścia i kontrola SHA

Użyto istniejącego katalogu, bez ponownego tworzenia mapowania:

```text
C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\03_wyniki\A2_mapowanie_GT_20261111T030449Z
```

| Wejście | SHA-256 |
|---|---|
| `mapping.json` | `49c7d0956d687f5caed62dfef5bcf31652b8d6b5843e31b984a0e2237e4b0848` |
| Zamrożona referencja i produkcyjny `reference_v1.json` | `e7af93284b427925fa072e5f5315a4caecb5c90bb4095038d72fddaf6c1c7e82` |
| `sorting_manifest.json` | `fb4cc7dae80b046ce362e0b2817bfbdc0acd0b2129357d7cbaec32a0a0de09fb` |
| `manifest_blokow.json` | `3262ea004f83cc06698a2f0185710d36ac72c8448a194a8accfeffb21893740d` |

Loader sprawdza manifest artefaktów A2, hashe mapowania, inwentarza, dowodów źródłowych, zamrożonego GT, obu manifestów materiału i 40 fotografii. Sprawdza kompletność GT 40/40 oraz siatkę 36 sesji. Przy otwarciu sesji wymaga zgodności `session_id`, SHA całego archiwum, identyfikatorów wywołań i źródłowych stempli klatek. Nie przelicza domen czasu.

Zachowane mianowniki A2: **36 sesji, 360 ekspozycji, 386 zdarzeń scen, 1656 wpisów klatek i 1281 wywołań MT**. Dwie reprezentacje tego samego obrazu SCENE_FRAME/TV_INPUT mogą być pokazane jako jedna klatka wyłącznie przy identycznych: sesji, SHA obrazu i pełnym stemplu źródłowym. Ich identyfikatory w A2 pozostają zachowane. Osiem zdarzeń mieszanych nie jest sprowadzanych do jednej fotografii. Materiał samolotów spoza GT pozostaje w gałęzi dodatkowej, z możliwością jawnego N/A.

Jednorazowe połączenie zapisuje tylko ścieżki i hashe w `Workspace\7_rankings\mobile_packages\f5a_reference_bindings.json`. Nie jest to magazyn ocen ani kopia GT. Produkcyjnego połączenia nie utworzono podczas testów.

## 3. Reprezentacja decyzji i trwałość

Oceny zapisują się w istniejącym `human_reviews/<SHA_archiwum>.review.json`, wewnątrz:

```text
provenance.f5a_assisted_gt_v1
  schema = alpr.mobile.f5a_assisted_gt.v1
  binding = ścieżki i SHA A2 / zamrożonego GT
  state:
    identities    — decyzje o ekspozycji lub dokładnej klatce
    coverage      — pokrycie tablicy przez rzeczywisty ROI wywołania
    detections    — decyzje o źródłowych attempt_id
    missing       — jawne FN, osobno dla wywołania i obiektu GT
    units         — jawne N/A albo obejrzany pusty wynik NO_PLATES
    blocks        — potwierdzenie obejrzanego bloku / zatwierdzenie A3
  versions / timeline / cursor — historia zmian i undo/redo
  resume — ostatni kontekst zapisanej decyzji
```

| Rozstrzygnięcie | Wartości i zasady |
|---|---|
| Tożsamość | Brak decyzji daje tylko `PROPOSED`. Operator zapisuje `CONFIRMED`, `CORRECTED`, `REJECTED` albo `N/A`. Odrzucenie i N/A wymagają powodu. Korekta konkretnej klatki ma pierwszeństwo przed decyzją całej ekspozycji. |
| Pokrycie ROI | `COVERED`, `OUTSIDE_ROI`, `PARTIAL_ROI`, `ROI_COVERAGE_UNPROVEN`. Ostatni status wymaga powodu; zapis zawiera rzeczywisty ROI źródłowy. |
| Wynik MT | `TP`, `FP`, `DUPLICATE`, `N/A`. TP wskazuje istniejący `object_id` zamrożonego GT. Drugi TP tego samego obiektu w jednym wywołaniu jest blokowany; duplikat wymaga wskazanego TP. |
| Pominięcie | `FN` wymaga poprawnie wykonanego MT, potwierdzonego pokrycia ROI i braku TP danej tablicy w tym wywołaniu. Pominięcie przez ROI nie staje się automatycznie FN lokalizatora MT. |
| Wywołanie | `EMPTY_REVIEWED` wymaga rzeczywiście pustego wyniku dla potwierdzonej fotografii NO_PLATES. Anulowane/niewykonane/błędne MT wymaga jawnego N/A, nie zera. |
| OCR | Pełny, wiarygodny tekst GT + TP + udowodniony FINAL + wykonane MZ + zgodny źródłowy crop + jednoznaczny odczyt. Fragment GT, nieczytelność, wieloznaczność albo jawne wyłączenie operatora dają N/A. |

Decyzje zawierają identyfikator decyzji, pochodzenie `OPERATOR_EXPLICIT`, operatora, czas i identyfikatory dowodów. Warstwa wskazuje `ASSISTED_CANONICAL_PHOTO_GT`. Automatyczna propozycja zachowuje odrębne pochodzenie `A2_AUTOMATIC_EVIDENCE`. Poprzedni tryb/status/rewizja nagłówka są zachowane w `legacy_review_header`. Gotowych ocen A3 nie można przemianować na ocenę zaślepioną.

Zmiana fotografii unieważnia zastosowanie zależnych ocen ROI/MT/MZ, zachowując je w historii. Spacja nie zastępuje już zapisanej korekty ponowną propozycją A2. Zapis jest natychmiastowy po jawnej decyzji; samo oglądanie i nawigacja nie zapisują ocen. Undo/redo A3 działa w tej samej warstwie, bez cofania starszej historii weryfikatora.

Nowa decyzja o wyniku lub pokryciu cofa wcześniejsze wyłączenie całego wywołania N/A, zachowując je w historii. Sprzeczne decyzje TP i OUTSIDE_ROI blokują ukończenie tego wywołania do czasu rozstrzygnięcia.

Potwierdzenie bloku oznacza wyłącznie tożsamość 10 obejrzanych ekspozycji. Nie nadpisuje wcześniejszych decyzji. Seryjne TP dotyczy wyłącznie jawnie zaznaczonych wywołań tej samej tablicy z dokładnie jednym udowodnionym FINAL w każdym wywołaniu; identyfikatory i decyzje każdego wywołania pozostają osobne.

**Status A3 jest oddzielny od starego statusu raportu.** `operator_complete` nie oznacza `operator_approved`. Zatwierdzenie A3 wymaga osobnej świadomej akcji po rozstrzygnięciu wszystkich powiązań i wywołań. Nowa decyzja unieważnia wcześniejsze zatwierdzenie. Legacy `review_status` pozostaje `IN_PROGRESS`; nie wymuszono zgodności starej metryki geometrycznej z operacyjnym A3.

Eksport dodaje `f5a_a3_operator_review.json`, `f5a_a3_operational_results.csv` i `f5a_a3_roi_and_missing.csv`. JSON zawiera warstwę wraz z historią, powiązaniem i stanem każdego wywołania; CSV rozdzielają wyniki detekcji/OCR od pokrycia/FN oraz zawierają sesję, SHA źródeł, rewizję i status kompletności wywołania. Źródłowy raport i dotychczasowe pliki eksportu zostają zachowane. Częściowy eksport służy kontroli postępu, nie jest automatycznie zatwierdzonym wynikiem naukowym.

## 4. Zmienione pliki

| Plik | Zmiana |
|---|---|
| `auto_annotation_tool/ranking/mobile_f5a_assisted.py` — nowy | `Reference`, wykrywanie i przypięcie A2, jawne decyzje A3, walidacja, historia, odtworzenie i dodatek eksportowy. |
| `auto_annotation_tool/gui/mobile_f5a_assisted.py` — nowy | `AssistedReview`: pasek serii, adaptacja istniejącego drzewa, podgląd GT, PPM, decyzje i powrót do kontekstu. |
| `auto_annotation_tool/ranking/mobile_human_review.py` | Walidacja dodatkowej warstwy, jawnie asystowany widok i dołączenie eksportu A3. |
| `auto_annotation_tool/gui/mobile_canvas_editor.py` | Warunkowe przekazanie nawigacji, PPM, Spacji, historii i informacji do A3; ochrona gotowego GT przed przypadkową edycją legacy w tym trybie. Zwykłe ścieżki i A1 zachowane. |
| `auto_annotation_tool/gui/z4_mobile_sample_review.py` | Instalacja adaptera wyłącznie dla F5A oraz wywołanie go po wczytaniu i namalowaniu źródła. |
| `tests/test_mobile_f5a_assisted.py` — nowy | Testy danych i natywnego Tk na prywatnych kopiach. |
| Niniejszy dokument | Audyt, kontrakty, dowody i krótki odbiór. |

Wcześniejszy brudny worktree zabezpieczono przed edycją. Wśród 493 istniejących plików aplikacji zmieniły się w tym zadaniu wyłącznie trzy wskazane pliki integracyjne. Istniejące lokalne poprawki pozostały zachowane.

## 5. Testy i ochrona danych

Testy A3 uruchamiano na prywatnych kopiach archiwów, z odrębnymi sidecarami i katalogami eksportu. A2 i zamrożone GT odczytywano bez zmian. Profil `USERPROFILE`/`APPDATA`/`LOCALAPPDATA` oraz katalog roboczy były skierowane do katalogu tymczasowego.

| Zestaw | PASS | FAIL | SKIP | Uwagi |
|---|---:|---:|---:|---|
| A3, `test_mobile_f5a_assisted.py` | 21 | 0 | 0 | Końcowy przebieg: 108,40 s. Ładowanie 36 sesji, SHA, decyzje i korekty, blok, wielokrotne MT, duplikaty, OCR, N/A, anulowane MT, mieszane fotografie, samoloty, atomowy zapis, wznowienie, eksport, natywny Tk. |
| Regresje scen Z4, bloków obserwacji, wyboru rekordu i A1 | 130 | 0 po powtórzeniu Tk w izolacji | 3 | Sześć plików testów. Pierwszy przebieg: 129 PASS / 1 FAIL / 3 SKIP; następnie cały plik Tk: 13/13 PASS. |
| Regresje trwałości / Canvas / GT Pack / dowodów scen | 129 | 3 | 0 | Trzy błędy odtworzone również w pełnej kopii kodu sprzed A3. |
| Odbiór GUI przez operatora | — | — | — | **NOT_VERIFIED**. |

Regresje Z4/A1: `test_f5a12c_scene_tk.py`, `test_z4_record_selection_context.py`, `test_mobile_observation_blocks.py`, `test_z4_photo_reference.py`, `test_z4_photo_geometry_status.py`, `test_z4_photo_reference_context.py`. Trzy SKIP dotyczą opcjonalnych fixture aktualnego A1, których nie podłączono do tych testów; rzeczywiste zamrożone GT 40/40 zweryfikowano osobno w A3. Błąd gestu S w `test_T28_existing_canvas_scene_scope_gestures[two-roi]` wystąpił przy równoległych oknach testowych; oddzielny przebieg całego pliku Tk przeszedł 13/13. Nie wprowadzano poprawki produkcyjnej dla tego błędu.

Trwałość: `test_mobile_human_review.py`, `test_mobile_p2b2_canvas_review.py`, `test_gt_pack.py`, `test_f5a12c_scene_evidence.py`. Istniejące błędy z `test_mobile_p2b2_canvas_review.py`:

- `test_flags_keep_geometry_and_gt_and_distinguish_model_vs_operator`;
- `test_correcting_gt_invalidates_checked_scene`;
- `test_zero_detection_requires_whole_roi_confirmation`.

Odtworzenie tych samych trzech błędów na zabezpieczonym stanie sprzed A3 nie pozwala ogłosić całego starszego zestawu jako PASS. Nie zmieniano jego oczekiwań ani kodu poza zakresem A3.

Dowody uruchomień i izolowanego środowiska: `C:\Users\48572\AppData\Local\Temp\f5a_a3_review_n0tg8xhs` (`test_env.json`, `a3_complete.log/xml`, `regression_final.log/xml`, `regression_tk_isolated.log/xml`, `persistence.log/xml`, `baseline_persistence.log/xml`). Testy A3 wymagają wskazania `ALPR_A3_A2` i prywatnego `ALPR_OBSERVATION_K02`; bez nich jawnie zgłaszają SKIP, zamiast udawać sprawdzenie rzeczywistej serii.

Kontrola niezmienności: **1920/1920 chronionych plików bez zmian SHA-256, rozmiaru i mtime**. Szczegóły: `protected_before.json` i `integrity_final.json` w katalogu dowodów. Obejmuje materiały/manifesty F5A, produkcyjny i zamrożony GT, artefakty A2, archiwa źródłowe oraz zabezpieczony magazyn/oceny Z4. Oryginalny i zamrożony GT nadal mają SHA `e7af93284b427925fa072e5f5315a4caecb5c90bb4095038d72fddaf6c1c7e82`.

Nie zmieniono Androida, modeli, Z2 ani plików A1. Nie uruchomiono inferencji. Nie wykonano reset/checkout/clean/stash/commit/push. Kontrola składni nowych modułów i `git diff --check` dla edytowanych plików śledzonych przeszła.

## 6. Odbiór operatora — jedna rzeczywista sesja

Sesja: **F5A / R1 / r02 / BLOK_B / K02**, `session_id = exp-1794265037188-43dc06b8`.

Archiwum: `03_uzupelnienia\R1\PAIRED_ROI_01\r02\F5A_R1_r02_BLOK_B_K02.alprsession`.
SHA: `140c20115cf34c67de7e591752b540d152ec07fea2bf7488a8546e97d8899a10`.
Mianowniki: 10 ekspozycji, 10 zdarzeń scen, 44 wywołania MT. W źródle są również przypadki wymagające rozstrzygnięcia N/A.

1. Uruchom ponownie Desktop i otwórz istniejące K02 w **Raporty z telefonu → Weryfikacja próbek**. Wcześniejsze połączenie z GT/A2 zostaje zachowane; jeśli go nie było, połącz znalezione pliki raz.
2. Wybierz zdjęcie. Porównaj GT po lewej z klatką telefonu i wybierz **Zgadza się**, **Popraw** lub **Nie można ustalić**.
3. Rozwiń zdjęcie, wybierz MT i kliknij jego wskazanie. Oceń je jako **Trafne**, **Błędne** lub **Nie można ocenić**. Gotowy numer GT wybierasz tylko wtedy, gdy są różne tablice. Dodatkowe oceny MT są pod **Więcej**.
4. Sprawdź, że **Dalej** niczego nie zatwierdza, a ocena zdjęcia nie zwiększa licznika MT. Źródłowe klatki pozostają w gałęzi **Klatki telefonu**.
5. Zamknij i otwórz tę samą sesję: oceny i ostatni zapisany kontekst mają pozostać. Zachowany eksport jest dostępny w nagłówku. Po rzeczywistym ukończeniu ocen wybierz **Zatwierdź sesję A3**.

Odbiór tej instrukcji nadal **NOT_VERIFIED** — decyzję o zaliczeniu podejmuje operator w działającej aplikacji.

## 7. Ograniczenia naukowe

- TP/FN/FP A3 są oceną operacyjną na konkretnym wywołaniu i jawnej referencji. Nie są pomiarem IoU.
- `polygon_iou`, `nmce`, `tp_at_iou_050` pozostają `null` / N/A bez zgodnego GT CameraX. Nie wytworzono transformacji ani narożników.
- Nie wybieramy najlepszego MZ na podstawie GT. Wiele źródłowych odczytów jednego wskazania pozostaje poza kwalifikacją CER A3; oryginalne dane nie są usuwane.
- Fragment numeru nie jest pełnym GT. N/A nie jest zerowym błędem. Liczba wierszy OCR nie zastępuje liczby wywołań MZ/MT.
- Zatwierdzenie operacyjne A3 nie nadaje historycznym metrykom geometrycznym ani staremu statusowi przeglądarki nowego znaczenia. Wyniki A3 mają odrębne, jawne pola eksportu.
- Testy nie oznaczają oceny eksperymentu przez operatora. Nie dokonano produkcyjnej weryfikacji 1281 wywołań.

**Następny krok:** operator odbiera powyższą sesję K02, a po odbiorze wykonuje w tym samym torze właściwą weryfikację F5A. F5B pozostaje pominięte; F6 dopiero po zakończeniu F5A.
