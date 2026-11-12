# Z4 / K02-B — audyt bloków stabilnej sceny

Data: 10.11.2026. Repozytorium: `C:\Users\48572\Desktop\dyplom\start4`.

## Werdykt etapu A

**Nie wdrożono grupowania ani zmiany nawigacji.** Zastosowano warunek operatora: „Jeżeli brakuje dowodów koniecznych do bezpiecznego grupowania, zatrzymaj implementację i wskaż brak”.

Źródła pozwalają odtworzyć **10 przedziałów między zdarzeniami zmiany sceny** oraz wiarygodne powiązania MP/MT/MZ. **Nie pozwalają wyznaczyć początku stabilności tych scen**. Wszystkie 10 rekordów ma `settling_status=NOT_ASSESSED`. Nie ma zapisanego, powiązanego ze źródłem zdarzenia osiągnięcia stabilności.

Liczba potwierdzonych **bloków stabilnej sceny: N/A**, nie 10 i nie zero. Liczba znalezionych znaczników osiągnięcia stabilności: **0**. To dwie różne informacje.

Nie utożsamiono potwierdzenia zmiany, zakończenia kolejki analizy, braku ruchu kamery ani zapisu JPEG z potwierdzeniem stabilnego obrazu TV.

## 1. Użyte źródło i integralność

Odczytano dokładnie wskazany poprawny plik:

```text
C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\03_uzupelnienia\R1\PAIRED_ROI_01\r02\F5A_R1_r02_BLOK_B_K02.alprsession
```

- SHA-256: `140c20115cf34c67de7e591752b540d152ec07fea2bf7488a8546e97d8899a10`.
- `session_id`: `exp-1794265037188-43dc06b8`.
- `report_id`: `r-1794265353818-ALPR-MT-261009-1053-4A2D-MZ-261007-2336-390B`.
- Te identyfikatory i SHA odpowiadają istniejącemu rekordowi magazynu Desktop.
- `analysis_mode=static`, `scene_handling_mode=strict_scene_boundary`.
- Istniejący `read_mobile_report_bundle()` zweryfikował **263 sumy SHA**, `validation.ok=True`.
- Pozostają ostrzeżenia parsera: uzupełnienie pochodzenia modeli z manifestów pipeline oraz niekompletne dowody ról. To nie jest błąd integralności archiwum; trzy wywołania zostały anulowane po zmianie sceny.

Sprawdzono: `session.json`, `report.json`, `events.jsonl`, `application.log`, `samples/scene_evidence.jsonl`, dziennik scen, `samples/mt_detection_roles.jsonl`, `samples/attempts.jsonl`, `samples/crops.jsonl`, `samples/annotations.jsonl`, `samples/tv_bbox_inputs.jsonl`, `samples/schema.json`, `telemetry/traces.jsonl` oraz manifest.

Pełne identyfikatory, granice w nanosekundach, klatki, SHA klatek, źródła MP, listy wywołań MT, ROI i próby MZ są w [maszynowym mapowaniu audytu](Z4_K02_MAPOWANIE_ZDARZEN_SCEN_2026-11-10.json). Ten plik jest wyłącznie raportem — aplikacja go nie używa jako GT, indeksu ani konfiguracji.

## 2. Jak Android wykrywa zmianę i co oznacza stabilizacja

Sprawdzono bieżący lokalny kod Androida tylko do odczytu; nie zmieniano projektu ani APK. Opis kodu nie zastępuje dowodu wykonania każdego warunku na urządzeniu. Konkretne powody zmian w K02 potwierdzają wpisy archiwum.

### Wykrycie zmiany statycznej sceny

`continuity/StaticSceneWatcher.java`, `observeFrame()`:

- porównuje luminancję z utrzymywanym obrazem odniesienia, kompensując średnią zmianę ekspozycji;
- obserwuje obszary ALPR oraz obszar globalny; profil domyślny ma margines 0,12, progi udziału zmienionych pikseli 0,30 lokalnie / 0,55 globalnie i różnicę luminancji 24;
- zwykłe potwierdzenie zmiany luminancji wymaga 2 obserwacji i co najmniej 50 ms; silny skok od 0,65 może potwierdzić zmianę natychmiast;
- dodatkowe kanały utraty/przemieszczenia lub pojawienia się cech wymagają 3 potwierdzeń i co najmniej 120 ms;
- są to warunki **potwierdzenia różnicy wobec poprzedniego obrazu**, nie znaczniki zakończenia przejścia TV ani osobny test stabilności nowego obrazu.

`pipeline/AlprPipeline.java`, `observeStaticLuma()` / `recordF5aSceneBoundary()`:

- potwierdzona zmiana powoduje `HARD_RESET` i zwiększenie generacji sceny/epoki;
- resetuje stan kolejki i obserwatora, zapisuje `SCENE_BOUNDARY` z nowymi generacjami oraz zdarzenie `static_scene_boundary`;
- żąda kolejnej klatki do przetworzenia. Nie dopisuje zdarzenia „scena ustabilizowana”.

`experiment/F5aEvidence.java`, `create()`, linia około 71, zapisuje literalnie `settling_status="NOT_ASSESSED"`. `capture()` zapisuje pierwszą kwalifikującą się klatkę tego zdarzenia. To nie jest klatka oznaczona jako wybrana po potwierdzeniu stabilności. Dziennik scen również zawiera wyłącznie `NOT_ASSESSED`.

### Dlaczego inne stany nie są zastępstwem

`acquisition/StaticSceneCycle.java` definiuje tylko `BASELINE`, `AZ_REFINEMENT`, `STATIC_IDLE`. `STATIC_IDLE` następuje po zakończeniu fazy podstawowej i wyczerpaniu dalszych kandydatów/refinementu. Zdarzenie `static_scene_idle` jest emitowane **po pracy kolejki**, a nie na początku stabilności obrazu.

W K02 występuje 6 zdarzeń `static_scene_idle`; nie mają one `source_stamp` ani `scene_event_id`. Wszystkie 54 zachowane ślady przetwarzania mają `static_scene_phase=BASELINE`.

`tracking/VisualMotionEvidenceDecay.java` utrzymuje krótkie dowody ruchu kamery przez 500 ms i ogon `settling` do 5 s. Jest to mechanizm ciągłości/ruchu kamery. Nie potwierdza nieruchomości treści prezentowanej na TV. W K02 `camera_motion_settling=0` we wszystkich 54 śladach nie stanowi dowodu stabilności fotografii.

W `events.jsonl` ani `application.log` nie znaleziono alternatywnego znacznika osiągnięcia stabilności. `auto_annotation_tool/ranking/mobile_scene_evidence.py` około linii 122 akceptuje w bieżącym kontrakcie właśnie `NOT_ASSESSED`. Nie wykazano utraty znacznika przez importer UX02 — brakuje go już w źródle.

## 3. Znaczenie czasów — bez mieszania domen

| Pole | Rzeczywiste znaczenie |
|---|---|
| `source_stamp.source_timestamp_nanos` + `source_timestamp_domain=CAMERAX_SENSOR` | Znacznik klatki wejściowej z CameraX/ImageInfo. Nie jest czasem otrzymania wyniku. `camera/CameraSourceTimeline.java` nadaje również `source_sequence`. |
| `event_stamp` | Źródło obserwacji powiązanej ze zdarzeniem; zawiera generacje. |
| `event_elapsed_nanos` | Czas zarejestrowania granicy przez Android `elapsedRealtimeNanos`; nie czas końca inferencji ani stabilizacji. |
| `scene_evidence.capture_elapsed_nanos` | Początek kopiowania pełnej klatki dowodowej. `ResearchSessionStore.captureSceneEvidence()` przekazuje `started`. |
| `capture_duration_nanos` | Czas operacji kopiowania tej klatki. |
| `attempt_started_elapsed_nanos` | Utworzenie rekordu próby przed przygotowaniem/wykonaniem MT. Nie jest osobnym timestampem wejścia do backendu MT. |
| `attributes.processing_started_nanos` | Początek przetwarzania całej klatki przez pipeline; w domenie `elapsedRealtimeNanos`. |
| `attributes.result_available_nanos` | Dostępność wyniku pipeline, zapisywana po pracy silnika. Występuje dla 41 z 44 śladów MT; nie występuje dla 3 anulowanych. |
| `elapsed_realtime_ns` w śladzie | Utworzenie `InferenceTrace`, a nie koniec inferencji. |
| `stage_ms.*_inference` | Zmierzone czasy trwania etapów, nie absolutne timestampy początku/końca każdego wywołania. |
| `attempt.source_frame_capture_elapsed_nanos` | Mimo nazwy: **czas trwania** kopiowania klatki, obliczany jako `now - frameCaptureStarted` w `MobileAlprEngine.java` około linii 3808. Nie wolno używać go jako czasu na osi sesji. |
| `events.elapsed_ms` | Czas emisji zdarzenia względem początku sesji, liczony monotonicznie przez `MetricsCollector.recordEvent()`. Nie zawsze oznacza czas czynności opisanej nazwą zdarzenia. |

Szczególnie `mz_attempt` i `mz_result` są emitowane obok siebie w `MainActivity.java` około linii 9585–9615 podczas obsługi gotowej `PlateObservation`. Nie wyznaczają początku i końca backendu MZ. Przykładowa para ma identyczne `elapsed_ms=4870` mimo rzeczywistego niezerowego czasu MZ.

Archiwum deklaruje `camera_timestamp_source=UNKNOWN`. Nie konwertowano znaczników `CAMERAX_SENSOR` na `elapsedRealtimeNanos` poprzez zgadywanie offsetu. Powiązania korzystają z jawnych identyfikatorów, pełnych stampów i generacji.

## 4. Mapowanie K02

Początek sesji: `2026-11-09T22:57:33.818Z`, `started_elapsed_nanos=2114890421355780`.

Koniec/deadline: `2115190421355780`, czyli 300,000 s. Obserwacja zatrzymania nastąpiła 1,518 ms później. Koniec ostatniego przedziału w tabeli pochodzi z zapisanego końca/deadline, nie z czasu zapisania archiwum.

Poniżej są **przedziały zdarzeń**, nie potwierdzone okresy stabilności i nie udowodnione tożsamości fotografii TV. Pierwszy zaczyna `SESSION_START`, pozostałe — 9 wykrytych `SCENE_BOUNDARY`. Nie założono 10 zmian: źródło ma 9 zmian i start sesji.

| Sufiks `scene_event_id` | Początek–koniec [s] | Generacja | `source_sequence` klatki SCENE_FRAME | MP wykonane | MT wywołania | MZ wykonane | RAW / FINAL / nierozstrzygnięte role |
|---|---:|---:|---:|---:|---:|---:|---|
| s00000001 | 0,000–29,871 | 63 | 35517 | 1 | 2 | 2 | 2 / 2 / 0 |
| s00000002 | 29,871–60,420 | 64 | 36200 | 1 | 8 | 14 | 16 / 14 / 2 |
| s00000003 | 60,420–89,752 | 65 | 36806 | 1 | 1 | 1 | 1 / 1 / 0 |
| s00000004 | 89,752–120,068 | 66 | 37451 | 1 | 0 | 0 | 0 / 0 / 0 |
| s00000005 | 120,068–150,518 | 67 | 38144 | 1 | 0 | 0 | 0 / 0 / 0 |
| s00000006 | 150,518–179,910 | 68 | 38703 | 1 | 10 | 9 | 11 / 9 / 1 |
| s00000007 | 179,910–209,802 | 69 | 39240 | 1 | 1 | 1 | 1 / 1 / 0 |
| s00000008 | 209,802–239,917 | 70 | 39919 | 1 | 11 | 10 | 11 / 10 / 1 |
| s00000009 | 239,917–269,851 | 71 | 40514 | 1 | 5 | 10 | 10 / 10 / 0 |
| s00000010 | 269,851–300,000 | 72 | 41119 | 1 | 6 | 4 | 6 / 6 / 0 |
| **Suma** | | | | **10** | **44** | **51** | **58 / 53 / 4** |

Dodatkowo jest **1 SUPPRESSED**, w s00000006. Dlatego 58 RAW = 53 FINAL + 1 SUPPRESSED + 4 UNRESOLVED. Nie są to liczby fizycznych tablic GT ani zapisanych decyzji operatora.

Każda klatka SCENE_FRAME ma `WRITTEN`, SHA i ścieżkę:

```text
samples/frames/scene-exp-1794265037188-43dc06b8-s000000NN.jpg
```

Dokładne źródła i SHA dla NN=01…10 są w dołączonym JSON. MP ma zapisany `trace_frame_id`, np. kolejno: 2353, 2358, 2367, 2369, 2371, 2874, 2885, 2887, 2899, 2906. Pozostałe 44 obserwacje MP mają `NOT_RUN`/wykorzystanie cache; nie doliczono ich jako inferencji MP.

### Podstawa powiązań

- Scena → MT: zgodność `scene_evidence.mt_invocation_ids` z `mt_detection_roles.scene_event_id` i `mt_invocation_id`.
- MT → wejście: pełny sześciopolowy `source_stamp`, `trace_frame_id`, wpis pełnej klatki i ROI.
- MT → rekordy detekcji: `attempts.mt_invocation_id` i zgodność stampów; zbiory odpowiadają `raw_attempt_ids`.
- Detekcja → MZ: `mz_executed=true`, `attempt_id`, odpowiadający crop i jego `timing.frame_id`; sprawdzono też zgodność zapisanej predykcji.
- Czternaście rekordów potomnych nie ma własnego `f5a_scene_event_id`. Mają jednak jawne powiązanie z wywołaniem MT i zgodny pełny stamp. Użyto tej ścieżki dowodowej, nie kolejności rekordów.

**Nieprzypisane do zdarzeń sceny:** 0 spośród 44 MT, 58 rekordów prób i 51 zapisanych wykonań MZ. Nie oznacza to potwierdzenia stabilności ani kompletności ich oceny.

**Niepełne role:** trzy wywołania `a00000017`, `a00000030`, `a00000042`, łącznie cztery nierozstrzygnięte rekordy. Ich związek ze wcześniejszą sceną jest znany, a wynik po postprocessingu pozostaje niepełny/N/A. Nie wolno usuwać ich ani uznawać automatycznie za FINAL.

### Wyniki kończące się po zmianie

| MT, ślad | Źródłowa scena | Początek przetwarzania [s] | Następna granica [s] | Wyprowadzona dolna granica zakończenia śladu [s] |
|---|---|---:|---:|---:|
| a00000017, 2366 | s00000002 | 59,312 | 60,420 | 60,620 |
| a00000030, 2884 | s00000006 | 178,625 | 179,910 | 179,929 |
| a00000042, 2898 | s00000008 | 238,762 | 239,917 | 240,178 |

Ostatnia kolumna jest wyliczeniem `trace.elapsed_realtime_ns + stage_ms.total`, nie niezależnie zapisanym timestampem końca backendu. `total` jest rozpoczynane po utworzeniu śladu, więc wyliczenie jest dolną granicą jego końca. W trzech śladach nie ma `result_available_nanos`; źródło podaje `scene_superseded`. **Nie przeniesiono żadnego z tych wywołań do następnej sceny.**

## 5. Dlaczego „Scena 03” i „Obraz 03” nie oznaczają tego samego

Obecna lista ma 10 SCENE_FRAME i 10 grup podmiotów (`subjects`). Grupa podmiotu pochodzi z identyfikatora generacji oraz entity/track, a nie z numeru fotografii TV.

Odczyt istniejącego modelu wskazał następujące przypisania grup w kolejności źródłowej:

| Pozycja grupy „Obraz” | Końcówka `subject_key` | Powiązane zdarzenie |
|---:|---|---|
| 01 | sg-63/entity-112 | s00000001 |
| 02 | sg-64/entity-113 | s00000002 |
| 03 | sg-64/entity-116 | s00000002 |
| 04 | sg-65/entity-120 | s00000003 |
| 05 | sg-68/entity-121 | s00000006 |
| 06 | sg-69/entity-124 | s00000007 |
| 07 | sg-70/entity-125 | s00000008 |
| 08 | sg-71/entity-129 | s00000009 |
| 09 | sg-71/entity-130 | s00000009 |
| 10 | sg-72/track-10 | s00000010 |

Przypisania dotyczą danych modelu, nie potwierdzenia aktualnego układu przez operatora. Jedno MT zawierające wiele detekcji może należeć do kilku grup podmiotów. Sumowanie liczników tych grup dałoby duplikaty wywołań; w audycie policzono 44 unikalne `mt_invocation_id`.

`gui/mobile_canvas_editor.py`, `refresh_tree()`, buduje grupy „Obraz”; `gui/mobile_canvas_scene_frames.py`, `add_rows()`, dodaje SCENE_FRAME. Przenosi MT pod SCENE_FRAME tylko przy **identycznym pełnym `source_stamp`**.

W K02 **0 z 44 stampów wejścia MT jest identyczne ze stampem reprezentującego SCENE_FRAME**. Związek z tą samą generacją zdarzenia jest potwierdzony, lecz są to inne klatki CameraX. Nie wolno potraktować ich jako tej samej geometrii, przenieść polygonów GT ani osłabić `source_binding`. Ewentualny przyszły kontener nawigacyjny musiałby zachować tę różnicę.

Brak MT w s00000004 i s00000005 nie oznacza `NO_PLATES`. Obie pełne sceny nadal wymagają świadomej decyzji operatora.

## 6. Czego brakuje do etapu B

Brakuje źródłowego dowodu przejścia do stanu stabilnego, powiązanego co najmniej z:

1. `session_id` i właściwym zdarzeniem/generacją sceny;
2. `source_stamp` klatki, na której potwierdzono stabilność;
3. monotonicznym czasem potwierdzenia z określoną domeną;
4. jednoznaczną semantyką kryterium stabilności i stanem braku/niepewności tego dowodu.

Obecny kontrakt `alpr.scene_evidence.v1` nie dostarcza tych danych. Nie można ich odzyskać przez ponowny import, założenie 30 s na fotografię, dopasowanie numerów, uznanie pierwszego MP/MT za początek stabilności albo wykorzystanie późnego wyniku.

Ewentualne dodanie takich dowodów producenta wymagałoby osobnego, wersjonowanego kontraktu i zgodnego odczytu. **Nie wykonano tej zmiany w Androidzie ani importerze.** Dla istniejących archiwów stabilność pozostaje N/A. Alternatywne grupowanie jedynie według wykrytych granic byłoby innym zakresem niż wymagany blok stabilnej sceny; nie wdrożono go pod tą nazwą.

## 7. Nawigacja, oceny i jednostki niepełne

- Nie zmieniono żadnego pliku aplikacji ani testu repozytorium. Dodano wyłącznie ten raport i JSON audytu.
- Pozostała dotychczasowa organizacja „Scena/Obraz/MT”; sceny dynamiczne zachowują dotychczasowy zakres.
- Nie tworzono drugiego Canvas, nie zmieniano GT, liczników naukowych, TP/FP/FN, IoU, CER, FINAL ani N/A.
- Wszystkie niepełne i anulowane dowody pozostały na miejscu. Nie dodano jeszcze sekcji „Dowody nieprzypisane / niepełne”, ponieważ etap B został zatrzymany.
- Ocena pełnej sceny nie została utożsamiona z ukończeniem wszystkich jej MT/ROI.
- Nie przenoszono GT zdjęć źródłowych na CameraX i nie wyznaczano liczby fizycznych tablic na podstawie detekcji.

## 8. Walidacja i ograniczenia

**Audyt K02: PASS w zakresie integralności i jawnych powiązań; brak podstaw do stabilnych bloków.** Sprawdzono unikalność identyfikatorów, zgodność powiązań scen/MT, sześciopolowych stampów, śladów MP, prób MZ i cropów oraz zachowanie źródłowego przypisania anulowanych wywołań.

Istniejące regresje: **122 PASS / 0 FAIL / 0 SKIP**, 33,67 s:

- `tests/test_f5a12c_scene_evidence.py`;
- `tests/test_f5a12c_scene_tk.py`;
- `tests/test_mobile_operator_progress.py`;
- `tests/test_mobile_mt_blind_review.py`.

Testy zapisujące działały wyłącznie na prywatnych fixture, z osobnym Workspace/profilem i katalogiem tymczasowym. K02 czytano bez zapisu. Nie uruchamiano modeli ani fizycznego eksperymentu.

Testy **nowego grupowania** z etapu D — w tym przełączanie bloków, brak stabilizacji, niejednoznaczny timestamp, powtórzone/brakujące sceny oraz zapis/wznowienie nowej listy — **NOT_RUN**, ponieważ nie powstała implementacja. Nie deklaruje się ich zaliczenia ani pełnej regresji całego repozytorium.

Kontrola bezpieczeństwa:

- archiwum K02, magazyn i 44 pliki ocen: niezmienione SHA, rozmiary i mtime;
- wcześniejsze pliki worktree i pełny diff tracked: identyczne z początkiem audytu;
- preferencje `C:\Users\48572\.auto_annotation_tool\session.json`: identyczne bajty/SHA i rozmiar, lecz zmienił się mtime w trakcie audytu. Nie ustalano przyczyny i nie przywracano pliku; nie jest to zmiana treści ocen;
- HEAD pozostał `70f980d1a33b230626f4e9375a7049f9164342fd`; bez reset/checkout/clean/commit/push.

## 9. Odbiór

Odbiór nowego GUI: **nie dotyczy — nie wdrożono zmiany nawigacji**. Nie zadeklarowano odbioru operatora.

Można otworzyć istniejący raport K02 w Z4, bez ponownego importu, i porównać jego jednostki z tabelą mapowania. Lista powinna zachować wcześniejszą postać. Nie należy oznaczać produkcyjnych scen ani zapisywać próbnych zmian w ramach odbioru tego audytu.

Priorytet kolejnego kroku: uzyskać brakujący dowód stabilności albo jawnie zmienić wymaganie na grupowanie według samych granic zdarzeń, z zachowaniem nieustalonej stabilności. W tym zadaniu nie wybrano takiej zmiany za operatora.

## 10. Dowody lokalne

Katalog roboczy: `C:\Users\48572\AppData\Local\Temp\z4_stable_scene_81292v56`.

Trwała kopia dowodów: `C:\Users\48572\Desktop\ALPR_BACKUPS\Z4_K02_STABILNE_SCENY_20261110_81292v56`.

Zawiera `audit_k02.py` (zewnętrzny skrypt audytu, nie moduł aplikacji), `source.json`, odczytane wpisy tekstowe w `entries/`, `k02_mapping.json`, `stability_search.json`, `regression.xml`, log regresji, polecenie testowe oraz inwentarze ochrony przed/po. Nie skopiowano fotografii jako nowego datasetu i nie utworzono produkcyjnego runu.
