# Audyt zbiorczy — sceny negatywne i decyzje GT w Z2/Z4

Data: **2026-11-10** (Europe/Warsaw)  
Repozytorium: `C:\Users\48572\Desktop\dyplom\start4`  
System: Windows 10  
Bazowy HEAD: `70f980d1a33b230626f4e9375a7049f9164342fd`  
Zakres: odczyt lokalnego kodu, kontraktów i istniejących testów; rekomendacja integracji.  
Status: **AUDYT KODU ZAKOŃCZONY; INTEGRACJA I ODBIÓR GUI NIEZATWIERDZONE**.

## 1. Wniosek i granice audytu

Najbliższym istniejącym mechanizmem dla ręcznej anotacji fotografii Z2 jest
**obsługa pełnej sceny Z4 w `mobile_scene_frame_review.py`**. Obsługuje świadomy
brak tablic, obecność tablicy bez ustalonej geometrii, przyczynę wyłączenia
tekstu, zapis decyzji i cofanie/ponawianie zmian.

Należy współdzielić znaczenie decyzji i logikę niezależną od źródła, zachowując
osobne adaptery tożsamości i zapisu Z2/Z4. Nie należy podłączać fotografii Z2
do `MobileReviewSession` przez fikcyjne archiwum Androida, identyfikator MT,
ROI albo `source_stamp` CameraX.

Audyt wykonano po wstrzymaniu wcześniejszej implementacji jawnych decyzji Z2.
W worktree pozostał jej lokalny szkic. Raport odróżnia:

1. Istniejącą obsługę Z4, odczytaną z aktualnego lokalnego kodu wraz z wcześniej
   istniejącymi zmianami użytkownika.
2. Kontrakty Z2/XML/GT Pack sprzed rozpoczęcia tego szkicu, sprawdzone również
   w bazowym kodzie Git i wcześniejszym stanie lokalnym.
3. Nowy, nieodebrany szkic Z2, który nie jest dowodem wcześniejszej obsługi
   tych decyzji ani zakończonej integracji ze Z4.

W ramach audytu nie implementowano funkcji, nie oznaczano fotografii, nie
zmieniano runu F5A i nie wykonywano commit/push. Utworzenie niniejszego pliku
jest wyłącznie zapisem raportu na późniejsze żądanie użytkownika.

## 2. Istniejące decyzje operatora w Z4

| Poziom oceny | Reprezentacja | Znaczenie |
|---|---|---|
| Pełna scena | `presence: UNRESOLVED / PRESENT / NO_PLATES`, `checked` | Ocena obecności tablic na całym udokumentowanym obrazie |
| Analizowany ROI | `roi_presence: NO_PLATES` | Decyzja o konkretnym obszarze wejściowym MT, nie automatycznie o całej fotografii |
| Wskazanie MT FINAL | `PLATE / NOT_PLATE / UNRESOLVED` | Decyzja o pojedynczym wyniku modelu |
| Starszy formularz wejścia MT | `visible_plate_count: none / one / multiple / uncertain` | Jawna ocena liczby tablic na wejściu konkretnego wywołania |
| Niepewna widoczność wskazania | `plate_visibility="uncertain"`, `is_plate=None`, `evaluable=False` | Brak rozstrzygnięcia; nie TP, FP ani negatywna scena |
| Tekst nieocenialny | `gt_text=""`, niepuste `text_exclusion_reason`, `text_confirmed=True` | Jawnie zapisany powód braku ocenialnego tekstu |
| Geometria nieocenialna pełnej sceny | `quad=None`, `geometry_state="unavailable"`, `geometry_exclusion_reason` | Obecność tablicy bez wymyślania narożników |

### Pełna scena

[mobile_scene_frame_review.py](../auto_annotation_tool/ranking/mobile_scene_frame_review.py):

- `_seed()` — tworzy stan `presence="UNRESOLVED"`, `checked=False`.
- `_validate()` — sprawdza tożsamość źródła i spójność decyzji; `NO_PLATES`
  nie może współistnieć z aktywnymi tablicami.
- `confirm_empty()` — świadomie potwierdza `NO_PLATES`; odmawia, jeśli
  pozostały oznaczone tablice.
- `remove()` — usunięcie ostatniej tablicy przywraca `UNRESOLVED`, nie
  `NO_PLATES`.
- `add_plate(points=None, geometry_reason=...)` — zapisuje fizyczną tablicę
  bez polygonu; wymaga przyczyny braku geometrii.
- `edit(text="", reason=...)` — zapisuje przyczynę braku ocenialnego tekstu.
  Nie dopuszcza jednocześnie niepustego tekstu i przyczyny wyłączenia.
- `store()` i `restore(redo=False/True)` — zapis, historia oraz undo/redo.

GUI: klasa `CanvasReviewEditor`, metoda `confirm_empty_image()` w
[mobile_canvas_editor.py](../auto_annotation_tool/gui/mobile_canvas_editor.py).
Etykiety i akcje pełnej sceny dostarcza
[mobile_canvas_scene_frames.py](../auto_annotation_tool/gui/mobile_canvas_scene_frames.py),
w szczególności `sync_empty_action()` i `show_presence_only()`.

### ROI i wskazania modelu

[mobile_canvas_resolution.py](../auto_annotation_tool/ranking/mobile_canvas_resolution.py)
zawiera `confirm_no_plates()`, `mark_identity_unresolved()` oraz walidację
powiązania decyzji ze źródłowym MT. Dla nowszego zapisu stosów kandydatów
potwierdzenie negatywnego ROI przechodzi przez `confirm_negative()` w
[mobile_candidate_stacks.py](../auto_annotation_tool/ranking/mobile_candidate_stacks.py).
Powiązania końcowych wskazań otrzymują m.in. `UNASSOCIATED_NO_PLATE`.

[mobile_canvas_partial_review.py](../auto_annotation_tool/ranking/mobile_canvas_partial_review.py)
przechowuje `PLATE`, `NOT_PLATE`, `UNRESOLVED`, `previous_decisions` oraz
`empty_confirmed`. Odrzucone przez NMS kandydaty RAW pozostają dowodem
diagnostycznym; nie stają się przez to osobnymi FP modelu FINAL.

W starszym formularzu `MobileSampleReviewWindow` z
[z4_mobile_sample_review.py](../auto_annotation_tool/gui/z4_mobile_sample_review.py)
wywołuje `MobileReviewSession.annotate_invocation()`. Mapowanie wyborów
„Nie tablica”, „Niedokładny obrys”, „Dobry obrys”, „Nie można ustalić” znajduje się
w `visual_decision()` i `selected_visual_state()` w
[mobile_verification_policy.py](../auto_annotation_tool/ranking/mobile_verification_policy.py).

### Brak pojazdów

Nie znaleziono osobnej, analogicznej decyzji operatora Z4 `NO_VEHICLES`.
Puste `selected_rois` w obserwacji MP jest wynikiem działania modelu, a nie
potwierdzeniem braku pojazdów lub tablic w GT.

`AnnotationStatus.NO_VEHICLE` istnieje w
[data_models.py](../auto_annotation_tool/data_models.py) i jest ustawiany przez
anotatory Desktop. Nie stanowi odpowiednika jawnej decyzji pełnej sceny Z4.

## 3. Schematy i miejsce zapisu

Główny kontener to klasa `MobileHumanReview`, obsługiwana przez
`MobileReviewSession` w
[mobile_human_review.py](../auto_annotation_tool/ranking/mobile_human_review.py).

Domyślna ścieżka sidecara:

```text
Workspace\7_rankings\mobile_packages\human_reviews\<SHA-256 archiwum>.review.json
```

SHA w nazwie identyfikuje **archiwum mobilne**, nie pojedynczą fotografię.
Ścieżkę bazową definiuje `CONFIG.DIR_7_RANKINGS_MOBILE_PACKAGES` w
[config.py](../auto_annotation_tool/config.py).

| Schemat / pole | Zawartość |
|---|---|
| `alpr.mobile_human_review.v1` | Kontener review: źródło, sesja, rewizja, tryb, decyzje |
| `scene_annotations[scene_event_id]` | Pełne sceny; `alpr.mobile.scene_frame_review.v1` |
| `invocation_annotations[mt_invocation_id].canvas_review_v1` | Canvas ROI; `alpr.mobile.canvas_review.v1` |
| `operator_frame_decisions_v1` | Decyzje operatora o wskazaniach; `alpr.mobile.operator_frame_decisions.v1` |
| `candidate_stacks_v1` | Referencje i powiązania kandydatów; `alpr.mobile.candidate_stacks.v1` |
| `attempt_annotations`, `sample_annotations` | Decyzje dotyczące prób i próbek |
| `subjects` | Tekst GT, ocenialność i uwagi dla podmiotów |
| `scene_history_v1` | Stany pełnej sceny i kursor undo/redo |
| `events` | Akcja, czas, obiekt, rewizja przed zmianą, dane przed/po zmianie |

Odrzucenie wskazania MT jest oddzielone od usunięcia lub wycofania ręcznej
referencji GTR. `mobile_canvas_review.toggle_error()` wymaga źródłowego
MT FINAL. Mechanizm wycofania referencji ma także własny audyt:
[mobile_reference_disposition.py](../auto_annotation_tool/ranking/mobile_reference_disposition.py),
schemat `alpr.mobile.reference_dispositions.v1`.

## 4. Trwałość, ponowne otwarcie i metryki

### Zapis i odczyt

`MobileReviewSession._save_change()` / `_save_change_locked()`:

1. Sprawdzają SHA źródła oraz identyfikatory i powiązania decyzji.
2. Zakładają krótką wyłączną blokadę zapisu sidecara.
3. Wykrywają nowszą rewizję zapisaną przez inne okno.
4. Zwiększają `review_revision` i aktualizują czas.
5. Zapisują atomowo przez plik tymczasowy, `fsync()` i `os.replace()`.

Ponowne otwarcie wczytuje sidecar przez `MobileHumanReview.from_dict()`,
sprawdza schemat, SHA i identyfikator sesji oraz waliduje decyzje. Odczyt nie
tworzy sidecara. Źródłowe archiwum i obrazy nie są miejscem zapisu review.

Zatwierdzenie `complete()` może utworzyć niezmienny snapshot
`ready_for_evaluation/.../manifest.json`, powiązany z SHA i rewizją.
Implementacja: [mobile_verification_snapshot.py](../auto_annotation_tool/ranking/mobile_verification_snapshot.py),
schemat `alpr.desktop.review_ready_manifest.v1`.

### Znaczenie wyników

**Ocena obecności, kompletność formularza i ocenialność metryki są odrębne.**

- Obecna polityka ROI: zero FINAL i zero referencji daje
  `NO_REFERENCE_EVIDENCE`, `metric_complete=False` oraz N/A dla wyników
  detekcyjnych. Nie daje automatycznie TN ani pełnego recall.
- `NO_PLATES` na pełnej scenie jest decyzją GT o obecności. Nie dowodzi
  wykonania MT i nie wytwarza brakującego wywołania.
- Pełna scena z tablicą przy zerze ROI może dać `OUTSIDE_ROI`; nie jest
  automatycznie FN nieuruchomionego MT.
- Brak dowodu źródła, niewykonane MT i nieustalona rola FINAL pozostają N/A.
- Tekst z przyczyną wyłączenia nie dostarcza fikcyjnych znaków do CER.
- Brak ocenialnych narożników pozostawia IoU/NMCE jako N/A; BBOX nie jest
  zastępczym dowodem źródłowego Pose.

Kluczowe pliki:

| Plik i funkcja | Rola |
|---|---|
| [mobile_frame_review_state.py](../auto_annotation_tool/ranking/mobile_frame_review_state.py): `from_scene()`, `for_session()`, `ELIGIBILITY` | Bieżąca kwalifikacja operacyjna i metryczna; jawne `zero_final_zero_gt=NO_REFERENCE_EVIDENCE` |
| [mobile_scene_frame_review.py](../auto_annotation_tool/ranking/mobile_scene_frame_review.py): `progress()`, `coverage()`, `summary()` | Ocena pełnej sceny i pokrycia ROI, bez fabrykowania MT/FN |
| [mobile_mt_detection_evaluation.py](../auto_annotation_tool/ranking/mobile_mt_detection_evaluation.py): `score_unit()` | Bramki źródła, wykonania, decyzji i polityki dopasowania |
| [mobile_canvas_review.py](../auto_annotation_tool/ranking/mobile_canvas_review.py): `counts()`, `summary()` | Oddzielne zliczanie referencji, FINAL, błędów i kandydatów RAW |
| [mobile_mt_invocations.py](../auto_annotation_tool/ranking/mobile_mt_invocations.py): `calculate_mt_invocations()` | Starsze miary wywołań; Canvas ma odrębny zakres i mianowniki |

W starszych gałęziach podsumowania i testach istnieją liczniki TN. Nie wolno
przenosić ich do Z2 bez uwzględnienia nowszego predykatu kwalifikacji.
Aktualny scenariusz `test_C01_empty_is_NO_REFERENCE_not_TN_or_full_recall`
w [test_z4_auto_frame_completion.py](../tests/test_z4_auto_frame_completion.py)
opisuje właśnie wynik N/A. Jest to ustalenie z odczytu kodu i testów, nie
deklaracja wyniku ich ponownego uruchomienia podczas audytu.

Z4 pełnej sceny używa `ASSISTED_SCENE_FRAME`, `independent_gt=False`.
Manifest gotowości ma `geometry_gt_required_for_readiness=False`.
Nie należy przenosić tych flag ani samego `checked` jako dowodu pełnego,
niezależnego GT F5A w Z2.

## 5. Z2, annotations.xml i GT Pack

### Kontrakt sprzed rozpoczętego szkicu jawnych decyzji

| Cecha | Istniejący mechanizm Z4 | Dotychczasowy kontrakt Z2 |
|---|---|---|
| Tożsamość | SHA archiwum, sesja, scena/wywołanie, `source_stamp`, `source_binding` | Ścieżka względna, SHA fotografii, `img-sha256-<SHA>` |
| Negatywna scena | Jawne `NO_PLATES` | Pusty obraz XML bez rozróżnienia nieoceniony/negatywny |
| Nieczytelny tekst | Przyczyna wyłączenia + potwierdzenie | Wartość tekstu albo jej brak |
| Nieustalona geometria | Pełna scena: `quad=None` + powód | Brak kompletnego analogicznego toru operatora |
| Trwałość | Sidecar, rewizje, historia, snapshot gotowości | XML, manifest runu, GT Pack, autosave |
| Przeznaczenie | Weryfikacja dowodów mobilnych, ocena asystowana | Ręczna anotacja fotografii, potencjalnie niezależne GT |

`NO_PLATE`, `NO_VEHICLE` i `PARTIAL_PLATE` są wartościami `AnnotationStatus`.
Ich występowanie nie oznacza, że istniała jawna decyzja operatora o negatywnym
GT albo pełny zapis częściowej geometrii. `PARTIAL_PLATE` jest używany również
przez automatyczny anotator.

Dotychczasowy [CVATExporter](../auto_annotation_tool/exporters/cvat_exporter.py)
zapisywał `<image>`, `<box>` i `<polygon>`. Pusty `<image>` zachowywał fotografię
w runie, ale nie jej świadomą ocenę negatywną. `_add_polygon()` zawierał
fallback BBOX → polygon; nie jest to wystarczający kontrakt dla nieustalonego
GT Pose.

GT Pack posiada istniejące schematy:

```text
alpr.gt.pack.v1
alpr.gt.image.v1
alpr.gt.plate.v1
alpr.gt.geometry.v1
alpr.gt.revision.v1
alpr.gt.layout-revision.v1
alpr.gt.conflict.v1
```

W [gt_pack.py](../auto_annotation_tool/gt_pack.py) tekst był wersjonowany
operacjami `set` i `clear`, a standardowy polygon wymagał co najmniej
czterech punktów. **`clear` nie oznacza `UNREADABLE`; pusty `plate_ids`
nie oznacza `NO_PLATES`.** Dokumentacja formatu:
[alpr_gt_pack_v1.md](alpr_gt_pack_v1.md).

Istniejące punkty integracji Z2:

- `CVATExporter._add_image()` / `_add_polygon()` — zapis XML.
- `z2_preview_workflow._parse_cvat_preview_annotations()` — odczyt i wznowienie.
- `z2_preview_workflow._save_preview_edits()` — Ctrl+S.
- `z2_preview_autosave.update_saved_images()` / `start_preview_autosave()` — autosave.
- `z2_preview_state._clone_preview_history_annotation()` i
  `_restore_preview_annotation_history_snapshot()` — cofanie zmian.
- `z2_manifest_runtime._write_annotation_run_manifest()` — tożsamość źródeł runu.
- `z2_gt_pack_runtime` — istniejąca synchronizacja XML → GT Pack i kolejka ponowień.

### Nowy lokalny szkic — oddzielony od historycznej obsługi

Przed poleceniem audytu rozpoczęto implementację m.in. w:

- [gt_review.py](../auto_annotation_tool/gt_review.py),
- [gt_pack_review.py](../auto_annotation_tool/gt_pack_review.py),
- [z2_explicit_gt_runtime.py](../auto_annotation_tool/gui/z2_explicit_gt_runtime.py),
- [z2_explicit_gt_ui.py](../auto_annotation_tool/gui/z2_explicit_gt_ui.py).

Szkic wprowadza `alpr.gt.review.v1`, metadane XML `alpr_gt_review_v1`
i `alpr_gt_plate_evidence_v1` oraz `review_revisions_v1` w GT Pack.
To **nowe, lokalne zmiany z poprzedniego polecenia**, a nie istniejący od dawna
mechanizm Z4. Nie uznano ich za odebraną integrację ani nie zmieniono ich
w ramach niniejszego audytu. Nie rekomenduje się dalszego rozwijania osobnego
modelu decyzji przed uzgodnieniem wspólnego kontraktu z mechanizmem pełnej sceny.

## 6. Rekomendowana minimalna integracja

Poniżej znajduje się rekomendacja, nie opis wykonanych zmian.

1. **Wspólne znaczenie decyzji.** Przyjąć istniejące
   `UNRESOLVED/PRESENT/NO_PLATES`, obecność tablicy, potwierdzenie geometrii,
   opcjonalny polygon z powodem braku oraz tekst lub powód wyłączenia.
   `UNREADABLE` może być jawnym kodem przyczyny wyłączenia tekstu; nie może być
   fikcyjną wartością numeru rejestracyjnego.

2. **Wydzielenie logiki niezależnej od Androida.** Z
   `mobile_scene_frame_review` wydzielić inicjalizację stanu, walidację decyzji,
   przejścia stanów i historię. Obecny adapter Z4 zachowuje wszystkie kontrole
   archiwum, sceny, `source_stamp` i MT. Nie kopiować całego mobilnego session
   runtime do Z2.

3. **Adapter tożsamości Z2.** Użyć istniejącego runu i jego
   `relative_path`, `source_file_sha256`, `img-sha256-<SHA>`. Nie dodawać
   fikcyjnych prób, wywołań MT, ROI ani danych CameraX. Zachować trwały
   identyfikator tablicy przy zmianie jej geometrii lub tekstu.

4. **Istniejący zapis Z2.** Wspólne decyzje utrwalać przez XML, autosave,
   Ctrl+S i GT Pack. Konieczne jest wersjonowane rozszerzenie metadanych,
   ponieważ same polygony i `set/clear` nie niosą wszystkich znaczeń.
   Nie tworzyć dodatkowego sidecara Z2 w `human_reviews` ani konkurencyjnego
   magazynu GT. Istniejącą kolejkę synchronizacji traktować jako kolejkę
   techniczną, nie drugie źródło prawdy.

5. **Osobna kompletność GT.** Rozdzielić ocenę obecności, kompletność tekstu
   i geometrii oraz ocenialność konkretnej metryki. Nie przejmować bez zmian
   `checked`/`READY_FOR_EVALUATION` z Z4. Nie wiązać ocenienia fotografii
   negatywnej z progiem 10 tablic dla treningowego datasetu YOLO Pose.

6. **GUI jako adapter decyzji.** W Z2 użyć polskich akcji „Brak tablic”,
   „Cofnij ocenę”, „Tekst nieczytelny”, „Geometria nieustalona/częściowa”.
   Nieocenione obrazy pokazywać osobno od błędnych anotacji. Odrzucenie
   detekcji modelu nie może zastępować decyzji o braku tablic w całej fotografii.

7. **Bez przebudowy metryk.** Zachować obecne metryki R0/R1/R2 i adapter
   CameraX. W przyszłym powiązaniu GT z wynikami oddzielić brak danych (`N/A`)
   od zera oraz od potwierdzonego negatywnego GT.

Minimalny zakres przyszłych zmian obejmuje więc wspólną logikę decyzji,
adapter Z2, transport metadanych XML/GT Pack i prezentację w Z2. Zmiana
mobilnego magazynu raportów, archiwów Androida, APK albo danych eksperymentu
nie jest do tego potrzebna.

## 7. Walidacja i ograniczenia

W ramach audytu nie uruchamiano nowych testów zapisujących decyzje ani
eksportujących raporty. Odczytano istniejące scenariusze, m.in.:

| Testy | Sprawdzany kontrakt |
|---|---|
| [test_f5a12c_scene_evidence.py](../tests/test_f5a12c_scene_evidence.py): T20 | Tablica przy zerze ROI: `OUTSIDE_ROI`, bez automatycznego MT FN |
| Ten sam plik: T21 | Obecność bez geometrii; brak fikcyjnych narożników i tekstu |
| Ten sam plik: T22 | Jawne zero tablic, rewizja zapisu, undo/redo |
| Ten sam plik: roundtrip T19 | Źródło, identyfikacja sceny, historia i eksport |
| [test_z4_auto_frame_completion.py](../tests/test_z4_auto_frame_completion.py): C01–C04 | N/A dla braku referencji, niewykonanego MT lub nieudowodnionego źródła |
| [test_mobile_human_review.py](../tests/test_mobile_human_review.py) | Widoczność, niepewność, odrzucenie wskazania i trwałość review |

Odczyt testu nie jest jego wykonaniem. Raport nie deklaruje nowego pełnego
PASS Z4 ani wizualnej akceptacji GUI.

Przed ewentualną integracją potrzebne są syntetyczne testy: brak decyzji,
świadome zero, wiele tablic, nieczytelny tekst, brak/część geometrii, cofanie,
autosave, Ctrl+S, wznowienie tego samego runu, XML/GT Pack oraz zgodność
historycznych zapisów. Należy również sprawdzić brak nadpisania decyzji
przez starsze źródło GT i rozbieżną rewizję w drugim oknie.

## 8. Integralność F5A i stan końcowy

Istniejący run:

```text
C:\Users\48572\Desktop\dyplom\start4\Workspace\2_auto_annotations\plates\run_001_20261110_093800
```

Podczas odczytu ustalono: 40 obrazów w XML, bez polygonów. Nie oznaczano ich
jako negatywne i nie uruchamiano modeli. Rekurencyjny odczyt oraz tożsamość
źródeł były wcześniejszym, osobnym etapem pracy.

Ponowna kontrola przy przygotowaniu tego raportu potwierdziła **47/47
niezmienionych SHA** chronionych plików, obejmujących run, 40 fotografii
i pliki Sortowni. W audycie sprawdzono również zachowanie 12 wcześniej
zmodyfikowanych plików mobilnych objętych kontrolną listą — bez zmian.

SHA-256 plików istniejącego runu:

| Plik | SHA-256 |
|---|---|
| `annotations.xml` | `680d3a1e379e9b085dc40046d70de8c9a756bea955e35535b546b4cd9ad46bcc` |
| `run_manifest.json` | `a17fbe42e63faa5fcab2fd644e8ff30a23cf3f173458f52e6d4f788b094bec68` |
| `report.txt` | `78f0d2d26645d0842e3f36e29e9ac33f9f0eeb5df4b2854a327acd012f69ec8d` |

Wcześniejsze dokumenty dotyczące samej rekurencji, do których ten audyt
nie dopisuje odbioru jawnych decyzji GT:

- [Odbiór rekurencyjnego wejścia Z2](Z2_REKURENCYJNE_OBRAZY_ODBIOR_2026-11-10.md).
- [Audyt SHA źródeł F5A](Z2_REKURENCYJNE_F5A_AUDYT_2026-11-10.json).

**Stan końcowy:** raport audytu i rekomendacja minimalnej integracji są
gotowe. Implementacja integracji pozostaje wstrzymana. Produkcyjne GT F5A
i odbiór wizualny wymagają odrębnej pracy oraz rzeczywistego potwierdzenia
operatora; niniejszy dokument ich nie zatwierdza.
