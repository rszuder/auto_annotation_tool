# Faza 2A — wejście MT, EXIF i odbiór geometrii EVAL396

Data: 2026-10-09. Baza kodu: `f5547e4`, `funkcja/az-crop-registry`; HEAD i lokalny ref upstream zgodne (0/0). Zachowano wcześniejsze zmiany robocze. Bez commit/push.

**Dostarczono implementację 2A. Odbiór geometrii pozostaje zablokowany: FAIL/STOP dla jednej tablicy z odwrotną kolejnością narożników.** Nie wykonano inferencji MT, treningu, pomiarów E2E, mobilnych ani final_test. Nie przeliczano predykcji MZ. Nie zapisano decyzji w imieniu operatora.

## 1. Potwierdzona przyczyna i naprawa EXIF

`utils.get_image_size()` (linia 94) otwiera obraz w Pillow i zwraca surowe `Image.size`. Dotychczas `PlateAnnotator.process_image()` pobierał te wymiary przed `_read_image_for_yolo()`, które dekodowało obraz w OpenCV z zastosowaniem EXIF. Ta sama rozbieżność występowała w annotatorze pojazdów i trybie łączonym.

Dla `DAY/SG621AW_001_607e39a8fd50_c9386732fc.jpg`:

| Właściwość | Potwierdzona wartość |
|---|---|
| SHA-256 pliku | `607e39a8fd50efdb8689bc461c31fb5fa271ab8f076179059f09fa4870bb959e` |
| EXIF Orientation | 6 |
| Surowe wymiary Pillow | 4032 × 3024 |
| Faktyczne piksele wejściowe OpenCV | 3024 × 4032 |
| OpenCV wobec EXIF-transpose Pillow, miniatura | MAE 1,49; p95 5,00 |
| GT | `plate_000428`, jeden bbox i cztery narożniki |

Przed poprawką `ImageAnnotation.width/height`, kontrola granic keypointów i metryki jakości mogły odnosić się do innego rozmiaru niż tablica pikseli podana modelowi. Punkt z Y pomiędzy 3024 a 4032 mógł zostać błędnie odrzucony, a poligon zastąpiony prostokątem bbox. To defekt kodu, nie dowód błędnego położenia zamrożonego GT.

Zmiana:

- `image_orientation.read_oriented_bgr()` dekoduje przez `cv2.imdecode(..., IMREAD_COLOR)`, kontroluje EXIF i wymiary; obsługuje ścieżki Unicode Windows. Nie wykonuje dodatkowego obrotu.
- `BaseAnnotator._read_image_for_yolo()` korzysta z tego dekodera. Wspólny `_model_input_size()` pobiera rozmiar z faktycznej tablicy wejściowej.
- `PlateAnnotator`, `VehicleAnnotator` i `CombinedAnnotator` przypisują wymiary dopiero po dekodowaniu, przed wywołaniem predyktora. Przy błędzie odczytu pozostaje status ERROR.
- Zachowano globalną semantykę `get_image_size()`. Starszy wariant wejścia przez ścieżkę (`True`) dostaje wymiary uwzględniające EXIF; nowy podgląd/preflight 2A używa wyłącznie jawnie zdekodowanej tablicy BGR.
- `inspect_oriented_image()` porównuje piksele z Pillow, zapisuje SHA tablicy BGR i odrzuca rozbieżność wymiarów lub obrazu. Limity miniatury: MAE ≤ 6, p95 ≤ 18, zgodne z wcześniejszą diagnostyką; nie są substytutem kontroli GT.

### Prześledzone ścieżki XY

| Ścieżka | Przestrzeń i konsekwencja |
|---|---|
| `gui/z2_preview_images.py:20` | `ImageOps.exif_transpose`, RGB: obraz zorientowany. |
| `annotators/base.py:76`, `plate_annotator.py:207` | BGR OpenCV z EXIF; bbox/keypoints wyników odnoszą się do tej tablicy. Wymiary adnotacji teraz pochodzą z jej shape. |
| `annotators/combined_annotator.py:95,356` | Scena zorientowana, ROI pojazdu lokalne; istniejący mechanizm przesuwa wynik tablicy do XY sceny. Granice ROI otrzymują właściwy rozmiar. |
| `annotators/vehicle_annotator.py:63` | Bbox w XY zorientowanej sceny; właściwe metadane rozmiaru. |
| `exporters/cvat_exporter.py:143,179` | XML serializuje `ImageAnnotation.width/height` i współrzędne bez dodatkowego obrotu. Naprawa obejmuje przyszłe eksporty, nie przepisuje istniejącego XML. |
| `character_recognition/plate_generator.py:112,342` | Odczyt OpenCV, utrwalenie `source_bbox/source_polygon` detekcji. Nie transformowano zapisanych danych. |
| `gt_pack.py:252,275` | Tożsamość uwzględnia EXIF; fingerprint pikseli stosuje transpose. Bez zmiany. |
| Zamrożone `metadata.json` | Punkty odczytane dokładnie jak zapisano, bez sortowania, rotacji i poprawiania GT. |

Starsze `_sort_corners_clockwise`, `PolygonValidator` i `PlateRectifier.order_quad_points` stosują różne sposoby porządkowania narożników. Pozostają mechanizmami dotychczasowej anotacji/rektyfikacji, a nie autorytetem do przepisywania GT lub obliczania surowego Pose AP. W 2B trzeba jawnie zweryfikować kontrakt indeksów predykcji. Test poprawki korzysta ze stubów modeli, nie z rzeczywistych checkpointów.

## 2. Rzeczywisty preflight i dodatkowa blokada GT

`ranking/mt_geometry_review.py:64` korzysta z istniejącego czytnika źródeł EVAL396: sprawdza selekcję, freeze, sześć checkpointów i historie, źródłowe inventory oraz dokładne pokrycie SHA train/eval. Nie wywołuje czytnika wyników ani inferencji MZ. Trzy checkpointy MT są różne; ich zadanie/tensory nie były ładowane i mają status `NOT_INSPECTED_PHASE2A`.

| Kontrola | Wynik |
|---|---|
| Sceny | 396: DAY 199, NIGHT 197 |
| Tablice MT | 479: DAY 235, NIGHT 244 |
| Nieczytelne dla MZ, nadal uwzględnione w MT | 30 |
| Odczyt EXIF i zgodność dekoderów | 396/396 |
| Bbox/quad w granicach zorientowanego obrazu | 479/479, tolerancja 1 px |
| Kolejność narożników zgodna z proponowanym TL/TR/BR/BL | 478/479 |
| Cała bramka geometrii | **FAIL / STOP** |

Nie zmieniono fingerprintów: selekcja `1f2db18cd073114f230ca2dd70a76ea9d1257d624dddf7ff39f51ada8e66aefe`, freeze `33add3fda705416bb88ed9b1ab71e275d2c4f36dd8f5b1bb2f2cbc59130ff77b`.

Jedyna niezgodność:

- Scena: `DAY/SG385F_SG386F_SGLM9MK_001_4688cd857aed_0b956ef8ab.jpg`, EXIF 1, 2048 × 1153.
- SHA: `4688cd857aed389ebe651ff71fde977c2dae05f5aaea36be2b4b417f9b579a14`.
- GT: `plate_000421`, `excluded_unreadable`; pozostaje w populacji MT.
- Bbox: `[1586.37, 492.07, 1616.05, 533.49]`.
- Punkty zapisane: P1 `[1586.37,503.98]`, P2 `[1601.9,533.49]`, P3 `[1616.05,520.38]`, P4 `[1600.69,492.07]`.
- `GT_CORNER_ORDER_REVERSED`: wszystkie cztery skręty mają znak przeciwny do wymaganego. Jest to wypukły czworokąt o odwrotnym obiegu, nie samoprzecięcie. Wcześniejszy test granic tego nie sprawdzał.

**Propozycja do osobnego zatwierdzenia:** ustalić wizualnie znaczenie narożników tej silnie nachylonej tablicy i zgodność z kontraktem 4-kpt modelu. Następnie przygotować wersjonowane, jawne mapowanie indeksów w lokalnym materiale ewaluacyjnym przyszłego runu, z zachowaniem źródłowych punktów, SHA i historii decyzji. Samo odwrócenie obiegu, np. `[P1,P4,P3,P2]`, nie rozstrzyga jeszcze położenia początku TL; alternatywny początek może dać `[P4,P3,P2,P1]`. Nie wybrano żadnego z tych wariantów. Obecna polityka `corner_reordering=forbidden` celowo blokuje zatwierdzenie do uzgodnienia nowej rewizji. Nie wykluczać sceny ani tablicy i nie edytować freeze.

## 3. Natywny Z4 i decyzja operatora

Istniejące `gui/z4_eval396.open_results()` zawiera dwie karty: dotychczasowe MZ oraz **MT — lokalizacja i geometria**. Otwarcie dla zadania `plate` wybiera MT. Karta MZ ładuje zapisane wyniki dopiero po jej wybraniu; istniejąca akcja eksportu przełącza na MZ. Zachowano objaśnienia modeli, CER w procentach, osie, małą tabelę, postęp i kontrolki okna.

Panel MT ma preflight w workerze, postęp, anulowanie, wybór sceny i tablicy, całą scenę oraz powiększenie GT z zoom/pan. Dekoduje ponownie oryginalny obraz tym samym dekoderem co annotator i sprawdza plik oraz SHA pikseli. Nakładka: turkusowy bbox, zielone TL/TR/BR/BL; dla błędnego porządku czerwony poligon i uczciwe oznaczenia surowych P1/P2/P3/P4. Podgląd błędnego przypadku pozostaje dostępny mimo FAIL.

`save_operator_decision()` wymaga jawnej decyzji i podpisu tekstowego operatora. Akceptacja wymaga poprawnego preflightu i obejrzenia wszystkich scen; odrzucenie wymaga powodu. Przed zapisem źródła są ponownie sprawdzane. Kontrakt jest wersjonowany i powiązany SHA z polityką, źródłami, pikselami, modelami i kodem. To lokalne oświadczenie operatora z kontrolą integralności, nie podpis PKI.

Decyzje trafią do osobnego `Workspace/E-MZ-DN-01/evaluation_runs/EVAL396_MT_geometry_<czas>_<id>/` (`preflight.json`, `geometry_policy.json`, `status.json`); zakończony katalog powstaje z `.partial`. Dotychczasowe runy i freeze są chronione. Przyszły runner ma wywołać `require_current_approval()` po świeżym preflight. W 2A przycisk pomiaru pozostaje zablokowany także po akceptacji, ponieważ runner 2B nie został jeszcze wdrożony.

### Dowód GUI i jego ograniczenie

Narzędzie dostępu do bieżącej sesji systemowej ponownie zwróciło `Computer Use native pipe is unavailable ... os error 2`. Dlatego nie potwierdzono przejścia w otwartej pełnej sesji ALPR operatora.

Uruchomiono rzeczywisty istniejący `open_results()` i nowe widgety w izolowanym hoście Tk, bez inicjalizacji `TrainingTab` i rekonsyliacji historii. Do sprawdzenia renderowania wykorzystano zapisany wynik osobno wykonanego pełnego preflightu; odczyt obrazów, sprawdzanie SHA oraz nakładki działały rzeczywistą ścieżką produkcyjną. Zrzuty obejrzano, potwierdzono rozmiary 1160×790 i 860×640, dostępność dolnych przycisków, 0 błędów callbacków, brak automatycznej decyzji i disabled pomiar. To dowód widgetów, nie GUI PASS operatora.

- [SG621AW: EXIF=6, cała scena i powiększenie](Workspace/_qa/phase2a_20261009/1_SG621AW_EXIF6.png)
- [Kontrola DAY](Workspace/_qa/phase2a_20261009/2_control.png)
- [Kontrola NIGHT](Workspace/_qa/phase2a_20261009/3_control.png)
- [plate_000421: czerwone surowe P1–P4](Workspace/_qa/phase2a_20261009/4_GT_ORDER_FAIL.png)
- [Minimalny rozmiar okna](Workspace/_qa/phase2a_20261009/minimum_860x640.png)
- [Wynik kontroli GUI](Workspace/_qa/phase2a_20261009/gui_verification.json)

### Kroki operatora

1. Po przeładowaniu aplikacji: **Z4 → Ranking modeli → [ TOR ] Zmień tor testowy → EVAL396 — zamrożona selekcja → [ TOR ] Zastosuj zaznaczony tor → [ WYNIKI ] Pokaż wyniki**.
2. Wybrać kartę **MT — lokalizacja i geometria**, następnie **[ MT ] Sprawdź geometrię i EXIF**. Poczekać na pełną kontrolę; w obecnych danych oczekiwany jest FAIL/STOP dla `plate_000421`.
3. W **Scena do odbioru** wybrać `SG621AW`; przycisk **[ MT ] Otwórz podgląd GT** ponawia odczyt. Sprawdzić pionowe wejście 3024×4032, bbox na właściwej tablicy oraz TL/TR/BR/BL względem obrazu i tablicy. Obejrzeć też zwykłe kontrole DAY/NIGHT.
4. Wybrać scenę oznaczoną **! GT**, tablicę `plate_000421 — ! GT`. Rozstrzygnąć znaczenie P1–P4 przed przyjęciem mapowania. Nie akceptować geometrii przez obejście blokady. Można zapisać odrzucenie z podpisem i uzasadnieniem.
5. Dopiero po świadomie przyjętej rewizji kontraktu, ponownej kontroli i wzrokowym odbiorze wszystkich wymaganych scen dostępna będzie akceptacja polityki. Akceptacja 2A sama nie uruchamia pomiaru.

Wymóg zatrzymania pochodzi z handoffu `HANDOFF_AGENT_FAZA2_MT_POSE_EVAL396_Z4_2026-10-09.md`, §7: „Nie uruchamiaj żadnej rzeczywistej inferencji na EVAL396, dopóki operator nie obejrzy podglądu sceny EXIF i nie zatwierdzi układu współrzędnych.” Obecny problem kolejności dodatkowo uniemożliwia techniczne zatwierdzenie kontraktu v1.

## 4. Testy i niezmienność artefaktów

| Zestaw wykonany | Wynik |
|---|---|
| `tests/test_mt_geometry_review.py` + `tests/test_z4_eval396.py` | **37 PASS, 0 FAIL**, 69,76 s |
| `tests/test_z2_at_semantics.py` | **12 PASS, 0 FAIL**, 9,61 s |
| Łącznie | **49 PASS, 0 FAIL**; nie jest to cała suita repo |
| Pełny preflight lokalnych danych | źródła i dekodery zgodne; **FAIL geometrii dla 1/479** — odrębne od wyniku pytest |
| SHA chronionych plików przed/po | **2646/2646 niezmienione, 0 zmian** |
| Wcześniejsze obce zmiany robocze | Zachowane; zmieniły się wyłącznie celowo rozszerzane `z4_eval396.py` i jego test spośród 11 wcześniej brudnych plików |

Testy obejmują asymetryczny obraz EXIF 1/3/6/8, brak tagu JPEG/PNG, niepoprawny tag, uszkodzenie, fałszywy obrót także przy identycznym rozmiarze, rzeczywistą tablicę przekazaną stubom trzech annotatorów, wymiary CVAT, zachowanie keypointów poza surową wysokością Pillow, GT poza granicami/brak quad/odwrotny obieg/samoprzecięcie/NaN, niepełny podpis/odbiór, odrzucenie, zmienione SHA/kontrakt/politykę, ochronę katalogu, rzeczywiste widgety Tk i regresje MZ. Akceptacje fixture są wyłącznie w testowym katalogu poza rzeczywistym eksperymentem.

Snapshot 2646 plików obejmuje freeze (2208), selekcję (5), ukończone wyniki MZ (10), źródła/sceny (408), wskazane checkpointy i historie (9) oraz sześć plików odebranego eksportu `eval396_import_20261009_212705_99dbb537`. Nie jest snapshotem całego Workspace ani certyfikacją final_test; final_test nie był otwierany ani wykorzystywany przez tę dostawę. Czytnik preflight dodatkowo ponownie sprawdził wszystkie **6910** odczytanych plików źródłowych/kodu. Nadal nie certyfikuje near-duplicates ani danych pretrainingu.

Dowody: [preflight.json](Workspace/_qa/phase2a_20261009/preflight.json), [verification.json](Workspace/_qa/phase2a_20261009/verification.json), [SHA przed](Workspace/_qa/phase2a_20261009/protected_before.json), [SHA po](Workspace/_qa/phase2a_20261009/protected_after.json). Fingerprint preflight: `db62ca9e94606148f141425f2e40d00ae24e7264464c445a7803beb784e3b649`. OpenCV 4.13.0, Pillow 12.1.0, NumPy 2.1.3.

## 5. Zakres plików i dalsza Faza 2B–C

Nowe pliki produkcyjne: `auto_annotation_tool/image_orientation.py`, `auto_annotation_tool/ranking/mt_geometry_review.py`, `auto_annotation_tool/gui/z4_mt_geometry.py`. Zmienione: `annotators/base.py`, `annotators/plate_annotator.py`, `annotators/combined_annotator.py`, `annotators/vehicle_annotator.py`, `gui/z4_eval396.py`. Nowy test: `tests/test_mt_geometry_review.py`; dostosowany test: `tests/test_z4_eval396.py` (rekurencyjne wyszukiwanie widgetów po dodaniu kart). Dodatkowo ten raport i dowody QA poza chronionymi danymi. Nie zmieniono istniejącego audytu Fazy 1.

Po odbiorze 2A pozostają:

1. Sprawdzenie rzeczywistego `pose`, names i czterech keypointów każdego checkpointu; wspólny zamrożony protokół, w tym zatwierdzona kolejność GT/predykcji i wejściowe piksele.
2. Worker pomiarów 396 pełnych scen × 3 MT, sekwencyjnie na GPU, postęp/anulowanie i niezależna kontrola uruchomienia. Bez OCR w torze MT.
3. Surowe box/keypoints oraz osobne liczniki braków, nieprawidłowych quadów i bbox-fallback. Dopasowanie jeden-do-jednego, stabilne rozstrzyganie remisów. Osobne operacyjne P/R/F1, błąd narożników oraz oficjalne Box/Pose AP/mAP tylko po poprawnej implementacji ich protokołu; starszy XML comparator nie jest AP.
4. Nowy wersjonowany run lokalny, ewentualny audytowalny test-view zorientowanych obrazów/etykiet wyłącznie w runie. Żadnej przebudowy selekcji lub freeze.
5. Wznowienie sprawdza fingerprint protokołu, checkpoint, scenę i SHA zapisanych rekordów. Ukończony, zgodny model/run ma być odczytywany; tylko brakujące prawidłowo zidentyfikowane jednostki mogą być obliczane. PARTIAL nie staje się PASS przez pominięcie braków. Ukończonych MZ nie uruchamiać ponownie.
6. Wyniki DAY/NIGHT/ALL, wykresy, raport SVG/CSV/Markdown/provenance i rzeczywisty odbiór GUI. Potem osobna decyzja o dalszych fazach; brak automatycznej promocji, E2E, mobile lub final_test.
