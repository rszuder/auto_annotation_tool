# Mapa funkcji programu i kodu

Dokument opisuje aplikację na dwóch poziomach:

- funkcjonalnym: co program robi i jakimi pojęciami operuje użytkownik,
- technicznym: gdzie w kodzie szukać konkretnego modułu, przepływu albo problemu.

Nie jest to lista każdej prywatnej funkcji pomocniczej typu `_refresh_*`, bo taka lista byłaby długa, mało czytelna i szybko przestałaby być aktualna. To jest mapa orientacyjna dla dewelopera, promotora albo agenta AI, który ma wejść w repozytorium bez zgadywania, gdzie leży dana część systemu.

## Skrót architektury

Aplikacja jest desktopowym narzędziem Tkinter do iteracyjnej budowy datasetów i modeli ALPR. Obsługuje:

- projekty kampanijne z grafem decyzji,
- import i kontrolę obrazów oraz anotacji tablic,
- autoanotację i ręczną korektę tablic,
- wyodrębnianie tablic i przygotowanie anotacji znaków,
- eksport datasetów YOLO,
- augmentację datasetu treningowego,
- trening modeli tablic i znaków,
- ranking, porównywanie, walidację i wybór modeli jako wyniku bramki.

Główny przepływ startowy:

```text
main.py
  -> dependency_bootstrap.py
  -> auto_annotation_tool.gui.app.AutoAnnotationApp
  -> zakładki GUI: CampaignTab, AnnotationTab, CharacterAnnotationTab, TrainingTab
  -> CampaignManager jako trwały stan projektów i iteracji
```

Najważniejsza zasada architektoniczna:

```text
Graf kampanii prowadzi użytkownika.
Z2, Z3 i Z4 wykonują realną pracę.
CampaignManager przechowuje stan projektu.
Kontrakty zasobów decydują, czy bramka może zostać zatwierdzona.
```

## Główne pojęcia

| Pojęcie | Znaczenie |
| --- | --- |
| Projekt | Osobna przestrzeń pracy w `Workspace/9_projects/<projekt>`. |
| Iteracja | Jeden cykl active learning: wybór zasobów, praca, dataset, trening, powrót do E1. |
| Węzeł `E*` | Stan procesu na grafie kampanii. |
| Bramka `T*` | Decyzja/przejście między węzłami grafu. |
| Z2 | Praca nad anotacjami tablic na obrazach. |
| Z3/PZ2 | Praca nad anotacjami znaków na wyodrębnionych tablicach. |
| Z3/PZ3 | Eksport źródłowego datasetu znaków. |
| Z4/PZ1 | Przygotowanie wariantu datasetu treningowego, split i augmentacja. |
| Z4/PZ2 | Trening modelu, historia runów, ranking i wybór wyniku bramki. |
| O | Obrazy wejściowe. |
| AT | Anotacje tablic na obrazach. |
| AZ | Anotacje znaków na wyodrębnionych tablicach. |
| MT | Model tablic. |
| MZ | Model znaków. |
| Run | Katalog procesu, np. autoanotacji, eksportu albo treningu. |
| Dataset | Zestaw danych YOLO przygotowany do treningu lub walidacji. |
| Kontrakt zasobu | Jednoznaczna odpowiedź, czy zasób jest wymagany, spełniony, do kontroli albo niespełniony. |

## Graf kampanii

Aktualny graf jest opisany deklaratywnie w:

- `auto_annotation_tool/campaign_transition_specs.py`
- `auto_annotation_tool/campaign_transition_graph.py`
- `auto_annotation_tool/campaign_transition_evaluator.py`
- `auto_annotation_tool/gui/campaign_dashboard_ui.py`
- `auto_annotation_tool/gui/campaign_graph_actions.py`

### Aktualne bramki

| Bramka | Przejście | Sens użytkowy |
| --- | --- | --- |
| T01 | `E1 -> E2` | Wybór źródła anotacji tablic dla dalszej pracy. Użytkownik wybiera tor i zasoby startowe. |
| T02 | `E1 -> E3` | Skrót do pracy nad znakami na istniejącym źródle wyodrębnionych tablic. |
| T03 | `E2 -> E3` | Przekazanie zatwierdzonych anotacji tablic do pracy nad znakami. |
| T04 | `E2 -> E4T` | Przygotowanie datasetu i trening modelu tablic. |
| T05 | `E3 -> E4Z` | Przygotowanie datasetu znaków do treningu. |
| T06 | `E4T/E4Z -> E1` | Zamknięcie iteracji po treningu albo świadomym pominięciu treningu. |

Uwaga historyczna: w starszych dokumentach i fragmentach copy może występować `T07`. Aktualnie zamknięcie iteracji pełni bramka `T06`.

### Tory iteracji

| Tor | Typowy przebieg | Cel |
| --- | --- | --- |
| `plate_training` | `E1 -> E2 -> E4T -> E1` | Budowa lub poprawa modelu tablic. |
| `char_from_images` | `E1 -> E2 -> E3 -> E4Z -> E1` | Budowa modelu znaków od obrazów, przez anotacje tablic. |
| `char_from_ready_plates` | `E1 -> E3 -> E4Z -> E1` | Budowa modelu znaków z istniejącego źródła wyodrębnionych tablic. |

## Funkcje programu

### 1. Uruchomienie i środowisko

Program startuje z `main.py`. Przed uruchomieniem GUI wykonywany jest bootstrap zależności i ograniczenie wątków bibliotek numerycznych.

Odpowiedzialne pliki:

- `main.py` - punkt wejścia aplikacji.
- `dependency_bootstrap.py` - sprawdzanie i przygotowanie zależności runtime.
- `auto_annotation_tool/config.py` - konfiguracja katalogów, modeli, CUDA i ustawień globalnych.
- `auto_annotation_tool/session.py` - zapamiętywanie ścieżek i ustawień sesji.
- `auto_annotation_tool/utils.py` - wspólne funkcje pomocnicze.
- `auto_annotation_tool/project_cache.py` - lekki cache odczytów projektowych.

### 2. Główne GUI

Główny shell aplikacji tworzy notebook, menu, status, terminal globalny, motywy oraz mechanizmy bezpiecznego zamykania.

Odpowiedzialne pliki:

- `auto_annotation_tool/gui/app.py` - klasa `AutoAnnotationApp`.
- `auto_annotation_tool/gui/app_startup.py` - splash startowy i gotowość zakładek.
- `auto_annotation_tool/gui/app_shutdown.py` - czyszczenie runtime przy zamknięciu.
- `auto_annotation_tool/gui/app_style_setup.py` - style Tk/ttk.
- `auto_annotation_tool/gui/app_theme_definitions.py` - definicje motywów.
- `auto_annotation_tool/gui/app_theme_runtime.py` - aplikowanie motywu do widgetów.
- `auto_annotation_tool/gui/app_menu_dropdown.py` - menu główne.
- `auto_annotation_tool/gui/app_global_terminal.py` - terminal/log globalny.
- `auto_annotation_tool/gui/app_window_recovery.py` - odzyskiwanie okna po minimalizacji/focusie.
- `auto_annotation_tool/gui/app_tooltips.py` - proste tooltipy.

### 3. Projekty, iteracje i stan kampanii

`CampaignManager` jest głównym właścicielem trwałego stanu projektu. Przechowuje aktywny projekt, iterację, status kroków, ścieżki artefaktów, registry i manifesty.

Odpowiedzialne pliki:

- `auto_annotation_tool/campaign_manager.py` - klasa `CampaignManager`.
- `auto_annotation_tool/campaign_project_registry.py` - lista projektów, tworzenie, usuwanie, aktywny projekt.
- `auto_annotation_tool/campaign_stage_state.py` - statusy etapów, ścieżki, przerwane prace, zasoby iteracji.
- `auto_annotation_tool/campaign_project_history.py` - historia projektu i zdarzeń.
- `auto_annotation_tool/campaign_iteration_paths.py` - normalizacja torów iteracji.
- `auto_annotation_tool/campaign_ingest_planner.py` - plan ingestu obrazów.
- `auto_annotation_tool/campaign_graph_sanity.py` - sanity-check grafu kampanii.

### 4. Kontrakty zasobów

Kontrakty zasobów odpowiadają na pytanie, czy bramka może zostać zatwierdzona. To ważne, bo bramka nie powinna opierać się wyłącznie na kolorze UI albo tekście statusu.

Odpowiedzialne pliki:

- `auto_annotation_tool/campaign_resource_catalog.py` - słownik zasobów: O, AT, AZ, MT, MZ i etykiety.
- `auto_annotation_tool/campaign_resource_state.py` - snapshot zasobu dla UI i kontraktu.
- `auto_annotation_tool/campaign_resource_contracts.py` - helpery gotowości kontraktowej.
- `auto_annotation_tool/campaign_transition_resource_report.py` - tabela raportu zasobów bramki.
- `auto_annotation_tool/campaign_plate_annotation_contract.py` - dopasowanie importowanych AT do obrazów O.

Najważniejszy kierunek stabilizacji:

```text
O -> AT
O/AT -> AZ
MT/MZ -> zasoby modelowe niezależne od paczki obrazów
```

Zmiana źródła obrazów nie powinna po cichu uznawać starych AT/AZ za aktualne. Zasób powinien dostać stan typu `do kontroli`, a użytkownik musi wiedzieć, gdzie tę kontrolę wykonać.

### 5. Dashboard kampanii i graf

Dashboard kampanii jest wizualnym sterownikiem procesu. Nie powinien duplikować logiki Z2/Z3/Z4, tylko wskazywać aktualną bramkę, dostępne działania, zasoby i ślad projektu.

Odpowiedzialne pliki:

- `auto_annotation_tool/gui/tab_campaign.py` - główna zakładka kampanii.
- `auto_annotation_tool/gui/campaign_dashboard_ui.py` - graf, bramki, modale pracy i zasobów.
- `auto_annotation_tool/gui/campaign_graph_actions.py` - wykonywanie akcji z grafu.
- `auto_annotation_tool/gui/campaign_shell_ui.py` - układ lewego/prawego panelu kampanii.
- `auto_annotation_tool/gui/campaign_stage_ui.py` - UI etapów i grafu.
- `auto_annotation_tool/gui/campaign_stage_logic.py` - decyzje zatwierdzania etapów.
- `auto_annotation_tool/gui/campaign_navigation.py` - przejścia z grafu do Z2/Z3/Z4.
- `auto_annotation_tool/gui/campaign_iteration_flow.py` - zamykanie iteracji i przejście do kolejnej.
- `auto_annotation_tool/gui/app_project_history.py` - modal historii projektu i śladu.

### 6. Z2 - anotacje tablic

Z2 służy do pracy na obrazach i ramkach tablic. Działa zarówno w trybie swobodnym, jak i w wielu kontekstach kampanii: T01, T02 kontrola AT, T03/T04/T05/T06 praca naprawcza albo uzupełnianie tablic.

Funkcje Z2:

- lista obrazów z flagami statusu,
- podgląd obrazu na canvas,
- ręczne rysowanie i korekta ramek tablic,
- autoanotacja YOLO,
- import CVAT XML,
- zatwierdzanie obrazów `[OK]`,
- tryb pełnoekranowy,
- liczniki bieżącej sesji i puli projektowej,
- przekazanie zatwierdzonych obrazów/anotacji do grafu,
- obsługa przerwanej pracy.

Odpowiedzialne pliki:

- `auto_annotation_tool/gui/tab_annotation.py` - klasa `AnnotationTab`, główny kontener Z2.
- `auto_annotation_tool/gui/z2_actions.py` - akcje procesu Z2.
- `auto_annotation_tool/gui/z2_annotation_process.py` - proces autoanotacji.
- `auto_annotation_tool/gui/z2_annotation_startup.py` - start i przywracanie pracy.
- `auto_annotation_tool/gui/z2_canvas_interaction.py` - interakcje canvas, skróty, zoom, zaznaczanie.
- `auto_annotation_tool/gui/z2_canvas_overlays.py` - overlaye canvas.
- `auto_annotation_tool/gui/z2_preview_workflow.py` - przepływ podglądu i zatwierdzania.
- `auto_annotation_tool/gui/z2_preview_state.py` - stan listy/podglądu.
- `auto_annotation_tool/gui/z2_preview_editor.py` - edycja ramek.
- `auto_annotation_tool/gui/z2_panel_workflow.py` - panele i liczniki.
- `auto_annotation_tool/gui/z2_campaign_flow.py` - powrót do grafu i kontekst kampanii.
- `auto_annotation_tool/gui/z2_campaign_runtime.py` - runtime kampanii dla Z2.
- `auto_annotation_tool/gui/z2_import_workflow.py` - import AT/CVAT do kontroli.
- `auto_annotation_tool/gui/z2_manifest_runtime.py` - manifesty runów Z2.
- `auto_annotation_tool/gui/z2_restore_workflow.py` - odtwarzanie przerwanej pracy.
- `auto_annotation_tool/gui/z2_right_panel_widgets.py` - prawy panel i widgety statusu.
- `auto_annotation_tool/gui/z2_status_ui_runtime.py` - statusy UI.
- `auto_annotation_tool/gui/z2_view_models.py` - modele widoku Z2.

### 7. Autoanotacja tablic i pojazdów

Warstwa annotatorów opakowuje modele YOLO i runtime walidacji ścieżek.

Odpowiedzialne pliki:

- `auto_annotation_tool/annotators/base.py` - bazowy annotator.
- `auto_annotation_tool/annotators/plate_annotator.py` - detekcja tablic.
- `auto_annotation_tool/annotators/vehicle_annotator.py` - detekcja pojazdów.
- `auto_annotation_tool/annotators/combined_annotator.py` - tryb vehicle-first.
- `auto_annotation_tool/annotators/runtime_factory.py` - bezpieczne tworzenie annotatorów i walidacja modeli.

### 8. Z3 - praca nad znakami

Z3 składa się z kilku podetapów. W kampanii najważniejsze są:

- przygotowanie źródła tablic,
- PZ2: korekta boxów znaków i tekstu,
- PZ3: eksport datasetu znaków.

Funkcje Z3/PZ2:

- lista wyodrębnionych tablic,
- OCR i detekcja znaków,
- pipeline z bloków OCR/YB/YS,
- edycja boxów znaków,
- tryb wpisywania znaków,
- tryb grupowego dziedziczenia geometrii,
- obsługa tablic jedno- i dwurzędowych,
- status perfect/bad,
- zapis metadanych i cofanie operacji,
- wykrywanie przerwanej pracy.

Odpowiedzialne pliki:

- `auto_annotation_tool/gui/tab_character_annotation.py` - klasa `CharacterAnnotationTab`.
- `auto_annotation_tool/gui/z3_init_runtime.py` - inicjalizacja Z3.
- `auto_annotation_tool/gui/z3_campaign_flow.py` - integracja Z3 z grafem kampanii.
- `auto_annotation_tool/gui/z3_extraction_tab_ui.py` - UI wyodrębniania tablic.
- `auto_annotation_tool/gui/z3_extraction_sources.py` - źródła wyodrębniania.
- `auto_annotation_tool/gui/z3_detection_tab_ui.py` - karta detekcji znaków.
- `auto_annotation_tool/gui/z3_detection_pipeline_ui.py` - modal/budowniczy pipeline OCR/YB/YS.
- `auto_annotation_tool/gui/z3_detection_controls_ui.py` - kontrolki detekcji.
- `auto_annotation_tool/gui/z3_detection_runtime.py` - wykonanie detekcji.
- `auto_annotation_tool/gui/z3_detection_algorithms.py` - algorytmy detekcji i łączenia wyników.
- `auto_annotation_tool/gui/z3_detection_model_ui.py` - wybór modelu detekcji.
- `auto_annotation_tool/gui/z3_preview_ui.py` - główny podgląd tablic.
- `auto_annotation_tool/gui/z3_preview_events.py` - klawiatura, mysz, skróty.
- `auto_annotation_tool/gui/z3_preview_editor_runtime.py` - edycja geometrii boxów.
- `auto_annotation_tool/gui/z3_preview_typing_runtime.py` - wpisywanie znaków.
- `auto_annotation_tool/gui/z3_preview_metadata_runtime.py` - status perfect/bad, zapis metadanych.
- `auto_annotation_tool/gui/z3_preview_badges.py` - badge i oznaczenia źródeł boxów.
- `auto_annotation_tool/gui/z3_preview_list_ui.py` - sortowanie/filtrowanie listy tablic.
- `auto_annotation_tool/gui/z3_preview_records.py` - normalizacja źródeł box/sign.
- `auto_annotation_tool/gui/z3_plate_layout_runtime.py` - układ 1R/2R i separator rzędów.
- `auto_annotation_tool/gui/z3_ocr_lab.py` - laboratorium OCR.
- `auto_annotation_tool/gui/z3_export_summary.py` - podsumowanie eksportu.
- `auto_annotation_tool/gui/z3_readiness.py` - gotowość PZ2/PZ3.
- `auto_annotation_tool/gui/z3_session_state.py` - lokalny stan sesji Z3.

Silniki znaków:

- `auto_annotation_tool/character_recognition/char_detector.py` - detekcja znaków OCR/YOLO.
- `auto_annotation_tool/character_recognition/char_annotator.py` - anotator znaków.
- `auto_annotation_tool/character_recognition/plate_generator.py` - generator wyodrębnionych tablic.
- `auto_annotation_tool/character_recognition/reading_order.py` - kolejność czytania boxów.
- `auto_annotation_tool/ocr/plate_ocr.py` - OCR tablic.
- `auto_annotation_tool/ocr/validators.py` - walidacja formatów rejestracji.

### 9. Rektyfikacja i geometria

Rektyfikacja odpowiada za prostowanie tablic i walidację poligonów. Jest używana po stronie tablic i znaków.

Odpowiedzialne pliki:

- `auto_annotation_tool/rectification/plate_rectifier.py` - rektyfikacja tablic.
- `auto_annotation_tool/rectification/polygon_validator.py` - walidacja i naprawa polygonów.
- `auto_annotation_tool/rectification/character_segmentation.py` - segmentacja znaków.
- `auto_annotation_tool/quality_metrics.py` - metryki jakości geometrii.
- `auto_annotation_tool/gui/tab_rectification.py` - zakładka narzędziowa rektyfikacji.

### 10. Z4/PZ1 - dataset, split i augmentacja

PZ1 buduje wariant datasetu treningowego. W zależności od toru pracuje na danych tablic albo znaków.

Funkcje PZ1:

- wybór źródła datasetu,
- podział train/val/test,
- prezentacja liczników,
- opcjonalne syntetyczne powiększenie train,
- konfiguracja i podgląd efektów augmentacji,
- tworzenie wariantu datasetu,
- podgląd gotowego datasetu.

Odpowiedzialne pliki:

- `auto_annotation_tool/gui/z4_dataset_tab_builder.py` - budowa karty PZ1.
- `auto_annotation_tool/gui/z4_dataset_builder.py` - logika tworzenia datasetu i splitu.
- `auto_annotation_tool/gui/z4_dataset_panels.py` - panele PZ1.
- `auto_annotation_tool/gui/z4_dataset_sources.py` - źródła datasetów.
- `auto_annotation_tool/gui/z4_dataset_validation.py` - walidacja źródeł.
- `auto_annotation_tool/gui/z4_dataset_preview.py` - podgląd datasetu YOLO.
- `auto_annotation_tool/training/dataset_creator.py` - tworzenie datasetu YOLO Pose z CVAT.
- `auto_annotation_tool/training/dataset_splitter.py` - podział datasetu.

### 11. Augmentacja

Augmentacja jest konfigurowana w modalnym inspektorze, a wykonywana w backendzie datasetu. Nie ma osobnego modułu `weather.py`; pogoda, światło, materiał i geometria są częścią profilu augmentacji.

Odpowiedzialne pliki:

- `auto_annotation_tool/gui/z4_augmentation_modal.py` - modal efektów, inspektor, canvas, suwaki, presety.
- `auto_annotation_tool/training/dataset_augmentation.py` - `AugmentationProfile`, losowe odchyłki i generowanie obrazów.

Główne grupy efektów:

| Grupa | Przykłady ustawień |
| --- | --- |
| Obraz/sensor | jasność, kontrast, nasycenie, blur, szum. |
| Światło | ambient, reflektory R1/R2/R3, kolor światła, stożki, poświata. |
| Materiał | wypukłość konturów, profil przekroju znaku, błoto, mokry film. |
| Pogoda | deszcz na tablicy, krople, mgiełka przy konturach, wiatr. |
| Geometria | transformacje właściwe głównie dla toru tablic; w torze znaków geometria tablicy jest zasadniczo chroniona. |

Szybkie szukanie ustawień pogodowych:

```powershell
rg -n "weather|rain_|water_film|tyndall|dirt_flow|contour_detection" auto_annotation_tool/gui/z4_augmentation_modal.py auto_annotation_tool/training/dataset_augmentation.py
```

### 12. Z4/PZ2 - trening

PZ2 uruchamia trening YOLO, pilnuje wyboru datasetu, modelu startowego, historii runów, wznowienia i wyboru wyniku bramki.

Funkcje PZ2:

- wybór datasetu treningowego,
- wybór modelu startowego,
- trening nowego modelu,
- dotrenowywanie modelu,
- pauza/stop/wznowienie runu,
- monitoring zasobów CPU/RAM/GPU/VRAM,
- live metryki,
- historia runów,
- przypięcie modelu jako wynik bramki,
- porównanie przebiegów treningów,
- ranking modeli.

Odpowiedzialne pliki:

- `auto_annotation_tool/gui/tab_training.py` - klasa `TrainingTab`.
- `auto_annotation_tool/gui/z4_train_tab_builder.py` - budowa PZ2.
- `auto_annotation_tool/gui/z4_training_runtime.py` - start, stop, wznowienie, historia, wybór wyniku.
- `auto_annotation_tool/gui/z4_training_progress.py` - postęp treningu i diagnostyka błędów.
- `auto_annotation_tool/gui/z4_training_metrics.py` - metryki, kokpit, model startowy, wynik bramki.
- `auto_annotation_tool/gui/z4_training_compare.py` - porównywanie przebiegów treningów.
- `auto_annotation_tool/gui/z4_history_runtime.py` - historia i statusy runów.
- `auto_annotation_tool/gui/z4_device_runtime.py` - wybór urządzenia treningowego.
- `auto_annotation_tool/gui/z4_ui_runtime.py` - dispatch UI i logi procesu.
- `auto_annotation_tool/training/trainer.py` - wrapper treningu YOLO.
- `auto_annotation_tool/training/training_worker.py` - worker treningu w osobnym procesie.
- `auto_annotation_tool/training/training_history.py` - trwała historia treningów.
- `auto_annotation_tool/training/training_report.py` - raport HTML i wykresy.
- `auto_annotation_tool/training/resource_monitor.py` - monitoring zasobów.

### 13. Ranking, walidacja i analiza modeli

Ranking pozwala porównywać modele na wspólnym torze testowym. Walidacja i analiza są kontekstowe dla historii treningu i rankingu.

Odpowiedzialne pliki:

- `auto_annotation_tool/ranking/model_ranking.py` - ranking modeli.
- `auto_annotation_tool/ranking/annotation_comparator.py` - porównywanie anotacji.
- `auto_annotation_tool/ranking/mobile_package_experiments.py` - kontrakt eksperymentów pakietów `MT+MZ` / `MP+MT+MZ`, raportów Android i punktacji mobilnej.
- `auto_annotation_tool/gui/tab_ranking.py` - starsza/oddzielna karta rankingu.
- `auto_annotation_tool/gui/z4_analysis_ranking.py` - analiza runów i raporty rankingowe w Z4.
- `auto_annotation_tool/gui/z4_validation_panel.py` - modal walidacji modeli.
- `auto_annotation_tool/gui/z4_model_export.py` - eksport wybranego modelu.

### 14. Import i eksport formatów

Program pracuje głównie z CVAT XML i YOLO. Dodatkowo ma osobny tor eksportu modeli do klienta mobilnego ALPR jako pakiet `.alprmodel`.

Odpowiedzialne pliki:

- `auto_annotation_tool/converters.py` - konwersja CVAT -> YOLO Pose.
- `auto_annotation_tool/cvat_tools/cvat_zip_manager.py` - ZIP CVAT.
- `auto_annotation_tool/cvat_tools/cvat_character_importer.py` - import znaków z CVAT.
- `auto_annotation_tool/cvat_tools/cvat_character_exporter.py` - eksport znaków do CVAT.
- `auto_annotation_tool/exporters/cvat_exporter.py` - eksport CVAT XML.
- `auto_annotation_tool/exporters/yolo_exporter.py` - eksport YOLO Pose.
- `auto_annotation_tool/exporters/mobile_model_exporter.py` - budowa pojedynczego `.alprmodel` (`alpr.model.v1`) oraz kompletnego pakietu `MT+MZ` lub `MP+MT+MZ` (`alpr.package.v1`).
- `auto_annotation_tool/exporters/report_generator.py` - raporty.
- `auto_annotation_tool/validators.py` - walidacja modeli i metadanych YOLO.
- `auto_annotation_tool/gui/z4_model_export.py` - modal eksportu modeli, wybór kandydatów i formatów mobilnych.
- `alpr_python_exporter_handoff.md` - kontrakt eksportera Python z klientem Android.
- `docs/eksport_mobilny_kwantyzacja.md` - opis formatów, kwantyzacji, kalibracji i parametrów inferencji dla pracy inżynierskiej.
- `docs/siatka_eksperymentow_mobilnych_alpr.md` - metodyka porównywania modeli, pakietów `MT+MZ` / `MP+MT+MZ`, wariantów runtime i wyników mobilnych.
- `docs/podbudowa_literaturowa_metodyki_testow_alpr.md` - uzasadnienie literaturowe: podzial danych, metryki detekcji, ocena end-to-end, testy mobilne i kwantyzacja.
- `docs/specyfikacja_agenta_aplikacji_mobilnej_alpr.md` - specyfikacja dla agenta Android: import `.alprmodel`, walidacja, inferencja mobilna i metodyka badań.

Uwaga: zaznaczenie kilku formatów w modalu eksportu mobilnego oznacza kilka wariantów tego samego checkpointu `best.pt` w jednym pakiecie `.alprmodel`, a nie kilka oddzielnych modeli logicznych.

### 15. Identyfikatory prezentacyjne

Długie nazwy datasetów, runów i modeli są skracane do czytelnych ID w UI. To ważne, bo użytkownik nie powinien porównywać ścieżek systemowych.

Odpowiedzialne pliki:

- `auto_annotation_tool/gui/dataset_display.py` - ID datasetów.
- `auto_annotation_tool/gui/model_display.py` - ID modeli.
- `auto_annotation_tool/gui/run_display.py` - ID runów.

## Mapa katalogów

```text
auto_annotation_tool/
  annotators/              # YOLO annotatory tablic/pojazdów
  character_recognition/   # OCR, detekcja znaków, generator cropów tablic
  cvat_tools/              # import/export CVAT i ZIP
  exporters/               # eksport CVAT/YOLO/raportów
  gui/                     # całość interfejsu Tkinter
  ocr/                     # OCR i walidatory rejestracji
  ranking/                 # ranking modeli i porównania anotacji
  rectification/           # prostowanie tablic i geometria
  training/                # dataset, augmentacja, trening, worker, monitoring
```

## Mapa najważniejszych klas

| Klasa | Plik | Rola |
| --- | --- | --- |
| `AutoAnnotationApp` | `gui/app.py` | Główne okno i zakładki. |
| `CampaignManager` | `campaign_manager.py` | Stan projektów, iteracji i artefaktów. |
| `CampaignTransitionSpec` | `campaign_transition_specs.py` | Deklaracja bramki/przejścia grafu. |
| `CampaignTransitionGraph` | `campaign_transition_graph.py` | Statyczny model grafu kampanii. |
| `CampaignResourceSnapshot` | `campaign_resource_state.py` | Snapshot zasobu dla kontraktu i UI. |
| `AnnotationTab` | `gui/tab_annotation.py` | Z2, anotacje tablic. |
| `CharacterAnnotationTab` | `gui/tab_character_annotation.py` | Z3, znaki i dataset znaków. |
| `TrainingTab` | `gui/tab_training.py` | Z4, dataset, trening, ranking. |
| `Step4AugmentationModal` | `gui/z4_augmentation_modal.py` | Modal efektów augmentacji. |
| `AugmentationProfile` | `training/dataset_augmentation.py` | Dane profilu augmentacji. |
| `PlateAnnotator` | `annotators/plate_annotator.py` | Detekcja tablic. |
| `CharacterDetector` | `character_recognition/char_detector.py` | Detekcja znaków. |
| `PlateOCR` | `ocr/plate_ocr.py` | OCR tablic. |
| `PlateRectifier` | `rectification/plate_rectifier.py` | Rektyfikacja tablic. |
| `ModelRanking` | `ranking/model_ranking.py` | Ranking modeli. |
| `TrainingResourceMonitor` | `training/resource_monitor.py` | Monitoring zasobów treningu. |

## Typowe ścieżki debugowania

### Bramka pokazuje zły status

Sprawdź kolejno:

```powershell
rg -n "resource_contract_ready|build_resource_contract_meta|CampaignResourceSnapshot" auto_annotation_tool
rg -n "get_campaign_step|approve_step|ready|interrupted" auto_annotation_tool/campaign_stage_state.py auto_annotation_tool/gui/campaign_dashboard_ui.py
rg -n "build_transition_resource_report|TransitionResourceReport" auto_annotation_tool
```

### Bramka prowadzi do złej karty

Sprawdź:

```powershell
rg -n "open_z2_campaign_context|continue_z3|open_z4|graph_action|approve_action" auto_annotation_tool/campaign_transition_specs.py auto_annotation_tool/gui/campaign_graph_actions.py auto_annotation_tool/gui/campaign_navigation.py
```

### Z2 pokazuje złe liczniki lub wolno zatwierdza

Sprawdź:

```powershell
rg -n "approved|OK|right|counter|refresh|preview_list|manifest" auto_annotation_tool/gui/z2_*.py auto_annotation_tool/gui/tab_annotation.py
```

### Z3/PZ2 gubi status perfect albo boxy

Sprawdź:

```powershell
rg -n "perfect|bad|layout|separator|manual|source_tag|metadata|derive_preview_status" auto_annotation_tool/gui/z3_*.py auto_annotation_tool/character_recognition
```

### Pipeline detekcji znaków nie pamięta ustawień

Sprawdź:

```powershell
rg -n "pipeline|ocr|yb|ys|session|detection_yolo|confidence" auto_annotation_tool/gui/z3_*.py
```

### Augmentacja nie działa albo nie widać efektu

Sprawdź:

```powershell
rg -n "AugmentationProfile|preview_augmentation_image|rain_|water_film|traffic_headlight|relief|contour" auto_annotation_tool/training/dataset_augmentation.py auto_annotation_tool/gui/z4_augmentation_modal.py
```

### Dataset nie propaguje się do treningu

Sprawdź:

```powershell
rg -n "dataset_variant|data.yaml|training_source|_get_step4_augmentation_profile|_refresh_dataset_variant_choices" auto_annotation_tool/gui/z4_*.py
```

### Trening nie widzi modelu albo nie można wznowić

Sprawdź:

```powershell
rg -n "resume|last.pt|best.pt|pinned|campaign result|training_result|base_model" auto_annotation_tool/gui/z4_training_*.py auto_annotation_tool/training
```

### Ranking modeli jest pusty

Sprawdź:

```powershell
rg -n "ranking|candidate|scope|project|global|participants|race" auto_annotation_tool/gui/z4_*.py auto_annotation_tool/ranking
```

## Zasady bezpiecznego rozwoju

1. Nie dokładać drugiego źródła prawdy, jeżeli istnieje już stan w `CampaignManager`.
2. Bramka może być aktywna tylko wtedy, gdy kontrakt zasobu na to pozwala.
3. Z2/Z3/Z4 wykonują pracę, a graf tylko prowadzi użytkownika.
4. Zmiana zasobu O wymaga ponownej oceny AT/AZ, ale nie musi fizycznie kasować starych artefaktów.
5. Import AT powinien trafiać do kontroli, nie od razu do puli `[OK]`.
6. Artefakty z poprzednich iteracji muszą być oznaczone iteracją powstania.
7. UI powinien pokazywać różnicę między wynikiem z poprzednich iteracji a przyrostem bieżącej iteracji.
8. Długie nazwy runów, datasetów i modeli powinny być prezentowane przez krótkie ID.
9. Przerwana praca musi być zapisana i monitorowana przez właściwą bramkę.
10. Operacje kosztowne powinny mieć realny splash/progress i nie mogą pokazywać niedobudowanego modala.

## Dokumenty powiązane

- `DZIENNIK_ARCHITEKTURY_I_ZMIAN.md` - roboczy dziennik decyzji i zmian.
- `docs/wizard_przebudowa.md` - starszy opis przebudowy wizarda.
- `docs/kampania_plan_testow.md` - plan testów ręcznych kampanii.

## Szybki indeks dla agenta AI

Jeżeli nie wiesz, gdzie zacząć:

```powershell
rg -n "badge_id|CampaignTransitionSpec" auto_annotation_tool/campaign_transition_specs.py
rg -n "class CampaignManager|approve_step|get_step" auto_annotation_tool/campaign_manager.py auto_annotation_tool/campaign_stage_state.py
rg -n "class AnnotationTab|Z2" auto_annotation_tool/gui/tab_annotation.py auto_annotation_tool/gui/z2_*.py
rg -n "class CharacterAnnotationTab|PZ2|PZ3" auto_annotation_tool/gui/tab_character_annotation.py auto_annotation_tool/gui/z3_*.py
rg -n "class TrainingTab|PZ1|PZ2|training" auto_annotation_tool/gui/tab_training.py auto_annotation_tool/gui/z4_*.py
rg -n "class AugmentationProfile|class Step4AugmentationModal" auto_annotation_tool/training/dataset_augmentation.py auto_annotation_tool/gui/z4_augmentation_modal.py
```
