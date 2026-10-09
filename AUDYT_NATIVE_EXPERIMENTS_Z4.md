# Audyt integracji eksperymentów Z4 — 2026-10-09

## Zakres i decyzja

Dyspozycja operatora: naprawić źródło przecieku, rozdzielanie identycznych scen MT między splity i wykonać handoff natywnych eksperymentów. Ten dokument powstaje przed implementacją. Bieżąca dostawa obejmuje naprawy oraz Fazę 1 (odczyt ukończonych MZ); nie uruchamia nowych pomiarów ani treningów. Kolejne fazy wymagają odbioru GUI i rozstrzygnięcia geometrii MT.

Przeczytano cały `HANDOFF_AGENT_Z4_NATIVE_KAMPANIA_EKSPERYMENTALNA_ALPR_2026-10-09.md`, plan z 2026-10-09 i trzy dokumenty architektury Desktop/Android/interoperacyjności z Downloads. Plan zawiera starsze statusy; obowiązują nowsze artefakty i handoff. Dokładnych wersji `tresc_pracy(20261008-225639).tex` i `EE-dyplom(20261008-225638).tex` nie znaleziono w Desktop/Downloads. Starszych wersji nie traktowano jako aktualnej pracy.

Repo Desktop: HEAD `2c1373d`, gałąź `funkcja/az-crop-registry`; zastane zmiany Z3, augmentacji, main.py i robocze patche pozostają poza zakresem. Sorter jest osobnym repo `../menadzer_obrazow`, ma lokalne zmiany v1.1; poprawki muszą zachować jego szkice i jawne kopiowanie.

## Stan funkcji i punkty integracji

| Funkcja | Istniejący kod | Stan przed zmianą |
|---|---|---|
| Historia → Porównaj wybrane | `gui/z4_training_compare.py` | Krzywe treningowe; nie niezależny benchmark |
| TEST / START walidacji | `gui/z4_validation_panel.py`, `gui/z4_training_runtime.py` | YOLO.val na data.yaml i splicie |
| TOR → Zmień tor testowy | `gui/z4_analysis_ranking.py::_collect_ranking_track_candidates`, `tab_training.py::_resolve_ranking_reference_source` | MZ: data.yaml, MT: XML; brak selection_manifest |
| START → Uruchom wyścig | `z4_analysis_ranking.py::_run_ranking_v2` | MZ metryki detekcji, MT AnnotationComparator; brak Exact/CER EVAL396 |
| MT AnnotationComparator | `ranking/annotation_comparator.py` | Bbox IoU .50/.80/.95, heurystyczne P/R; nie AP ani narożniki Pose |
| Plik roboczy MT | `_run_ranking_v2` | `temp_ranking_auto.xml` tworzony wewnątrz reference_dir — wymaga izolacji |
| WYNIKI / PODGLĄD / RAPORT | `z4_analysis_ranking.py` | Gotowe Treeview, Canvas, SVG/CSV/Markdown; rozszerzyć o rodzaj metryki |
| Whole plate OCR | `ranking/mz_whole_plate_evaluation.py` | Wspólna kolejność czytania i CER; użyć do weryfikacji importu |
| Android research | `ranking/mobile_package_experiments.py`, `mobile_mt_invocations.py`, `mobile_human_review.py`, `gui/z4_mobile_report_browser.py` | Istniejący kanał .alprsession; crop-session nie zastępuje pełnego eksperymentu |

Przepływ integracji: istniejący TrainingTab → wybór TOR → adapter selekcji i zapisanych wyników → istniejące okna wyników/raportu → osobny eksport raportu. Import nie dopisuje fikcyjnego treningu ani nowego pomiaru.

## Potwierdzone artefakty

- EVAL396: `Workspace/E-MZ-DN-01/evaluation_selections/E-MZ-DN-01_EVAL396_20261009`, schema `emzdn01.eval_scene_selection.v1`, fingerprint `1f2db18cd073114f230ca2dd70a76ea9d1257d624dddf7ff39f51ada8e66aefe`.
- Jednostki: 396 scen (199 DAY / 197 NIGHT), 479 tablic lokalizacji (235/244), 449 zatwierdzonych tekstów (230/219), 30 unreadable (5/25).
- Freeze GT: `33add3fda705416bb88ed9b1ab71e275d2c4f36dd8f5b1bb2f2cbc59130ff77b`; nie jest zmieniany.
- Istniejące `evaluation_runs/E-MZ-DN-01_EVAL396_MZ_v1`: trzy pary manifest/summary/rows oraz comparison. MZ-DAY: 299/449 Exact = 66.59%, CER 283/3052 = 0.0927. To izolowane MZ na GT cropach, nie E2E, mAP lub Android.
- Import ma sprawdzić SHA wszystkich plików, tożsamości modeli, selekcji i GT oraz rzeczywiste rekordy i agregację, a nie tylko obecność summary.

## Przyczyny dwóch błędów

1. Sorter `packages.inventory_complete` potwierdzał jedynie kompletność dostarczonych pakietów. Sesja obejmowała tylko MZ-s, bez MT-n. To pozwoliło skopiować cztery sceny obecne w MT; sam SHA działał poprawnie. Nowa bramka musi wymagać odrębnego kontraktu pełnej populacji modeli/rodziców oraz wszystkich splitów. Starszy skan bez kontraktu nie uzyskuje automatycznie certyfikatu niezależności.
2. `DatasetCreator.create_dataset` i ogólny `DatasetSplitter.split_dataset` losowały pliki/nazwy. Bazowe MT ma 1000 plików / 990 SHA, w tym pięć SHA w różnych splitach. Nowe podziały mają utrzymywać wszystkie kopie i zadeklarowane pochodne sceny w jednej grupie. Historia i stare datasety pozostają niezmienione.

## Minimalna sekwencja poprawek

1. **MT source groups:** wspólny deterministyczny podział po źródłowym SHA, manifest przypisania; oba wejścia tworzenia splitu. Testy duplikatów nazw/SHA, małych zbiorów, pochodnych oraz niezmienności źródła.
2. **Sortownia:** kontrakt wymaganych modeli/inventory i rodziców, walidacja przed skanem/kopiowaniem/wznowieniem, kontrola wszystkich splitów, czytelny stan braków i wybór kontraktu w GUI. Test odtwarzający MZ-only kontra MT+MZ.
3. **Adapter EVAL396:** odczyt selekcji, GT, lineage i ukończonych wyników; SHA i semantyka, brak inferencji, brak zapisu w danych źródłowych. Test jednego zmienionego bajtu i zmienionego mianownika.
4. **Istniejący Z4:** TOR EVAL396, WYNIKI/PODGLĄD/RAPORT z DAY/NIGHT/ALL, Exact/CER i źródłami. Osobny katalog plików roboczych starego rankingu MT. Test realnych widgetów Tk i eksportu/odczytu raportu.

## EXIF i dalsze fazy

Z2 używa `ImageOps.exif_transpose`, Z3 `cv2.imread`, a pomocnicze odczyty rozmiaru mogą zwracać surowe PIL.size. Stary preflight blokuje scenę SG621AW z EXIF. Obecność `preflight_emzdn01_eval396_mt_exif_v2.py` nie stanowi potwierdzenia polityki współrzędnych GT. Nie wybieramy jej milcząco i nie transformujemy freeze. Pomiar MT/Pose oraz E2E pozostają niedostępne dla tej selekcji do rozstrzygnięcia i odbioru następnej fazy.

Nie wykonujemy nowych treningów, MT/MZ inferencji, pomiarów telefonu, wyboru zwycięzcy, freeze końcowego ani final_test. Pełny plan dalszych faz pozostaje w handoffie.

## Stan przeglądu GUI przed implementacją

Kod i nazwy kontrolek potwierdzone lokalnie. Inicjalizacja `computer-use` działa, lecz `sky.list_apps()` zgłasza `Computer Use native pipe is unavailable` (Windows os error 2). Nie jest to GUI PASS. Sprawdzenie widgetów Tk i zrzut uruchomionego widoku należy odnotować oddzielnie od odbioru operatora. Nie uznawać samych testów za akceptację kolejnej fazy.

## Wykonana dostawa — naprawy i Faza 1

**Desktop:** `training/scene_split.py` grupuje spójne tożsamości źródła i dokładnego pliku, z deterministycznym seed. `DatasetCreator` oraz ogólny `DatasetSplitter` korzystają z niego przed zapisem. Manifest `scene_split_assignment.json` zachowuje pochodzenie także przy kolejnych podziałach. Znane augmentacje są przypięte do źródeł. Kopie nie są kasowane ani arbitralnie deduplikowane; ich etykiety zostają przy swoich próbkach. Niepełna genealogia augmentacji MT blokuje podział. Cropy MZ bez źródła nie dostają fikcyjnego source-scene SHA.

**Sorter:** osobny `alpr_eval_sorter/experiment.py` wymaga kontraktu `alpr.eval_independence_contract.v1`, pełnej listy modeli/rodziców i filtrów train/val/test. `alpr_pipeline` wymaga MT i MZ; jawny `single_stage` certyfikuje tylko jedną rolę. Bramka działa przy kopiowaniu, także po wznowieniu, i ponownie odczytuje rzeczywiste pakiety. Starsze szkice pozostają dostępne, ale brak kontraktu blokuje eksport obrazów. Kontrakt nie jest wyprowadzany automatycznie z przypadkowego zestawu wybranych pakietów. Format oraz obsługa: `../menadzer_obrazow/KONTRAKT_NIEZALEZNOSCI.md`.

**Z4:** `ranking/eval396.py` sprawdza zaakceptowane fingerprinty, SHA manifestów/runów/wierszy, rzeczywiste źródła freeze, sześć checkpointów i historie, kompletność inventory oraz lokalny rodowód. Odtwarza Exact/CER wspólnymi funkcjami aplikacji z zapisanych predykcji i porównuje wyniki z summary/comparison. Dla historycznych inventory weryfikuje fingerprint istniejącego datasetu; pliki tego odtworzenia też trafiają do kontroli przed/po. Nie ładuje checkpointów do inferencji.

`gui/z4_eval396.py` rozszerza istniejące wejścia TOR/KONIE/WYNIKI/PODGLĄD/RAPORT. Wybór EVAL396 wyłącza znaczenie pola splitu YOLO, pokazuje różne jednostki MT/MZ i prowadzi do odczytu wyników. Kontrole nie uruchamiają dotychczasowego runnera YOLO dla tej selekcji. Worker i kolejka utrzymują responsywność Tk podczas pełnej kontroli źródeł. Nie ma automatycznej promocji modelu ani fikcyjnych wpisów historii treningów. Raport eksportuje SVG/CSV/Markdown i provenance.json do nowego, osobnego katalogu; ponowna kontrola źródeł poprzedza publikację. Przerwany eksport pozostaje oznaczony PARTIAL.

Stary ranking MT zapisuje roboczy XML w odrębnym katalogu `ranking/temporary`, a nie w materiale referencyjnym. Jego metryki nadal nie są prawdziwym Pose AP — Faza 2 nie została zastąpiona tym porównaniem.

### Wyniki kontroli

| Kontrola | Wynik i dokładny zakres |
|---|---|
| Końcowy zestaw Desktop | **108 PASS**, nowe testy EVAL396/MT oraz regresje source inventory, grup MZ, OCR i rozkładu klas |
| Cała lokalna suita sortera | **59 PASS**, także rzeczywiste widgety Tk, resume, crash recovery, jawne kopiowanie, brak kontraktu/rodzica/MT i zmieniony pakiet |
| Rzeczywisty EVAL396 | **PASS**: 6 modeli, 396 scen, 479 tablic, 449 odczytów/model; wynik MZ-DAY ALL 299/449 i 283/3052 |
| Mutacje fixture | **FAIL zgodnie z oczekiwaniem**: zmiana bajtu rows, summary, comparison lub run_manifest; zmieniony GT przy zgodnych lokalnych sumach też odrzucony |
| Odczyt/eksport raportu | **PASS**, CSV ma 9 wierszy wyników, Markdown i SVG zawierają 66.59% i 0.0927; źródła są przypięte SHA |
| GUI | **PASS w izolowanym hoście Tk**: rzeczywisty istniejący wybór toru Z4, przejście przez jego przycisk do resolvera, rzeczywisty widok wyników i zmiana ALL→NIGHT / Exact→CER; zrzuty obejrzane |
| Chronione dane | **2640 plików, 0 zmian SHA**: freeze GT, EVAL396, ukończone MZ, źródłowe sceny, wskazane checkpointy i historie |

Jedyny wykryty problem regresji Desktopu był w fixture: 18 rzekomo różnych obrazów miało identyczne bajty `fake`. Fixture rozkładu klas otrzymała różne bajty; nie osłabiono bramki wykrywającej identyczne sceny.

Dowody lokalne:

- [Wybór toru w istniejącym modalu Z4](Workspace/_qa/native_experiments_20261009/z4_eval396_track.png)
- [Rzeczywiste wyniki MZ / ALL](Workspace/_qa/native_experiments_20261009/z4_eval396_results.png)
- [NIGHT / porządek według CER](Workspace/_qa/native_experiments_20261009/z4_eval396_night_cer.png)
- [Odczytane wartości i ścieżka eksportu](Workspace/_qa/native_experiments_20261009/gui_smoke_result.json)
- [Kontrola niezmienności danych](Workspace/_qa/native_experiments_20261009/protected_after_check.json)

Testy Tk nie oznaczają odbioru operatora w jego pełnej, bieżącej sesji aplikacji. W celu ochrony historii nie uruchamiano nowego pełnego `TrainingTab.__init__` z automatyczną rekonsyliacją historii. Zamiast tego użyto rzeczywistych funkcji i widgetów toru/wyników w izolowanym oknie Tk.

### EXIF — nowe dowody, bez zmiany polityki GT

Read-only `preflight_emzdn01_eval396_mt_exif_v2.preflight(check_model_task=False)` zakończył kontrolę geometrii: **479/479**, domeny 235/244, źródła 199/197. Nie uruchomiono inferencji ani ładowania modeli YOLO.

Jedyna scena z orientacją EXIF to `DAY/SG621AW_001_607e39a8fd50_c9386732fc.jpg`: Orientation=6, surowe PIL.size=4032×3024, `ImageOps.exif_transpose` i OpenCV 4.13.0 = 3024×4032. Porównanie miniatur dekoderów: MAE=1.49, p95=5.00. To potwierdza zgodność tych dekoderów i kontrolę granic/geometrii; nie jest samo w sobie wizualnym zatwierdzeniem położenia GT ani decyzją operatora o układzie współrzędnych przyszłego pomiaru MT. Niczego w GT nie transformowano.

### Granice i następny krok

Ukończono naprawy kodu oraz Fazy **0–1**. Historyczne 1000/990 obrazów MT i pięć kolizji SHA między splitami nie są przepisywane; naprawa dotyczy tworzenia nowych podziałów, nie retrospektywnej zmiany wyników. Grupowanie identyczności nie certyfikuje braku near-duplicates. Ogólne łączenie istniejących datasetów (`merge_datasets`) nie przebudowuje ich historycznych splitów i nie stanowi nowego certyfikowanego podziału.

Następny krok operatora w aplikacji po przeładowaniu kodu: **Z4 → ranking → [ TOR ] Zmień tor testowy → EVAL396 — zamrożona selekcja → zastosuj → [ WYNIKI ]**. Obejrzeć ALL/DAY/NIGHT, zmienić kryterium Exact/CER, sprawdzić raport i zaakceptować Fazę 1. W NIGHT lider Exact i lider CER różnią się; nie należy utożsamiać kolejności z automatycznym wyborem wdrożenia.

Handoff §7 wymaga: „raport przeglądu i screenshot faktycznego GUI przed kolejną fazą” oraz odróżnienia pytest PASS od akceptacji workflow. Dlatego Fazy 2–7 pozostają do kolejnych, sekwencyjnych odbiorów: jawna polityka geometrii MT, MT/Pose, wybrane pary E2E, pomiary mobilne, decyzja o konfiguracji końcowej i pojedynczy final_test. Nie rozpoczęto żadnego z tych pomiarów, nie wybrano zwycięzcy, nie zmieniono pracy TeX, nie wykonano commit/push.

Automatyczna kontrola narzędzia odrzuciła sprzątanie `.pytest_native_contract_20261009` i `.pytest_native_regression_20261009` w repo sortera (`blocked by policy`). Te pomocnicze katalogi pozostawiono na dysku. Końcowe testy używają `start4/Workspace/_pytest`; nie zmieniono reguł bezpieczeństwa ani zawartości chronionych zbiorów.
