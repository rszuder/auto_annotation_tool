# Handoff: eksporter modeli Python → klient mobilny ALPR

> Dokument lokalny przekazywany pomiędzy agentami. Nie dodawać go do repozytorium klienta mobilnego.

Stan kontraktu: 2026-08-21. Android obsługuje już paczki MT+MZ oraz MP+MT+MZ.
Eksporter Python buduje pojedyncze pakiety `MP`, `MT`, `MZ` oraz kompletne paczki
`MT+MZ` i `MP+MT+MZ`. Konwersja surowego modelu pojazdów YOLO nie powinna być
wykonywana na telefonie, bo jest zbyt ciężka dla urządzenia mobilnego; desktop
ma dostarczyć gotowy artefakt wykonawczy w paczce `.alprmodel`.

`MP` jest opcjonalnym filtrem ROI dla pojazdów. Może pochodzić z modelu
trenowanego w projekcie albo z bazowego detektora Ultralytics/COCO
przygotowanego przez aplikację Python w `Workspace/6_models/base/detect`.
Telefon może działać także na paczce `MT+MZ` bez etapu pojazdów; jeśli `MP`
zostanie dołączony, Android importuje gotowy model `vehicle/detect`, jego
warianty runtime, manifest oraz filtr klas pojazdów. Telefon nie pobiera i nie
konwertuje surowego modelu `MP`.

`MP` może być dodany z katalogu modeli Ultralytics po stronie aplikacji Python.
Centrum eksportu pokazuje aktualną listę modeli `detect`, najpierw szuka
wskazanego pliku w katalogach programu, a gdy go nie znajdzie, pobiera checkpoint
na desktopie do `Workspace/6_models/base/detect/ultralytics`, waliduje rolę
`vehicle/detect` i dopiero taki model pokazuje jako kandydata eksportu. Klasy
pojazdów przepuszczane przez `MP` są ustawiane w konfiguracji eksportu pakietu.
Klient mobilny nie pobiera ani nie konwertuje surowych checkpointów.

Dokument opisuje kontrakt faktycznie zaimplementowanego klienta Android z projektu `C:\Users\48572\AndroidStudioProjects\ALPR_v1`. Eksporter powstaje w programie Python `C:\Users\48572\Desktop\dyplom\start4`.

Źródła prawdy po stronie Androida:

- `docs/model_package_v1.md` — opis i przykład manifestu;
- `docs/alpr-model-v1.schema.json` — JSON Schema;
- `docs/alpr-package-v1.schema.json` — JSON Schema kompletnej paczki;
- `app/src/main/java/com/example/alpr_v1/model/ModelManifest.java`;
- `app/src/main/java/com/example/alpr_v1/model/ModelPackageImporter.java`;
- `app/src/main/java/com/example/alpr_v1/model/AlprPackageManifest.java`;
- `app/src/main/java/com/example/alpr_v1/model/AlprPackageImporter.java`;
- `app/src/main/java/com/example/alpr_v1/pipeline/MobileAlprEngine.java`.

## 0. Aktualizacja kontraktu dla agenta Android - 2026-08-21

Ta sekcja jest krótkim briefem wykonawczym. Jeżeli agent pracujący nad klientem
mobilnym czyta tylko jedną część handoffu, powinien zacząć tutaj.

### 0.1. Co dostarcza aplikacja Python

- Eksporter desktopowy dostarcza gotowy plik `.alprmodel`; klient mobilny nie
  pobiera checkpointów `.pt` i nie konwertuje modeli YOLO na telefonie.
- Pakiet może zawierać jeden model logiczny `MP`, `MT` albo `MZ`, parę `MT+MZ`
  albo pełny komplet `MP+MT+MZ`.
- `MP` jest opcjonalnym modelem pojazdów. Jeżeli jest w paczce, jest już
  wyeksportowany do wariantów wykonawczych i opisany w manifeście tak samo jak
  `MT` i `MZ`.
- `MT` jest modelem tablic i ma `role="plate"`, `task="pose"`.
- `MZ` jest modelem znaków i ma `role="character"`, `task="detect"`.
- Każdy model w paczce ma własny manifest potomny, własne warianty runtime,
  progi, `imgsz`, etykiety, dekoder i sumy SHA-256.

### 0.2. Co musi zrobić klient mobilny

- Importować `alpr.package.v1` jako jeden komplet, ale uruchamiać każdy model
  zgodnie z jego osobnym manifestem.
- Dla paczki `MT+MZ` uruchomić kolejność:
  `plate_detection -> plate_rectification -> character_detection -> sequence_assembly`.
- Dla paczki `MP+MT+MZ` uruchomić kolejność:
  `vehicle_detection -> plate_detection -> plate_rectification -> character_detection -> sequence_assembly`.
- Jeżeli `MP` jest obecny, ale użytkownik wyłączy etap pojazdów, aplikacja może
  nadal uruchomić `MT` na pełnej klatce. Obecność `MP` w paczce nie wymusza
  użycia ROI pojazdu w każdej sesji.
- Dla `vehicle_detection` czytać filtr klas z bloku `vehicle_detection`.
  Najpierw używać `include_class_indices`, potem `include_labels`, a dopiero na
  końcu fallbacku COCO `[2,3,5,7]`.
- Nie zakładać, że wszystkie modele mają ten sam `imgsz`. `imgsz` jest liczbą
  pikseli wejścia danego modelu, np. `MP=320`, `MT=640`, `MZ=448`. W kaskadzie
  różne rozmiary wejścia są poprawne, bo każdy etap dostaje inny obraz roboczy:
  klatkę, ROI pojazdu albo wyprostowany crop tablicy.

### 0.3. Dekoder i tensor wyjścia są źródłem prawdy

Android nie powinien zgadywać dekodera na podstawie samej roli modelu. Źródłem
prawdy są pola manifestu:

- `output.output_format`;
- `output.decoder`;
- `output.tensor_layout`;
- `output.box_format`;
- `output.nms_required`;
- `output.keypoint_count`;
- `output.keypoint_dimensions`;
- `labels` i `class_count`.

Aktualne poprawne przypadki:

- `MT pose` może mieć wyjście TFLite `[1, 300, 14]`. To jest prawidłowe dla
  jednej klasy tablicy, czterech narożników i `keypoint_dimensions=2`.
- `MZ detect` może mieć wyjście `[1, 300, 6]`. To oznacza
  `end2end_detections`, czyli gotowe detekcje `x1, y1, x2, y2, score, class`.
- Dla `output_format="end2end_detections"` klient nie wykonuje drugiego NMS,
  bo manifest ustawia `nms_required=false`.
- Dla `output_format="raw_yolo"` klient dekoduje klasyczny tensor YOLO zgodnie
  z `tensor_layout` i progami z manifestu.

Jeżeli klient nie obsługuje danego `decoder` albo `output_format`, powinien
pokazać jasny błąd importu/uruchomienia wariantu zamiast zgadywać strukturę
tensora.

### 0.4. Kwantyzacja INT8 i `data.yaml`

- `data.yaml` służy wyłącznie do kalibracji INT8 po stronie aplikacji Python.
  Nie jest potrzebny do samej inferencji mobilnej.
- Eksporter zapisuje w manifeście informację o kalibracji, ale Android używa
  przede wszystkim parametrów kwantyzacji odczytanych z tensora TFLite.
- Kalibracja jest per model. `MP`, `MT` i `MZ` mogą mieć różne `data.yaml`,
  ponieważ reprezentatywne dane wejściowe są inne dla klatki/pojazdu, tablicy
  i cropu znaków.
- Wariant FP32 pozostaje wariantem referencyjnym. INT8 jest wariantem
  wydajnościowym i musi być porównany z FP32 na tym samym zestawie testowym.

### 0.5. Raport z klienta mobilnego

Raport Androida powinien zapisywać co najmniej:

- `package_id`, `package_version`, `created_at` i SHA-256 źródłowego
  `.alprmodel`;
- aktywne role modeli: `vehicle`, `plate`, `character`;
- `model_id`, wybrany runtime, precyzję, `imgsz`, `decoder` i
  `output_format` każdego etapu;
- informację, czy `vehicle_detection` było użyte, oraz jaki filtr klas
  zastosowano;
- czasy inferencji per etap i end-to-end, najlepiej `p50`, `p90`, `p95`;
- rozmiar pakietu, rozmiary modeli i obserwacje pamięciowe, jeżeli runtime je
  udostępnia;
- metryki jakości: wykrycie tablicy, poprawność rektyfikacji, poprawność znaków,
  `CER` oraz trafienie całego numeru rejestracyjnego.

Ten raport jest potrzebny nie tylko do UI aplikacji demonstracyjnej, ale też do
porównywania kandydackich pakietów w pracy inżynierskiej.

## 1. Obsługiwane formaty

| Wariant | Import | Inferencja | Autotuning |
| --- | --- | --- | --- |
| LiteRT `.tflite` FP32 | tak | CPU/GPU | tak |
| LiteRT `.tflite` INT8/UINT8 | tak | CPU/GPU, zależnie od delegata | tak |
| ONNX `.onnx` FP32 | tak | CPU | tak |
| ONNX INT8 | technicznie może być spakowany | nie | nie |
| NCNN `.param` + `.bin` | tak | jeszcze nie | nie |
| PyTorch `.pt` | nie | nie | nie |

Android używa LiteRT `1.4.1`, delegata GPU `1.4.2`, ONNX Runtime Android `1.26.0` oraz ABI `arm64-v8a`/`armeabi-v7a`.

NCNN może być wariantem dodatkowym, lecz pakiet przeznaczony do bieżącej aplikacji powinien zawierać co najmniej LiteRT albo ONNX.

## 2. Role modeli

| Tor Python | `role` | `task` | Warunki |
| --- | --- | --- | --- |
| `plate` | `plate` | `pose` | co najmniej 4 keypointy; zalecane dokładnie 4 rogi |
| `char` | `character` | `detect` | kompletne `labels` w kolejności ID klas |
| `vehicle` | `vehicle` | `detect` | model opcjonalnej pierwszej kaskady |

Klient odrzuca `plate+detect`, `character+pose`, `vehicle+pose`, model tablic z mniej niż czterema keypointami oraz manifest, w którym `len(labels) != class_count`.

Pierwsze cztery keypointy modelu tablic muszą być narożnikami. Telefon porządkuje je przestrzennie do `TL, TR, BR, BL`.

Ważne dla dekodera: model `pose` może eksportować punkty jako `kpt_shape=[N,2]` albo `kpt_shape=[N,3]`. Android nie może zakładać na sztywno trzech wartości na punkt. Manifest niesie `output.keypoint_dimensions`, które mówi, czy keypoint ma tylko `(x, y)`, czy `(x, y, confidence)`.

## 3. Zalecane warianty jednego pakietu

Minimum wdrożeniowe:

```text
LiteRT FP32 + ONNX FP32
```

Pakiet badawczy:

```text
LiteRT FP32 + LiteRT INT8 + ONNX FP32 + opcjonalnie NCNN FP32/FP16
```

Wszystkie warianty muszą pochodzić z tego samego `best.pt`. Autotuner traktuje je jako różne reprezentacje tych samych wag.

Nie eksportować osobnego LiteRT FP16. Aktualne Ultralytics nie tworzy dla LiteRT odrębnego pliku FP16; delegat GPU może wykonywać obliczenia z obniżoną precyzją na modelu FP32.

## 3.1. Semantyka wyboru wielu formatow

Kilka zaznaczonych formatow w jednym modelu potomnym oznacza kilka wariantow
wykonawczych tego samego checkpointu. To nie sa rozne modele logiczne i Android
nie powinien traktowac ich jako osobnych kandydatow MT/MZ/MP.

Znaczenie formatow dla klienta mobilnego:

| Format | Rola w pakiecie | Decyzja Androida |
| --- | --- | --- |
| `LiteRT/TFLite FP32` | wariant stabilny i domyslny na Androida | preferowany punkt startowy, jesli runtime LiteRT jest dostepny |
| `LiteRT/TFLite INT8` | wariant lekki/wydajnosciowy | uzywac dopiero po walidacji jakosci wzgledem FP32 i po sprawdzeniu kalibracji |
| `ONNX FP32` | wariant kontrolny/fallback | uruchamiac, gdy potrzebna jest diagnostyka albo gdy TFLite nie dziala na urzadzeniu |
| `NCNN FP32` | wariant eksperymentalny | importowac tylko jako opcje, dopoki aplikacja nie ma pelnego runtime NCNN |

Android powinien zapisac w raporcie, ktory wariant faktycznie uruchomil dla
kazdej roli (`vehicle`, `plate`, `character`). To jest istotne badawczo, bo
ten sam checkpoint moze miec rozne czasy inferencji, rozmiary i zachowanie
numeryczne w zaleznosci od runtime.

Rekomendowany model wyboru:

1. Dla demonstracji: preferowac `LiteRT/TFLite FP32`.
2. Dla badan: eksportowac rownolegle `LiteRT/TFLite FP32`, `ONNX FP32` i
   opcjonalnie `LiteRT/TFLite INT8`.
3. Dla finalnego domyslnego runtime: wybrac wariant na podstawie raportu
   mobilnego, a nie na podstawie samego rozmiaru pliku.

## 4. Biblioteki Python

Podstawowe, już używane przez program:

```text
torch
ultralytics
PyYAML
```

Standardowa biblioteka Pythona wystarczy do zbudowania pakietu:

```text
dataclasses, hashlib, json, pathlib, shutil, tempfile, zipfile
```

ONNX — eksport, inspekcja i walidacja:

```text
onnx
onnxruntime
onnxslim
```

LiteRT — zależnie od wersji Ultralytics:

```text
tensorflow
tf_keras
onnx2tf
onnx_graphsurgeon
sng4onnx
ai-edge-litert
onnx
onnxruntime
onnxslim
protobuf
```

Eksporter powinien wykonać własny preflight i pokazać brakujące zależności zamiast pozwalać Ultralytics na instalowanie pakietów w tle. Automatyczny `AutoUpdate` utrudnia powtarzalność eksperymentu, bo zmienia środowisko wykonawcze poza jawnie kontrolowanym przepływem aplikacji.

Po eksporcie `.tflite` eksporter desktopowy musi otworzyć plik przez interpreter TFLite, najlepiej `tf.lite.Interpreter`. To jest etap kontroli manifestu: odczytujemy realny kształt wejścia, wyjścia, typ danych i parametry kwantyzacji. Nie używać starego importu `from tensorflow.lite import Interpreter`, bo w TensorFlow `2.19` może go nie być.

Do testów i walidacji manifestu:

```text
jsonschema
pytest
```

Proponowany osobny plik:

```text
requirements-mobile-export.txt
```

Przykładowa zawartość:

```text
ultralytics
torch
torchvision
onnx
onnxruntime
onnxslim
jsonschema
pytest
tensorflow>=2.0.0,<=2.19.0
tf_keras<=2.19.0
sng4onnx>=1.0.1
onnx_graphsurgeon>=0.3.26
ai-edge-litert>=1.2.0
onnx2tf>=1.26.3,<1.29.0
protobuf>=5
ncnn
pnnx
```

Wersję Ultralytics spiąć z wersją używaną do treningu. Nie dodawać bez weryfikacji wszystkich zależności przejściowych eksportu do głównego `requirements-runtime.txt`.

### Stan środowiska sprawdzony 2026-08-19

```text
Python 3.12.7
torch 2.5.1+cu121
torchvision 0.20.1+cu121
ultralytics 8.4.19
tensorflow 2.19.0
tf_keras 2.19.0
onnx 1.20.1
onnxruntime 1.26.0
onnxslim 0.1.96
onnx2tf 1.28.8
protobuf 5.29.6
```

W tej sesji preflight potwierdził komplet zależności dla `LiteRT/TFLite` i `ONNX`. Braki dotyczą tylko opcjonalnego wariantu `NCNN`: `ncnn` oraz `pnnx`. Agent powinien ponownie wykonać preflight przed eksportem, bo środowisko Pythona może się zmienić między sesjami.

Kontrola interpretera TFLite: `tf.lite.Interpreter` działa w bieżącym środowisku.

## 5. Wywołania Ultralytics

Wymagania wspólne Androida:

```python
common = {
    "imgsz": image_size,
    "batch": 1,
    "dynamic": False,
    "nms": False,
    "device": "cpu",
}
```

- `batch=1` — mobilny dekoder obsługuje tylko batch 1;
- `dynamic=False` — backend ONNX odrzuca wymiary dynamiczne;
- `nms=False` — Android wykonuje własny NMS;
- `imgsz` musi odpowiadać manifestowi.

```python
from ultralytics import YOLO

model = YOLO("best.pt")

onnx_path = model.export(
    format="onnx", imgsz=640, batch=1, dynamic=False,
    simplify=True, nms=False, device="cpu",
)

litert_path = model.export(
    format="tflite", imgsz=640, batch=1,
    nms=False, device="cpu",
)

ncnn_dir = model.export(
    format="ncnn", imgsz=640, batch=1, device="cpu",
)
```

W UI używamy nazwy `LiteRT/TFLite`, bo taki jest sens wdrożeniowy formatu dla Androida. Do lokalnego Ultralytics przekazujemy jednak `format="tflite"`. Nie należy przekazywać `format="litert"` bez jawnego sprawdzenia obsługi w używanej wersji biblioteki.

Eksport INT8:

```python
model.export(
    format="tflite",
    int8=True,
    data="data.yaml",
    fraction=1.0,
    imgsz=640,
    batch=1,
    nms=False,
    device="cpu",
)
```

Eksporter może obsłużyć wariant awaryjny `quantize=8`, jeśli dana wersja Ultralytics nie przyjmie `int8=True`. Eksport INT8 bez reprezentatywnego `data.yaml` powinien być zablokowany w GUI.

## 6. Inspekcja rzeczywistych tensorów

Manifestu nie wolno tworzyć wyłącznie z założeń o formacie. Każdy artefakt należy otworzyć i odczytać jego tensor wejściowy i pierwsze wyjście.

### Wejście

Dozwolone kształty statyczne:

```text
[1, H, W, 3] -> NHWC
[1, 3, H, W] -> NCHW
```

Inny kształt przerywa eksport. TFLite może mieć `FLOAT32`, `UINT8` lub `INT8`. Obecny backend ONNX wymaga `FLOAT32`.

Domyślny preprocessing Ultralytics:

```json
{
  "color": "RGB",
  "scale": 0.0039215686,
  "offset": 0.0
}
```

Android wykonuje letterbox kolorem `(114,114,114)`. Dla TFLite kwantyzowanego parametry kwantyzacji są odczytywane również z samego tensora.

### Wyjście

Dekoder obsługuje dwa typy wyjścia YOLO:

- `raw_yolo` - klasyczny tensor `xywh + score klas + opcjonalne keypointy`;
- `end2end_detections` - gotowa lista detekcji, typowa dla modeli end-to-end/YOLO26: `x1, y1, x2, y2, score, class` oraz opcjonalne keypointy.

Model end-to-end nie wymaga NMS po stronie Androida. To nie jest błąd eksportu, tylko inny kontrakt dekodera.

Liczba kanałów:

```text
detect bez objectness: 4 + class_count
pose bez objectness:   4 + class_count + keypoint_dimensions * keypoint_count

detect z objectness:   5 + class_count
pose z objectness:     5 + class_count + keypoint_dimensions * keypoint_count

detect end-to-end:     6
pose end-to-end:       6 + keypoint_dimensions * keypoint_count
```

```python
expected_channels = (
    4
    + int(has_objectness)
    + class_count
    + keypoint_dimensions * keypoint_count
)

if output_shape[-2] == expected_channels:
    tensor_layout = "channels_first"  # [1,C,N]
elif output_shape[-1] == expected_channels:
    tensor_layout = "anchors_first"   # [1,N,C]
else:
    raise ExportError("Nie rozpoznano układu surowego wyjścia YOLO")
```

Wszystkie wcześniejsze wymiary muszą wynosić `1`. Android dekoduje pierwsze wyjście modelu.

Przykład: model tablic `pose` z jedną klasą, czterema narożnikami i `keypoint_dimensions=2` ma `13` kanałów bez objectness albo `14` kanałów z objectness. Kształt TFLite `[1, 300, 14]` jest w takim przypadku prawidłowy.

Przykład: model znaków `detect` z `36` klasami i wyjściem `[1, 300, 6]` jest modelem `end2end_detections`. Kanały nie zawierają całego wektora `36` score klas, tylko `score` zwycięskiej klasy i `class_index`.

Przykład `output` dla modelu znaków:

```json
{
  "decoder": "ultralytics_detect_raw_v1",
  "output_format": "raw_yolo",
  "class_count": 36,
  "keypoint_count": 0,
  "keypoint_dimensions": 0,
  "has_objectness": false,
  "tensor_layout": "channels_first",
  "normalized_coordinates": false,
  "nms_in_graph": false,
  "confidence_threshold": 0.25,
  "iou_threshold": 0.45
}
```

Akceptowane dekodery: `ultralytics_yolo_raw_v1`, `ultralytics_detect_raw_v1`, `ultralytics_pose_raw_v1`, `ultralytics_detect_end2end_v1`, `ultralytics_pose_end2end_v1`.

## 7. Etykiety

```python
raw_names = dict(model.names)
indices = sorted(int(key) for key in raw_names)
if indices != list(range(len(indices))):
    raise ExportError("Klasy nie tworzą zakresu 0..N-1")
labels = [str(raw_names[index]) for index in indices]
```

W niektórych modelach klucze mogą być napisami; implementacja powinna obsłużyć `raw_names[index]` i `raw_names[str(index)]`.

- `len(labels) == class_count`;
- `character`: tekst etykiety jest bezpośrednio doklejany do wyniku;
- `vehicle`: model powinien zawierać tylko klasy traktowane jako pojazdy albo eksporter musi jawnie zbudować ich podzbiór;
- `plate`: może mieć jedną klasę `plate` lub klasy typów tablic.

Dla roli `vehicle` eksporter zapisuje dodatkowy blok `vehicle_detection`.
Ten blok mówi aplikacji mobilnej, które klasy detektora pojazdów mają wejść do
dalszej kaskady ALPR:

```json
{
  "filter_mode": "include",
  "include_labels": ["car", "motorcycle", "bus", "truck", "van", "vehicle"],
  "include_class_indices": [2, 3, 5, 7],
  "fallback_coco_class_indices": [2, 3, 5, 7],
  "label_matching": "case_insensitive_normalized",
  "next_stage": "plate_detection"
}
```

Android powinien najpierw użyć `include_class_indices`, bo są policzone względem
faktycznych `labels` wyeksportowanego modelu. Jeżeli indeksów nie ma, klient
może zmapować `include_labels` na `labels` po normalizacji tekstu. Dopiero dla
standardowego modelu COCO dopuszczalny jest fallback `fallback_coco_class_indices`.
Wynik `MP` nie jest wynikiem końcowym ALPR; służy tylko do wyznaczenia ROI, w
którym uruchamiany jest `MT`.

## 8. Manifest i struktura ZIP

Schemat: `alpr.model.v1`. `model_id` pasuje do:

```text
[A-Za-z0-9][A-Za-z0-9._-]{0,79}
```

Przykładowa struktura:

```text
manifest.json
variants/tflite/model.tflite
variants/tflite_int8/model.tflite
variants/onnx/model.onnx
variants/ncnn/model.param
variants/ncnn/model.bin
```

Wymagania importera:

- maksymalnie 256 wpisów;
- maksymalnie 512 MiB po rozpakowaniu;
- tylko względne ścieżki POSIX;
- brak duplikatów;
- `manifest.json` w katalogu głównym;
- SHA-256 dla każdego wskazanego pliku;
- TFLite kończy się `.tflite`;
- ONNX kończy się `.onnx`;
- NCNN ma `.param` i `.bin`.

```python
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
```

Pakiet jest zwykłym ZIP z rozszerzeniem `.alprmodel`. Pola `input` i `output` na poziomie manifestu są domyślne. Każdy wariant może je nadpisać, co jest potrzebne np. dla TFLite NHWC i ONNX NCHW.

Zalecane metadane dodatkowe:

```json
{
  "source": {
    "checkpoint": "best.pt",
    "checkpoint_sha256": "...",
    "ultralytics_version": "...",
    "torch_version": "...",
    "exported_at": "ISO-8601"
  },
  "training": {
    "run_id": "...",
    "dataset_path": "...",
    "img_size": 640
  },
  "metrics": {
    "best_map50": 0.0,
    "best_map50_95": 0.0,
    "best_epoch": 0
  }
}
```

## 9. Kompletny pakiet ALPR `MT+MZ` lub `MP+MT+MZ`

Pojedynczy pakiet `alpr.model.v1` opisuje jeden model logiczny. Pełny system ALPR
na telefonie potrzebuje co najmniej dwóch modeli, a opcjonalnie trzech:

- `MP` — opcjonalny model pojazdów ograniczający analizę MT do ROI;
- `MT` — model tablic, czyli detekcja tablicy i punkt startowy rektyfikacji;
- `MZ` — model znaków na wyciętej i wyprostowanej tablicy.

Eksporter Python musi potrafić utworzyć drugi poziom pakietu:
`alpr.package.v1`. Format nie zastępuje `alpr.model.v1`, tylko pakuje dwa lub
trzy już zwalidowane pakiety pojedynczych modeli w jeden komplet
wdrożeniowo-badawczy.

Przykładowa struktura:

```text
manifest.json
models/vehicle/model.alprmodel       # opcjonalny MP
models/vehicle/manifest.json         # opcjonalny MP
models/plate/model.alprmodel
models/plate/manifest.json
models/character/model.alprmodel
models/character/manifest.json
```

Manifest głównego pakietu ma:

- `schema: "alpr.package.v1"`;
- `kind: "complete_alpr_pipeline"`;
- wymagane `models.plate` z `role: "plate"`, `task: "pose"`;
- wymagane `models.character` z `role: "character"`, `task: "detect"`;
- opcjonalne `models.vehicle` z `role: "vehicle"`, `task: "detect"`;
- czteroetapowy `pipeline` dla MT+MZ albo pięcioetapowy dla MP+MT+MZ;
- metadane eksperymentu, datasetu rankingowego i datasetu kalibracyjnego, jeżeli są znane.

Android rozpoznaje oba warianty. Pakiet jawnie niesie zestaw modeli, a każdy
model zachowuje własny manifest, warianty runtime, progi i sumy SHA-256.

Walidacja pakietu kompletnego:

- główny ZIP ma bezpieczne ścieżki, brak duplikatów i limit rozmiaru;
- wszystkie zagnieżdżone `.alprmodel` muszą przejść walidację pojedynczego modelu;
- rola modelu musi zgadzać się z kluczem `vehicle`, `plate` albo `character`;
- główny `manifest.json` musi wskazywać pakiet i manifest boczny każdego modelu
  oraz zawierać SHA-256 obu plików.

### 9.1. Stan kompatybilności Androida

Stan na 2026-08-20: klient Android ma już drugi tor importu i obsługuje:

- pojedynczy `alpr.model.v1` dla roli `vehicle`, `plate` albo `character`;
- historyczny komplet MT+MZ z czterema etapami;
- komplet MP+MT+MZ z pięcioma etapami;
- walidację ról, zadań, manifestów bocznych, ścieżek i SHA-256;
- transakcyjną aktywację wszystkich modeli obecnych w komplecie;
- odtworzenie powiązań modeli z rejestru po restarcie;
- zachowanie dokładnego źródłowego `source.alprmodel` do raportu badawczego.

Import modelu MP nie włącza automatycznie przełącznika kaskady pojazdów.
Użytkownik decyduje w Opcjach, czy uruchomić MP → ROI → MT → MZ. Jeżeli MP nie
jest używany, MT nadal może analizować pełną klatkę.

### 9.2. Wymagania implementacyjne dla eksportera kompletnej paczki

Eksporter desktopowy ma:

1. Przyjąć wymagane żądania eksportu MT i MZ oraz opcjonalne żądanie MP.
2. Zbudować każdy model jako niezależny, poprawny `alpr.model.v1`.
3. Skopiować identyczny manifest potomny do pliku bocznego
   `models/<role>/manifest.json`.
4. Po finalnym zapisaniu plików policzyć SHA-256 pakietu potomnego i manifestu
   bocznego.
5. Utworzyć nadrzędny manifest zgodny z `alpr-package-v1.schema.json`.
6. Dla MT+MZ zapisać dokładnie cztery etapy bez `vehicle_detection`.
7. Dla MP+MT+MZ zapisać dokładnie pięć etapów, z `vehicle_detection` jako
   pierwszym etapem.
8. Zweryfikować ponownie wszystkie pakiety potomne, manifesty, role, zadania,
   ścieżki oraz sumy po zamknięciu finalnego ZIP.
9. Zapisać wynik atomowo z rozszerzeniem `.alprmodel`; błąd lub anulowanie nie
   może pozostawić częściowego pliku docelowego.

Wariant MP+MT+MZ musi używać następującej kolejności:

```json
[
  {"stage":"vehicle_detection","model":"vehicle","role":"vehicle","task":"detect"},
  {"stage":"plate_detection","model":"plate","role":"plate","task":"pose"},
  {"stage":"plate_rectification","implementation":"android_alpr_rectifier"},
  {"stage":"character_detection","model":"character","role":"character","task":"detect"},
  {"stage":"sequence_assembly","implementation":"android_alpr_sequence_decoder"}
]
```

Wariant bez MP usuwa wyłącznie pierwszy element; pozostała kolejność nie może
się zmienić.

Każdy wpis `models.<role>` ma dokładnie powiązać rolę logiczną z dwoma plikami:

```json
"vehicle": {
  "role": "vehicle",
  "task": "detect",
  "model_id": "vehicle-yolo-001",
  "schema": "alpr.model.v1",
  "package_file": "models/vehicle/model.alprmodel",
  "manifest_file": "models/vehicle/manifest.json",
  "sha256": {
    "models/vehicle/model.alprmodel": "0000000000000000000000000000000000000000000000000000000000000000",
    "models/vehicle/manifest.json": "0000000000000000000000000000000000000000000000000000000000000000"
  }
}
```

Analogiczne wpisy są wymagane dla `plate` i `character`. Klucze obiektu
`sha256` muszą być identyczne ze ścieżkami z `package_file` i `manifest_file`.
Ścieżki są względne, POSIX, bez `..`, pustych segmentów, separatorów `\` i
dwukropków. Pakiet kompletny może mieć maksymalnie 640 wpisów i 1 GiB po
rozpakowaniu.

Manifest boczny musi być semantycznie identyczny z `manifest.json` znajdującym
się wewnątrz odpowiadającego mu pakietu potomnego. Nie wystarczy zgodność
`model_id`; Android porównuje całą strukturę JSON po normalizacji kolejności
kluczy. Pola `role`, `task` i `model_id` wpisu nadrzędnego również muszą być
zgodne z manifestem potomnym.

### 9.3. Parametry per model, nie globalnie dla paczki

Komplet jest jedną paczką wdrożeniową, ale nie oznacza jednego wspólnego
zestawu parametrów inferencji. MP, MT i MZ zachowują własne konfiguracje.

Parametry, które muszą pozostać osobne dla każdego modelu:

- `imgsz` / rozmiar wejścia — MP i MT pracują na klatce/ROI, a MZ na
  wyciętej i wyprostowanej tablicy;
- `confidence_threshold` i `iou_threshold` — progi mają inne znaczenie dla
  pojazdów, tablic i ciasno ułożonych znaków;
- `runtime`, wariant wykonawczy i kwantyzacja — każdy model jest autotuningowany
  osobno;
- `calibration_data` / `data.yaml` — INT8 wymaga reprezentatywnych danych dla
  konkretnego modelu, więc MP, MT i MZ nie mogą automatycznie współdzielić
  kalibracji;
- `labels`, `class_count`, `task`, `decoder` i `output` — MT jest `pose`, a MP
  i MZ są `detect`, lecz mają odmienne klasy.

Parametry wspólne dla paczki:

- `package_id`, `name`, `version` i `created_at`;
- deklaracja pipeline'u 4- albo 5-etapowego;
- opis eksperymentu, datasetu rankingowego i datasetu kalibracyjnego, jeżeli
  dotyczą całej paczki;
- decyzja UX, że zestaw jest jednym kandydatem do uruchomienia mobilnego ALPR.

Wniosek: UI może pokazywać paczkę jako jeden komplet, ale preprocessing,
runtime, progi, dekoder, etykiety i kalibracja muszą być eksportowane per model
i wykonywane per etap pipeline'u.

Uzasadnienie dokumentacyjne:

- Ultralytics opisuje `imgsz`, `conf`, `iou`, `format`, `quantize`, `data` i `fraction` jako argumenty konkretnego modelu/trybu eksportu albo inferencji;
- TensorFlow Lite wymaga, aby dane wejsciowe byly dopasowane do ksztaltu tensora konkretnego modelu;
- pelna kwantyzacja INT8 wymaga reprezentatywnego datasetu do kalibracji zakresow aktywacji konkretnego modelu;
- literatura ALPR opisuje system jako potok etapow: lokalizacja tablicy, rektyfikacja/przetwarzanie, rozpoznanie znakow i zlozenie wyniku, wiec parametry etapow powinny byc rozdzielone.

Zrodla:

- https://docs.ultralytics.com/modes/export
- https://docs.ultralytics.com/modes/predict
- https://www.tensorflow.org/model_optimization/guide/quantization/post_training
- https://android.googlesource.com/platform/external/tensorflow/+/HEAD/tensorflow/lite/g3doc/android/quickstart.md
- https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/ipr2.12262

## 10. Proponowane API Python

Plik:

```text
auto_annotation_tool/exporters/mobile_model_exporter.py
```

```python
@dataclass(frozen=True)
class MobileExportRequest:
    checkpoint: Path
    destination: Path
    role: Literal["vehicle", "plate", "character"]
    formats: tuple[Literal["litert", "onnx", "ncnn"], ...]
    image_size: int | tuple[int, int]
    quantizations: tuple[str, ...] = ("fp32",)
    calibration_data: Path | None = None
    confidence_threshold: float = 0.25
    iou_threshold: float = 0.45


@dataclass(frozen=True)
class ExportedVariant:
    id: str
    runtime: str
    precision: str
    files: tuple[Path, ...]
    input_spec: dict
    output_spec: dict


class MobileModelExporter:
    def preflight(self, request: MobileExportRequest) -> list[str]: ...
    def export(self, request: MobileExportRequest) -> Path: ...
    def inspect_variant(self, variant: ExportedVariant) -> ExportedVariant: ...
    def validate_package(self, package_path: Path) -> None: ...


@dataclass(frozen=True)
class CompleteAlprExportRequest:
    destination: Path
    plate: MobileExportRequest
    character: MobileExportRequest
    vehicle: MobileExportRequest | None = None
    package_id: str = ""
    name: str = ""
    version: str = "1"


class CompleteAlprPackageExporter:
    def preflight(self, request: CompleteAlprExportRequest) -> list[str]: ...
    def export(self, request: CompleteAlprExportRequest) -> Path: ...
    def validate_complete_package(self, package_path: Path) -> None: ...
```

Konstruktor kompletnej paczki nie może ponownie konwertować gotowych modeli,
jeżeli otrzymał już zwalidowane artefakty potomne. Powinien jednak ponownie
sprawdzić ich manifesty i hashe przed osadzeniem w nadrzędnym ZIP.

W kompletnym pakiecie parametr `image_size`/`imgsz` pozostaje parametrem każdego
modelu z osobna. Przykładowo MP może pracować w 320×320, MT w 640×640, a MZ w
416×416. Eksporter zapisuje te wartości wyłącznie w manifestach odpowiednich
modeli potomnych.

Eksport wykonywać w katalogu tymczasowym. Plik docelowy zastąpić atomowo dopiero po przejściu wszystkich walidacji.

## 11. Walidacja

Kolejność:

1. Zweryfikować checkpoint, rolę, `model.task`, `kpt_shape` i etykiety.
2. Wyeksportować każdy wariant do katalogu tymczasowego.
3. Odczytać prawdziwe kształty i typy tensorów.
4. Wykonać inferencję kontrolną.
5. Porównać wynik z checkpointem PyTorch z tolerancją.
6. Zbudować manifest i sprawdzić go przez `jsonschema`.
7. Skopiować artefakty do docelowej struktury i policzyć SHA-256.
8. Zbudować ZIP.
9. Ponownie otworzyć ZIP, sprawdzić ścieżki, pliki i sumy.
10. Atomowo przenieść `.alprmodel` do miejsca docelowego.

Dla `alpr.package.v1` powyższy cykl należy zakończyć osobno dla każdego modelu,
a następnie wykonać drugi poziom walidacji:

1. Sprawdzić obowiązkowe MT i MZ oraz opcjonalny MP.
2. Sprawdzić pary ról i zadań: `vehicle/detect`, `plate/pose`,
   `character/detect`.
3. Zapisać manifesty boczne z tych samych obiektów JSON co manifesty wewnętrzne.
4. Policzyć hashe finalnych plików potomnych.
5. Zbudować pipeline 4- albo 5-etapowy zależnie od obecności MP.
6. Zweryfikować nadrzędny manifest przez `alpr-package-v1.schema.json`.
7. Zamknąć nadrzędny ZIP i ponownie zweryfikować wszystkie ścieżki, hashe oraz
   manifesty potomne bez korzystania z danych pozostawionych w pamięci.

Porównanie nie wymaga identyczności bitowej. Sprawdzić:

- kształty tensorów;
- brak NaN/Inf;
- zbliżoną liczbę detekcji;
- klasy najwyższych wyników;
- współrzędne z tolerancją zależną od kwantyzacji;
- dla `plate`: cztery keypointy.

## 12. Integracja z GUI Python

Punkt integracji: menu kontekstowe historii treningów obok „Eksportuj best.pt do modeli trybu swobodnego”.

Nowa akcja:

```text
Eksportuj pakiet dla klienta mobilnego (.alprmodel)
```

W widoku pozwalającym zestawić modele należy dodać drugą akcję:

```text
Eksportuj kompletny pipeline mobilny (MP/MT/MZ)
```

Modal:

- rola z runu, tylko do odczytu;
- `best.pt`, tylko do odczytu;
- LiteRT FP32 — domyślnie zaznaczone;
- LiteRT INT8 — wymaga datasetu kalibracyjnego;
- ONNX FP32 — opcjonalny wariant kontrolny/fallback;
- NCNN — opcjonalne;
- `imgsz` z runu;
- confidence i IoU;
- ścieżka `.alprmodel`.

Modal kompletnego pipeline'u:

- wymagany wybór runu/checkpointu MT (`plate + pose`);
- wymagany wybór runu/checkpointu MZ (`character + detect`);
- opcjonalny wybór runu/checkpointu MP (`vehicle + detect`);
- osobne `imgsz`, formaty, kwantyzacje, progi i dane kalibracyjne per model;
- podgląd wynikowej kolejności etapów i identyfikatorów modeli;
- `package_id`, nazwa, wersja i ścieżka docelowa;
- preflight wszystkich składowych przed rozpoczęciem konwersji;
- czytelny status: `MT+MZ` albo `MP+MT+MZ`.

Eksport uruchomić w workerze, nie blokować Tkintera. Anulowanie nie może pozostawić częściowego pliku docelowego.

## 13. Kryteria akceptacji

- Pakiety dla `plate`, `character`, `vehicle`.
- LiteRT FP32 i ONNX FP32 z tego samego checkpointu.
- LiteRT INT8 tylko z kalibracją.
- Manifest przechodzi `alpr-model-v1.schema.json`.
- Manifest kompletu przechodzi `alpr-package-v1.schema.json`.
- SHA-256 zgadza się po ponownym otwarciu ZIP.
- Eksport MT+MZ tworzy pipeline dokładnie 4-etapowy.
- Eksport MP+MT+MZ tworzy pipeline dokładnie 5-etapowy z MP na początku.
- Manifest boczny każdego modelu jest semantycznie identyczny z manifestem
  wewnątrz jego `.alprmodel`.
- Android importuje oba warianty kompletnej paczki i pojedyncze modele.
- Import kompletu z MP aktywuje MP, MT i MZ bez automatycznego włączania
  przełącznika kaskady pojazdów.
- Android wykonuje autotuning LiteRT/ONNX.
- Model tablic prowadzi do rektyfikacji z czterech narożników.
- Model znaków ma poprawną kolejność klas.
- Raport telefonu zawiera model, fingerprint i profile autotuningu.

## 14. Typowe błędy

| Objaw Androida | Przyczyna |
| --- | --- |
| Nieobsługiwany schemat | `schema` inne niż `alpr.model.v1` lub `alpr.package.v1` |
| Nieobsługiwany kompletny pipeline | błędne `kind` albo kolejność 4/5 etapów |
| Pipeline wymaga dokładnie 4/5 etapów | obecność MP nie zgadza się z `vehicle_detection` |
| Niezgodna rola modelu vehicle | MP nie ma `role: vehicle`, `task: detect` |
| Manifest boczny nie odpowiada pakietowi | sidecar nie jest identyczny z manifestem potomnym |
| Brak SHA-256 | brak sumy dla dokładnej ścieżki |
| labels != class_count | niepełne lub niesortowane `model.names` |
| Plate musi być pose | błędny checkpoint/rola |
| Manifest wejścia nie odpowiada tensorowi | błędny shape/type/layout |
| Nierozpoznane wyjście YOLO | NMS w grafie albo zły `tensor_layout` |
| Dynamiczny ONNX | `dynamic=True` |
| ONNX wymaga FLOAT32 | spakowany wariant ONNX INT8 |
| Model nie staje się aktywny | pakiet zawiera tylko NCNN |

## 15. Oficjalne źródła

- https://docs.ultralytics.com/modes/export/
- https://docs.ultralytics.com/integrations/litert/
- https://docs.ultralytics.com/integrations/onnx/
- https://docs.ultralytics.com/integrations/ncnn/
