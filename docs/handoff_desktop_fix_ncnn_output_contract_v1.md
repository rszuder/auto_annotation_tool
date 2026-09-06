# HANDOFF — Desktop exporter: naprawa kontraktu wyjścia MT dla NCNN

## Repozytorium i punkt odniesienia

Repozytorium: `rszuder/auto_annotation_tool`

Punkt odniesienia audytu:
- commit: `32111cd9d0b21e12d5ca2bb3b38eda1dc200a4a9`
- message: `Potwierdzanie datasetu po przygotowaniu obrazow przed treningiem`

Nie cofaj zmian dotyczących provenance, identyfikacji checkpointów, datasetów, historii treningów ani eksportu research-v1.

## Problem

Scenariusz:
1. Desktop eksportuje kompletny pakiet MP + MT(YOLO26s Pose) + MZ.
2. Pakiet działa w Androidzie.
3. Desktop eksportuje osobny MT(YOLO26n Pose).
4. Android podmienia tylko MT.
5. Import jest poprawny.
6. Live pipeline zgłasza:

```text
Tensor YOLO end-to-end ma niezgodny kształt:
atrybuty=13, oczekiwano co najmniej 14
```

Dostarczony rzeczywisty `manifest.json` ma:
- `role=plate`
- `task=pose`
- `input=512x512`
- `class_count=1`
- `keypoint_count=4`
- `keypoint_dimensions=2`

Top-level `output` deklaruje `ultralytics_pose_end2end_v1`.
Wariant `ncnn-fp32` również jawnie deklaruje:
- `output_format=end2end_detections`
- `tensor_layout=channels_first`
- `box_format=xyxy`
- `nms_required=false`
- `end2end_output=true`

To jest niezgodne z rzeczywistym kontraktem NCNN używanym przez Android.

## Dlaczego 13 i 14 są diagnostyczne

Dla RAW YOLO Pose:

```text
4 bbox + 1 klasa + 4*2 keypoints = 13
```

Dla END-TO-END:

```text
6 + 4*2 keypoints = 14
```

Komunikat Androida oznacza więc:

```text
rzeczywisty tensor = RAW YOLO Pose
manifest/dekoder   = END-TO-END
```

## Przyczyna po stronie Desktop

W `_export_variant(...)` TFLite i ONNX przechodzą przez `inspect_variant(...)`, ale NCNN nie ma równoważnej inspekcji. Początkowy `default_output` jest budowany z checkpointowego `end2end_output`. Dla tego modelu checkpoint jest oznaczony jako end-to-end, więc ta właściwość jest błędnie przenoszona na wariant NCNN.

Android ma specjalną konwersję NCNN do RAW, ale wykonuje ją tylko wtedy, gdy wariant NCNN nie ma własnego `output` override. Desktop zapisuje override, więc mechanizm ochronny Androida zostaje pominięty.

## Cel poprawki

Kontrakt `output` ma opisywać rzeczywisty artefakt wykonawczy, a nie logiczną właściwość checkpointu:

```text
checkpoint
 -> TFLite artifact -> osobny output spec
 -> ONNX artifact   -> osobny output spec
 -> NCNN artifact   -> osobny output spec
```

## Wymagane zmiany P0

### 1. NCNN zawsze jako RAW YOLO

Dla MT Pose wymusić:

```json
{
  "decoder": "ultralytics_pose_raw_v1",
  "output_format": "raw_yolo",
  "class_count": 1,
  "keypoint_count": 4,
  "keypoint_dimensions": 2,
  "has_objectness": false,
  "tensor_layout": "channels_first",
  "box_format": "xywh",
  "normalized_coordinates": false,
  "nms_in_graph": false,
  "nms_required": true
}
```

Zachować progi confidence/IoU z requestu.

### 2. Nie dziedziczyć kontraktu NCNN z `model_info["end2end_output"]`

Dodać osobną ścieżkę np. `_resolve_ncnn_output_spec(...)` albo rozszerzyć `inspect_variant()` o NCNN. Jeżeli pełna automatyczna inspekcja `.param/.bin` jest niewygodna, zastosować jawny, testowany kontrakt:

```text
Ultralytics/PNNX NCNN -> raw_yolo
```

### 3. Nie wyprowadzać tasku z nazwy dekodera przez `replace`

Obecne podejście dla `ultralytics_pose_end2end_v1` daje `pose_end2end_v1` zamiast `pose`.

Task przekazywać jawnie:
- plate -> pose
- vehicle -> detect
- character -> detect

### 4. Walidacja gotowego pakietu ma obejmować runtime/output

`validate_package()` powinien odrzucać m.in.:

```text
runtime=ncnn
output_format=end2end_detections
```

Dla NCNN wymagać:
- `*_raw_v1`
- `raw_yolo`
- `xywh`
- `nms_required=true`

TFLite/ONNX nadal walidować na podstawie rzeczywistej inspekcji artefaktu.

### 5. Wspólny helper oczekiwanego wymiaru

RAW:

```python
expected_raw = 4 + int(has_objectness) + class_count + keypoint_count * keypoint_dimensions
```

END-TO-END:

```python
expected_end2end = 6 + keypoint_count * keypoint_dimensions
```

Dla tego MT:
- RAW = 13
- END-TO-END = 14

### 6. Per-wariant output

Nie zakładać, że wszystkie runtime mają taki sam format. Poprawny pakiet może mieć:

```text
TFLite -> end2end
ONNX   -> end2end
NCNN   -> raw
```

Każdy wariant różniący się od top-level `output` ma dostać poprawny override.

## Testy regresyjne

1. YOLO26n Pose `[4,2]`, NCNN -> `ultralytics_pose_raw_v1`, `raw_yolo`, `xywh`, `nms_required=true`, oczekiwane 13.
2. Ten sam test dla YOLO26s Pose.
3. TFLite: tensor 14 -> end-to-end; tensor 13 -> raw.
4. ONNX: analogicznie.
5. Walidator odrzuca NCNN zadeklarowany jako end-to-end.
6. Task zawsze wynika z roli, nie z nazwy dekodera.
7. Eksport pełnego pakietu S i osobnego MT N bez zmiany kontraktów MP/MZ.

## Nie zmieniać

Nie zmieniać:
- provenance v2,
- lineage,
- dataset identity,
- `dataset_id`,
- `split_sha256`,
- `data_yaml_sha256`,
- checkpoint SHA-256,
- `best_epoch`,
- logiki treningu,
- rankingu modeli,
- `.alprsession`,
- `model_refs`.

To jest naprawa `runtime/output contract`.

## Kryterium akceptacji

Nowo wyeksportowany pakiet tego YOLO26n Pose nie może deklarować NCNN jako end-to-end, jeśli rzeczywisty artefakt ma 13 kanałów RAW.

Po imporcie w Androidzie model ma działać jako MT bez błędu `13 vs 14` i bez ręcznej edycji manifestu.

## Raport końcowy agenta

Podaj:
- commit SHA,
- zmienione pliki,
- uruchomione testy,
- wynik testów,
- finalny `output` dla TFLite/ONNX/NCNN,
- informację, czy ponowny eksport YOLO26n przeszedł walidację ZIP.

## Wdrożenie i weryfikacja — 2026-09-06

Implementacja: `auto_annotation_tool/exporters/mobile_model_exporter.py`.
Regresje: `tests/test_mobile_ncnn_output_contract.py`.

- NCNN otrzymuje jawny kontrakt Ultralytics/PNNX RAW, niezależny od
  `end2end_output` checkpointu. Zachowane są liczby klas/keypointów i progi.
- `inspect_variant(..., role=...)` wyznacza task z roli. ONNX i TFLite nadal
  ustalają format na podstawie kształtu rzeczywistego artefaktu.
- Walidacja manifestu, wywoływana także po otwarciu ZIP i dla pakietów
  zagnieżdżonych, sprawdza spójność runtime, dekodera, formatu, wymiarów,
  układu, współrzędnych i NMS. Niepełny override nie dziedziczy brakujących
  wymiarów: Android traktuje `variant.output` jako kompletny obiekt.
- Wspólna funkcja `expected_yolo_output_attributes` rozróżnia RAW z opcjonalnym
  objectness oraz end-to-end. RAW 13 i end-to-end 14 dotyczą MT z `[4,2]`;
  samo 14 nie wystarcza do odróżnienia end-to-end od RAW z objectness.
- Starsze paczki błędnie deklarujące NCNN jako end-to-end są odrzucane;
  wymagają ponownego eksportu.

Uruchomiono:

```text
python -m pytest tests/test_mobile_ncnn_output_contract.py tests/test_mobile_export_checkpoint_identity.py tests/test_mobile_export_project_sources.py tests/test_mobile_report_full_rows.py -q --tb=short --basetemp=output/pytest_ncnn_all_mobile
```

Wynik: **70 passed**, w tym 38 nowych przypadków kontraktu wyjścia.
Obejmują N/S, keypointy 2D/3D, role MP/MT/MZ, tensor 13/14, błędne ZIP,
kompletne override, zachowanie provenance i złożenie pełnej paczki S.

Rzeczywiste checkpointy projektu `pisto`, wejście 512×512:

| Model | Run | SHA-256 checkpointu |
| --- | --- | --- |
| YOLO26n Pose | `20260718_200612` | `855b7ed25610335b6ae18171035fea783c83df246ddf310b9045b8b2e94871a8` |
| YOLO26s Pose | `20260713_204401` | `ee7c8959b1deba89d51c608c6b83e0bf2aa14041cc94c336ea99899d656684e4` |

Źródłowe pliki `.pt` zachowały SHA-256. Nie zmieniono historii treningów ani
datasetów. Eksport kontrolny wykonał bezpośrednio publiczny eksporter API;
pakiety kontrolne nie zawierają pełnego profilu provenance przekazywanego
przez centrum eksportu GUI. Zachowanie tego profilu sprawdzają regresje.

| Runtime | Finalny decoder / format | Układ | Box | NMS | Tensor |
| --- | --- | --- | --- | --- | --- |
| TFLite FP32 (N) | `ultralytics_pose_end2end_v1` / `end2end_detections` | `detections_first` | `xyxy` | `false` | `[1,300,14]` |
| ONNX FP32 (N/S) | `ultralytics_pose_end2end_v1` / `end2end_detections` | `detections_first` | `xyxy` | `false` | `[1,300,14]` |
| NCNN FP32 (N/S) | `ultralytics_pose_raw_v1` / `raw_yolo` | `channels_first` | `xywh` | `true` | `[13,5376]` |

Każdy wariant MT ma `class_count=1`, `keypoint_count=4`,
`keypoint_dimensions=2`, `has_objectness=false`, `nms_in_graph=false`,
confidence `0.25` oraz IoU `0.45`. Współrzędne TFLite są znormalizowane,
ONNX/NCNN są pikselowe. `end2end_output` jest zgodny z formatem wariantu.

NCNN i ONNX wykonano na CPU z zerowym wejściem; TFLite sprawdzono przez
odczyt kształtu z gotowego pliku. Dodatkowa próba inferencji TFLite po
konwersji zakończyła proces diagnostyczny bez raportu, dlatego nie zaliczono
jej jako testu wykonania TFLite. Ponowna, osobna inspekcja gotowej paczki N
oraz wykonanie ONNX/NCNN zakończyły się poprawnie.

**Ponowny eksport YOLO26n przeszedł walidację ZIP.** Eksport S i pełna paczka
MP + MT(S) + MZ również przeszły walidację, włącznie z paczkami potomnymi.
MP/MZ pochodzą z istniejącej paczki `260826_1847_int8` i pozostają identyczne
bajtowo. SHA-256 pakietów potomnych:

- MP: `61449aeb6ce8e1d3c5bf0919ec578f5091eb71bb12f7c78941ae9a8f8475ba19`
- MZ: `09ae09ccd9b40bdbe8af875902cc0b5e887a149c2d49b7f7bc7286126cc98bd7`

Artefakty lokalne, poza Git:

- `output/ncnn_contract_audit/mt_yolo26n_512.alprmodel`
- `output/ncnn_contract_audit/mt_yolo26s_512.alprmodel`
- `output/ncnn_contract_audit/full_mp_mt_s_mz.alprmodel`
- `output/ncnn_contract_audit/n_results.json`, `s_results.json`
- `output/ncnn_contract_audit.py` — skrypt odtwarzający eksport i kontrolę.

Środowisko: Ultralytics 8.4.19, PyTorch 2.5.1+cu121, TensorFlow 2.19.0,
ONNX 1.20.1, NCNN 1.0.20260526, PNNX 20260526. Nie wykonano podmiany MT
ani testu live na telefonie; weryfikacja dotyczy desktopu i artefaktów CPU.
