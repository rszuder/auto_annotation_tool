# Specyfikacja dla agenta aplikacji mobilnej ALPR

Dokument jest instrukcją dla agenta rozwijającego demonstracyjną aplikację Android korzystającą z modeli trenowanych w aplikacji Python. Ma dwa cele: opisać faktyczny kontrakt eksportu `.alprmodel` oraz zebrać argumentację techniczną przydatną w pracy inżynierskiej.

Stan na dzień: 2026-08-20.

## 1. Zakres

Agent mobilny powinien traktować aplikację Python jako narzędzie treningu, wyboru i eksportu modeli. Aplikacja Android nie ma interpretować surowych checkpointów `best.pt`. Jej wejściem jest pakiet `.alprmodel`.

Zakres po stronie Androida:

- import pakietu `.alprmodel`;
- walidacja manifestu i sum kontrolnych;
- wybór obsługiwanego wariantu wykonawczego;
- uruchomienie inferencji;
- dekodowanie wyników YOLO zgodnie z rolą modelu;
- raportowanie jakości, czasu inferencji i zużycia zasobów.

Poza zakresem Androida:

- trening modeli;
- wybór datasetu treningowego;
- kalibracja INT8;
- konwersja z `best.pt` do formatów mobilnych.

## 2. Co jest już zrobione w aplikacji Python

W repozytorium desktopowym istnieje osobny tor eksportu mobilnego.

| Obszar | Status | Pliki |
| --- | --- | --- |
| Centrum eksportu mobilnego | Zaimplementowane. Dostępne z menu `Eksport -> Pakiet mobilny ALPR (.alprmodel)` oraz z kontekstu treningów. | `auto_annotation_tool/gui/app.py`, `auto_annotation_tool/gui/z4_model_export.py` |
| Eksporter pakietu | Zaimplementowany jako niezależny moduł budujący `.alprmodel`. | `auto_annotation_tool/exporters/mobile_model_exporter.py` |
| Preflight zależności | Zaimplementowany. Sprawdza checkpoint, formaty, rolę, katalog docelowy, zależności i kalibrację INT8. | `auto_annotation_tool/exporters/mobile_model_exporter.py`, `auto_annotation_tool/gui/z4_model_export.py` |
| Import katalogowy MP | Zaimplementowany w centrum eksportu. Pokazuje listę modeli Ultralytics `detect`, używa lokalnego pliku, jeśli już istnieje w katalogach programu, albo pobiera checkpoint na desktopie do `Workspace/6_models/base/detect/ultralytics`, waliduje rolę `vehicle/detect` i dodaje model jako kandydata `MP`. Klasy pojazdów są ustawiane dopiero w konfiguracji eksportu pakietu. | `auto_annotation_tool/gui/z4_model_export.py` |
| Pakiet wymiany | Zaimplementowany jako ZIP z manifestem i katalogiem `variants/`. | `auto_annotation_tool/exporters/mobile_model_exporter.py` |
| Dokument handoff | Istnieje opis kontraktu Python -> Android. | `alpr_python_exporter_handoff.md` |
| Dokument kwantyzacji | Istnieje opis formatów, kwantyzacji i parametrów inferencji. | `docs/eksport_mobilny_kwantyzacja.md` |
| Zależności eksportu | Wydzielone do osobnego pliku wymagań. | `requirements-mobile-export.txt` |

Najważniejsza decyzja: kilka zaznaczonych formatów w modalu eksportu oznacza kilka wariantów wykonawczych tego samego checkpointu w jednym pakiecie, a nie kilka różnych modeli logicznych.

## 3. Główny przepływ eksportu

1. Użytkownik trenuje model tablic `MT`, model znaków `MZ` albo wybiera gotowy model pojazdów `MP`.
2. Program zapisuje checkpoint YOLO, zwykle `best.pt`.
3. Użytkownik otwiera centrum eksportu mobilnego.
4. Użytkownik wybiera kandydata, formaty, `imgsz`, `conf`, `IoU` i ewentualnie `data.yaml` do INT8.
5. Eksporter wykonuje preflight.
6. Eksporter ładuje checkpoint przez Ultralytics YOLO.
7. Eksporter sprawdza rolę modelu, typ zadania, etykiety, liczbę klas i keypointy.
8. Eksporter tworzy warianty wykonawcze, np. TFLite FP32, TFLite INT8, ONNX FP32.
9. Eksporter sprawdza rzeczywiste tensory wejścia i wyjścia dla ONNX/TFLite.
10. Eksporter buduje `manifest.json`.
11. Eksporter liczy SHA-256 dla plików wariantów i checkpointu źródłowego.
12. Eksporter waliduje pakiet.
13. Eksporter zapisuje docelowy plik `.alprmodel` atomowo, po pełnym powodzeniu procesu.
14. Android importuje pakiet i wybiera najlepszy wariant dla urządzenia.

## 4. Format pakietu `.alprmodel`

Pakiet `.alprmodel` jest zwykłym archiwum ZIP z innym rozszerzeniem.

Eksporter Python obsluguje dwa poziomy tego kontenera:

| Schemat | Znaczenie | Kiedy uzywac |
| --- | --- | --- |
| `alpr.model.v1` | Jeden model logiczny, np. `MP`, `MT` albo `MZ`. | Test izolowany, ranking pojedynczych modeli, fallback. |
| `alpr.package.v1` | Kompletny pakiet ALPR z para `MT+MZ` albo kompletem `MP+MT+MZ` i pipeline. | Docelowy import do aplikacji demonstracyjnej oraz eksperyment end-to-end. |

Przykładowa struktura:

```text
model.alprmodel
  manifest.json
  variants/tflite/model.tflite
  variants/tflite_int8/model.tflite
  variants/onnx/model.onnx
  variants/ncnn/model.param
  variants/ncnn/model.bin
```

Android powinien importować pakiet przez bezpieczne rozpakowanie do prywatnego katalogu aplikacji. Nie wolno ufać ścieżkom z ZIP bez normalizacji.

Wariant `MP+MT+MZ` oznacza, ze model pojazdow jest juz wyeksportowany po stronie aplikacji Python. Klient mobilny nie powinien pobierac surowego YOLO ani wykonywac konwersji na telefonie; jego zadaniem jest wybor obslugiwanego wariantu z manifestu i uruchomienie gotowej inferencji.

## 5. Manifest

Manifest jest kontraktem inferencji. Android ma czytać manifest jako źródło prawdy, a nie rekonstruować parametry z nazwy pliku.

Minimalny sens pól:

| Pole | Znaczenie dla Androida |
| --- | --- |
| `schema` | Wersja kontraktu, obecnie `alpr.model.v1`. |
| `model_id` | Stabilny identyfikator modelu/pakietu w aplikacji mobilnej. |
| `name` | Nazwa prezentacyjna. |
| `version` | Wersja pakietu modelu, nie wersja architektury YOLO. |
| `role` | Rola logiczna: `plate`, `character` albo `vehicle`. |
| `task` | Typ zadania YOLO: `pose` albo `detect`. |
| `input` | Wymiary, layout, kanały, typ danych, skala i offset wejścia. |
| `output` | Dekoder, liczba klas, keypointy, progi `conf`/`IoU`, informacja o NMS. |
| `labels` | Etykiety klas w kolejności modelu. |
| `variants` | Lista plików wykonawczych i ich sumy SHA-256. |
| `source` | Pochodzenie checkpointu, hash, wersje bibliotek, liczba parametrów. |
| `training` | Metadane treningu: run, dataset, epoki, model startowy. |
| `metrics` | Metryki najlepszego checkpointu. |
| `model` | Informacje prezentacyjne, np. rodzina YOLO i liczba parametrów. |

Przykład skrócony:

```json
{
  "schema": "alpr.model.v1",
  "model_id": "MZ-260802-1603-6810",
  "name": "MZ-260802-1603-6810",
  "version": "1",
  "role": "character",
  "task": "detect",
  "input": {
    "width": 640,
    "height": 640,
    "channels": 3,
    "layout": "NHWC",
    "color": "RGB",
    "data_type": "FLOAT32",
    "scale": 0.0039215686,
    "offset": 0.0
  },
  "output": {
    "decoder": "ultralytics_detect_raw_v1",
    "class_count": 36,
    "keypoint_count": 0,
    "nms_in_graph": false,
    "confidence_threshold": 0.25,
    "iou_threshold": 0.45
  },
  "labels": ["0", "1", "2"],
  "variants": [
    {
      "id": "tflite-fp32",
      "runtime": "tflite",
      "precision": "fp32",
      "file": "variants/tflite/model.tflite",
      "sha256": {
        "variants/tflite/model.tflite": "..."
      }
    }
  ]
}
```

## 6. Role modeli

| Rola | Skrót w programie | Zadanie | Dekoder Androida | Sens |
| --- | --- | --- | --- | --- |
| `plate` | `MT` | `pose` | `ultralytics_pose_raw_v1` | Detekcja tablic i czterech punktów narożnych do rektyfikacji. |
| `character` | `MZ` | `detect` | `ultralytics_detect_raw_v1` | Detekcja ramek znaków na cropie tablicy. |
| `vehicle` | Opcjonalne | `detect` | `ultralytics_detect_raw_v1` | Detekcja pojazdu, jeśli klient mobilny będzie miał taki etap. |

Warunek krytyczny: Android nie może mieszać roli `MT` z dekoderem znaków ani roli `MZ` z dekoderem pose. Program Python waliduje to w eksporcie, ale Android powinien powtórzyć walidację przy imporcie.

Jeżeli paczka zawiera `MP`, manifest modelu `vehicle` oraz etap
`vehicle_detection` w manifeście paczki zawierają filtr klas. Klient mobilny
powinien traktować tylko `include_class_indices` jako obiekty wejściowe dla
detekcji tablic. Jeżeli indeksy nie są dostępne, należy zmapować
`include_labels` na `labels` modelu po normalizacji tekstu. `fallback_coco_class_indices`
wolno użyć wyłącznie dla standardowego modelu COCO. Detektor `MP` nie zwraca
wyniku ALPR; wskazuje regiony pojazdów, w których uruchamiany jest `MT`.

Dla `MT` Android musi dodatkowo czytać `output.keypoint_dimensions`. Model `pose` może zwracać narożniki jako `(x, y)` albo `(x, y, confidence)`, więc liczby kanałów nie wolno liczyć zawsze jako `3 * keypoint_count`. Manifest jest źródłem prawdy dla wymiaru punktu.

Agent Android musi obsłużyć również `output_format=end2end_detections`. W takim wariancie tensor ma układ `[1, max_det, 6 + keypoint_dimensions * keypoint_count]`, a pierwsze sześć wartości to `x1, y1, x2, y2, score, class_index`. To typowy wynik modeli end-to-end, np. YOLO26. Dla takiego modelu `nms_required=false`, bo model zwraca już posortowaną listę kandydatów.

## 7. Warianty wykonawcze

| Opcja w UI | Co trafia do pakietu | Status rekomendacji |
| --- | --- | --- |
| `LiteRT/TFLite FP32` | `variants/tflite/model.tflite` | Wariant główny na Androida. Najbezpieczniejszy start. |
| `LiteRT/TFLite INT8` | `variants/tflite_int8/model.tflite` | Wariant badawczy i wydajnościowy. Wymaga kalibracji. |
| `ONNX FP32` | `variants/onnx/model.onnx` | Wariant kontrolny/fallback. Dobry do diagnostyki zgodności. |
| `NCNN FP32` | `variants/ncnn/model.param` i `model.bin` | Wariant eksperymentalny, jeśli klient Android ma runtime NCNN. |

Kolejność wyboru runtime w aplikacji mobilnej powinna być jawna i mierzona. Propozycja:

1. Użyć wariantu preferowanego przez użytkownika, jeśli runtime jest dostępny.
2. Jeśli nie jest dostępny, wybrać LiteRT/TFLite FP32.
3. Jeśli TFLite nie działa, użyć ONNX FP32, o ile aplikacja ma ONNX Runtime.
4. Jeśli wariant INT8 jest dostępny, porównać go z FP32 na zestawie testowym przed oznaczeniem jako domyślny.

## 8. Parametry inferencji

| Parametr | Skąd pochodzi | Jak Android ma go użyć |
| --- | --- | --- |
| `imgsz` | UI eksportu i manifest `input`. | Preprocessing musi dopasować obraz do wymiaru wejściowego modelu. |
| `layout` | Inspekcja wariantu. | TFLite zwykle używa `NHWC`, ONNX zwykle `NCHW`; nie zgadywać. |
| `scale` i `offset` | Manifest. | Normalizacja wejścia przed inferencją. |
| `conf` | Manifest `output.confidence_threshold`. | Minimalna pewność detekcji przed NMS lub po dekodowaniu. |
| `IoU` | Manifest `output.iou_threshold`. | Próg NMS usuwający duplikaty ramek. |
| `nms_in_graph` | Manifest. | Obecnie eksport zakłada `false`; NMS wykonuje aplikacja mobilna. |

Ważne: `conf` i `IoU` są parametrami postprocessingu, a nie treningu. Zmiana tych wartości może zmienić liczbę detekcji bez zmiany samego modelu.

## 9. Jak działa eksporter w kodzie

Główna klasa:

```text
auto_annotation_tool/exporters/mobile_model_exporter.py
```

Główne API:

```python
MobileExportRequest(
    checkpoint=Path(".../best.pt"),
    destination=Path(".../model.alprmodel"),
    role="character",
    formats=("litert", "onnx"),
    image_size=640,
    quantizations=("fp32",),
    calibration_data=None,
    confidence_threshold=0.25,
    iou_threshold=0.45,
)
```

Eksporter robi preflight przed właściwym eksportem.

Sprawdzane warunki:

- checkpoint istnieje;
- ścieżka docelowa kończy się na `.alprmodel`;
- rola modelu jest obsługiwana;
- wybrano co najmniej jeden format;
- `imgsz` ma poprawną wartość;
- istnieją pakiety `ultralytics`, `torch` i `torchvision`;
- dla ONNX istnieją `onnx`, `onnxruntime`, `onnxslim`;
- dla LiteRT/TFLite istnieją `tensorflow`, `tf_keras`, `onnx2tf`, `onnx_graphsurgeon`, `sng4onnx`, `ai-edge-litert`, `onnx`, `onnxruntime`, `onnxslim`, `protobuf`;
- dla LiteRT/TFLite dostępny jest interpreter TFLite, np. `tf.lite.Interpreter`, żeby eksporter mógł sprawdzić rzeczywiste tensory po konwersji;
- dla NCNN istnieją `ncnn` i `pnnx`;
- INT8 ma wskazany dataset kalibracyjny `data.yaml`.

Preflight jest jawny i zależny od wybranego formatu. Eksporter nie powinien pozwalać, aby Ultralytics instalował pakiety automatycznie w tle, ponieważ taki mechanizm utrudnia powtarzalność eksperymentu i diagnostykę środowiska.

Eksport wariantów:

| Runtime | Wywołanie bazowe | Uwagi |
| --- | --- | --- |
| ONNX | `model.export(format="onnx", dynamic=False, simplify=True, batch=1, nms=False, device="cpu")` | Eksport statyczny, bez NMS w grafie. |
| TFLite FP32 | `model.export(format="tflite", batch=1, nms=False, device="cpu")` | W UI wariant jest opisany jako `LiteRT/TFLite`, ale Ultralytics otrzymuje realny format `tflite`. |
| TFLite INT8 | `model.export(format="tflite", int8=True, data=data_yaml, fraction=1.0, ...)` | Dataset kalibracyjny jest wymagany, ponieważ zakresy aktywacji muszą zostać wyznaczone na reprezentatywnych danych. |
| NCNN | `model.export(format="ncnn", batch=1, nms=False, device="cpu")` | Wymaga dwóch plików: `.param` i `.bin`. |

Eksporter buduje pakiet w katalogu tymczasowym i przenosi wynik atomowo dopiero po walidacji. To chroni Androida przed częściowym, uszkodzonym pakietem.

## 10. Wymagania po stronie Androida

Importer Android powinien wykonać następującą sekwencję:

1. Otworzyć `.alprmodel` jako ZIP.
2. Sprawdzić obecność `manifest.json`.
3. Zweryfikować `schema == "alpr.model.v1"`.
4. Sprawdzić, czy `role` i `task` tworzą poprawną parę.
5. Sprawdzić listę `variants`.
6. Zweryfikować, czy runtime wariantu jest wspierany przez aplikację.
7. Obliczyć SHA-256 każdego pliku wariantu.
8. Porównać SHA-256 z manifestem.
9. Rozpakować pakiet do prywatnego katalogu aplikacji.
10. Zarejestrować model w lokalnym katalogu modeli.
11. Oznaczyć wariant domyślny dopiero po poprawnym załadowaniu runtime.

Walidacja roli:

| Rola | Warunek importu |
| --- | --- |
| `plate` | `task == "pose"` oraz `keypoint_count >= 4`. |
| `character` | `task == "detect"` oraz komplet etykiet znaków. |
| `vehicle` | `task == "detect"`. |

Android nie powinien przyjmować pakietu, jeśli `labels.length != output.class_count`.

## 11. Inferencja w aplikacji mobilnej

Pipeline mobilny powinien być jawny.

Proponowany przepływ:

1. Pełny obraz z kamery trafia do modelu `MT`.
2. Model `MT` zwraca detekcję tablicy oraz punkty narożne.
3. Aplikacja rektyfikuje tablicę do cropa.
4. Crop tablicy trafia do modelu `MZ`.
5. Model `MZ` zwraca ramki znaków i klasy.
6. Aplikacja sortuje znaki w kolejności odczytu.
7. Aplikacja składa numer rejestracyjny.
8. Aplikacja prezentuje wynik i metryki czasu.

Jeżeli aplikacja ma tryb uproszczony, może importować tylko `MZ` i działać na gotowych cropach tablic. Wtedy UI powinien jasno mówić, że nie jest wykonywana detekcja tablic na pełnym obrazie.

## 12. Kwantyzacja i kalibracja

FP32 jest wariantem referencyjnym. INT8 jest wariantem eksperymentalno-wdrożeniowym.

Kalibracja INT8 polega na przepuszczeniu reprezentatywnych obrazów przez model w trakcie konwersji. Celem jest dobranie zakresów liczbowych aktywacji, których nie da się poprawnie wyznaczyć wyłącznie z wag modelu.

Dla modelu `MT` dataset kalibracyjny powinien reprezentować pełne obrazy/sceny.

Dla modelu `MZ` dataset kalibracyjny powinien reprezentować cropy tablic.

Zasada badawcza: model INT8 nie może zostać uznany za lepszy tylko dlatego, że jest szybszy. Musi przejść porównanie jakości względem FP32 na tym samym zestawie walidacyjnym.

## 13. Wersja modelu i identyfikatory

Należy rozdzielać trzy pojęcia:

| Pojęcie | Przykład | Znaczenie |
| --- | --- | --- |
| `model_id` | `MZ-260802-1603-6810` | Identyfikator pakietu/modelu w naszej aplikacji. |
| Wersja pakietu | `1` | Wersja eksportowanego pakietu/kontraktu modelu. |
| Rodzina YOLO | `YOLO26n`, `YOLOv8m` | Architektura i rozmiar modelu bazowego. |

Android powinien prezentować użytkownikowi `model_id`, rolę, rodzinę YOLO, liczbę parametrów, rozmiar wariantu i datę eksportu. Run treningowy jest pochodzeniem modelu, ale nie powinien być główną nazwą użytkową modelu.

## 14. Dokumentacja do pracy inżynierskiej

Eksport mobilny można opisać jako etap wdrożeniowy systemu ALPR, który oddziela trening od inferencji na urządzeniu brzegowym.

Teza techniczna:

```text
Ten sam wytrenowany checkpoint może zostać przekształcony do kilku wariantów wykonawczych. Warianty różnią się runtime, precyzją liczbową, rozmiarem pliku, czasem inferencji i potencjalną utratą jakości. Dzięki wspólnemu manifestowi można je porównywać w kontrolowany sposób.
```

Pełna siatka eksperymentów, w tym ranking pakietów `MT+MZ` / `MP+MT+MZ`, podział odpowiedzialności ALPR/Android i lista wykresów do pracy, znajduje się w `docs/siatka_eksperymentow_mobilnych_alpr.md`.

Uzasadnienie literaturowe metodyki, w tym relacja `wniosek -> zrodlo -> decyzja projektowa`, znajduje sie w `docs/podbudowa_literaturowa_metodyki_testow_alpr.md`.

Zmienne niezależne eksperymentu:

- format wykonawczy: TFLite, ONNX, NCNN;
- precyzja: FP32, INT8;
- rozmiar wejścia `imgsz`;
- próg detekcji `conf`;
- próg NMS `IoU`;
- runtime/delegat na urządzeniu, np. CPU, GPU, NNAPI/NPU.

Zmienne kontrolowane:

- ten sam checkpoint `best.pt`;
- ten sam zbiór testowy;
- ta sama wersja aplikacji mobilnej;
- ten sam telefon lub jawnie opisane telefony;
- ta sama procedura pomiaru czasu;
- ten sam pipeline dekodowania.

Metryki:

- rozmiar pakietu i wariantu w MB;
- czas inferencji p50, p90, p95;
- liczba FPS;
- pamięć RAM podczas inferencji;
- temperatura urządzenia, jeśli możliwa do zebrania;
- zużycie energii, jeśli możliwe do zebrania;
- precyzja, czułość, F1;
- mAP50 i mAP50-95, jeśli walidacja jest wykonywana na zbiorze z ground truth;
- liczba błędów odczytu całej tablicy;
- liczba brakujących znaków;
- liczba fałszywych znaków;
- liczba duplikatów po NMS.

Wykresy do pracy:

- rozmiar modelu kontra czas inferencji;
- jakość modelu kontra czas inferencji;
- FP32 kontra INT8 dla tego samego checkpointu;
- p50/p95 latency dla wariantów na tym samym telefonie;
- Pareto: jakość kontra koszt;
- histogram błędów OCR/znaków;
- tabela zwycięzcy z uzasadnieniem wyboru.

Wniosek wdrożeniowy powinien wybierać nie model „najładniejszy w tabeli”, lecz wariant, który znajduje się najbliżej kompromisu jakości, czasu, pamięci i stabilności.

## 15. Checklist dla agenta Android

Przed implementacją importu:

- przeczytać `alpr_python_exporter_handoff.md`;
- sprawdzić `docs/model_package_v1.md` w projekcie Android, jeśli istnieje;
- nie implementować importu surowego `best.pt`;
- traktować `.alprmodel` jako jedyny kontrakt wymiany;
- nie zgadywać layoutu tensorów;
- nie zgadywać progów `conf` i `IoU`;
- nie ufać rozszerzeniu pliku bez walidacji ZIP i manifestu;
- nie wybierać INT8 jako domyślnego bez testu jakości.

Po implementacji importu:

- zaimportować pakiet MZ;
- zaimportować pakiet MT;
- sprawdzić SHA-256;
- wyświetlić metadane modelu;
- uruchomić inferencję testową;
- porównać wynik TFLite FP32 z ONNX FP32;
- jeśli istnieje INT8, porównać INT8 z FP32;
- zapisać raport pomiaru.

## 16. Minimalne kryteria akceptacji

| Obszar | Kryterium |
| --- | --- |
| Import | Android importuje `.alprmodel` i odrzuca uszkodzony ZIP. |
| Manifest | Android sprawdza `schema`, `role`, `task`, `labels`, `variants`, `sha256`. |
| Runtime | Android uruchamia co najmniej TFLite FP32. |
| Fallback | Brak obsługi wariantu nie psuje importu całego pakietu. |
| Dekoder | `MT` i `MZ` mają osobne ścieżki dekodowania. |
| Raport | Aplikacja zapisuje czas inferencji, wariant, urządzenie i wersję modelu. |
| UI | Użytkownik widzi model, rolę, format, precyzję, datę eksportu i status importu. |

## 17. Miejsca w kodzie Python

| Plik | Znaczenie |
| --- | --- |
| `auto_annotation_tool/gui/app.py` | Dodaje wejście z menu głównego do centrum eksportu mobilnego. |
| `auto_annotation_tool/gui/z4_model_export.py` | Buduje modal eksportu, listę kandydatów, formularz formatów i preflight. |
| `auto_annotation_tool/exporters/mobile_model_exporter.py` | Buduje pojedynczy `.alprmodel` oraz kompletny pakiet `alpr.package.v1` z para `MT+MZ` albo kaskada `MP+MT+MZ`. |
| `auto_annotation_tool/ranking/mobile_package_experiments.py` | Opisuje eksperyment pakietu `MT+MZ` / `MP+MT+MZ`, raport z Androida i punktację mobilną. |
| `auto_annotation_tool/exporters/__init__.py` | Eksportuje API modułu mobilnego. |
| `requirements-mobile-export.txt` | Zależności potrzebne do konwersji mobilnej. |
| `alpr_python_exporter_handoff.md` | Kontrakt szczegółowy między Pythonem i Androidem. |
| `docs/eksport_mobilny_kwantyzacja.md` | Uzasadnienie formatów, kwantyzacji i parametrów inferencji. |
| `docs/podbudowa_literaturowa_metodyki_testow_alpr.md` | Literaturowa podbudowa metodyki testow i wiarygodnosci wynikow. |

## 18. Literatura i źródła

Poniższe pozycje są źródłami, na których opierają się wnioski o eksporcie, kwantyzacji, benchmarkach i metrykach. Lista łączy dokumentację oficjalną z literaturą naukową, ponieważ część pracy ma charakter inżyniersko-wdrożeniowy, a część badawczy.

### Źródła wdrożeniowe

| Kod | Źródło | Wykorzystanie w projekcie |
| --- | --- | --- |
| [U1] | Ultralytics, `Model Export with Ultralytics YOLO`, https://docs.ultralytics.com/modes/export/ | Uzasadnienie eksportu checkpointu YOLO do formatów wdrożeniowych, lista formatów, parametry `imgsz`, `conf`, `iou`, `nms`, `batch`, `device`, `data`, `fraction`, `quantize`. |
| [U2] | TensorFlow Lite, `Post-training quantization`, https://github.com/tensorflow/tensorflow/blob/master/tensorflow/lite/g3doc/performance/post_training_quantization.md | Uzasadnienie kalibracji INT8 na reprezentatywnym zbiorze danych i rozdzielenia FP32 jako wariantu referencyjnego od INT8 jako wariantu zoptymalizowanego. |
| [U3] | ONNX Runtime, `Mobile`, https://onnxruntime.ai/docs/tutorials/mobile/ | Uzasadnienie wariantu ONNX jako ścieżki kontrolnej/fallback na urządzeniu mobilnym. |
| [U4] | ONNX Runtime, `Get started with ONNX Runtime mobile`, https://onnxruntime.ai/docs/get-started/with-mobile.html | Uzasadnienie sprawdzania rozmiaru modelu, pamięci i kompatybilności runtime na urządzeniu. |
| [U5] | Google AI Edge LiteRT, `NPU delegates`, https://ai.google.dev/edge/litert/android/npu | Uzasadnienie testowania różnych delegatów sprzętowych Androida, ponieważ wydajność zależy od telefonu, NPU i stosu wykonawczego. |

### Literatura naukowa

| Kod | Publikacja | Wykorzystanie w projekcie |
| --- | --- | --- |
| [L1] | Redmon, J., Divvala, S., Girshick, R., Farhadi, A. (2016). `You Only Look Once: Unified, Real-Time Object Detection`. CVPR 2016, 779-788. DOI: 10.1109/CVPR.2016.91. https://openaccess.thecvf.com/content_cvpr_2016/html/Redmon_You_Only_Look_CVPR_2016_paper.html | Podstawa teoretyczna dla jednoprzebiegowej detekcji obiektów i wymogu pomiaru szybkości inferencji. |
| [L2] | Jacob, B., Kligys, S., Chen, B., Zhu, M., Tang, M., Howard, A., Adam, H., Kalenichenko, D. (2018). `Quantization and Training of Neural Networks for Efficient Integer-Arithmetic-Only Inference`. CVPR 2018, 2704-2713. DOI: 10.1109/CVPR.2018.00286. https://openaccess.thecvf.com/content_cvpr_2018/html/Jacob_Quantization_and_Training_CVPR_2018_paper.html | Podstawa dla tezy, że INT8 może zmniejszyć koszt pamięciowy i przyspieszyć inferencję na sprzęcie mobilnym, ale wymaga weryfikacji jakości. |
| [L3] | Nagel, M., Fournarakis, M., Amjad, R. A., Bondarenko, Y., van Baalen, M., Blankevoort, T. (2021). `A White Paper on Neural Network Quantization`. arXiv:2106.08295. DOI: 10.48550/arXiv.2106.08295. https://arxiv.org/abs/2106.08295 | Uporządkowanie pojęć PTQ/QAT, ryzyk degradacji jakości i potrzeby porównywania modeli po kwantyzacji z wariantem FP32. |
| [L4] | Janapa Reddi, V. et al. (2022). `MLPerf Mobile Inference Benchmark: An Industry-Standard Open-Source Machine Learning Benchmark for On-Device AI`. Proceedings of Machine Learning and Systems, 4, 352-369. https://proceedings.mlsys.org/paper_files/paper/2022/hash/a2b2702ea7e682c5ea2c20e8f71efb0c-Abstract.html | Podstawa dla modelu testów mobilnych: mierzyć jednocześnie szybkość, jakość, urządzenie, runtime i reguły przebiegu eksperymentu. |
| [L5] | Mattson, P. et al. (2020). `MLPerf: An Industry Standard Benchmark Suite for Machine Learning Performance`. IEEE Micro, 40(2), 8-16. DOI: 10.1109/MM.2020.2974843. https://doi.org/10.1109/MM.2020.2974843 | Uzasadnienie potrzeby powtarzalnej procedury benchmarkowej zamiast pojedynczego, ręcznego pomiaru. |
| [L6] | Lin, T.-Y. et al. (2014). `Microsoft COCO: Common Objects in Context`. ECCV 2014, 740-755. DOI: 10.1007/978-3-319-10602-1_48. https://mlanthology.org/eccv/2014/lin2014eccv-microsoft/ | Kontekst metryk detekcji, IoU, mAP i oceny lokalizacji obiektów. |
| [L7] | Sokolova, M., Lapalme, G. (2009). `A systematic analysis of performance measures for classification tasks`. Information Processing and Management, 45(4), 427-437. DOI: 10.1016/j.ipm.2009.03.002. https://dblp.org/rec/journals/ipm/SokolovaL09.html | Uzasadnienie raportowania precyzji, czułości i F1 zamiast polegania na jednej zagregowanej metryce. |

## 19. Powiązanie wniosków z literaturą

| Wniosek projektowy | Uzasadnienie | Źródła |
| --- | --- | --- |
| Android powinien importować `.alprmodel`, a nie surowe `best.pt`. | Checkpoint treningowy jest artefaktem PyTorch/Ultralytics, a aplikacja mobilna potrzebuje formatu zgodnego z runtime na urządzeniu. | [U1], [U3], [U5] |
| Jeden pakiet może zawierać kilka wariantów tego samego modelu. | Różne formaty i precyzje mają różny koszt pamięci, opóźnienie i kompatybilność sprzętową, więc powinny być porównywane jako warianty jednego checkpointu. | [U1], [L4], [L5] |
| FP32 jest wariantem referencyjnym, a INT8 wariantem badawczym/wdrożeniowym. | Kwantyzacja może przyspieszyć inferencję i zmniejszyć model, ale może też pogorszyć jakość, więc wymaga pomiaru względem FP32. | [U2], [L2], [L3] |
| INT8 wymaga reprezentatywnej kalibracji. | Zakresy aktywacji zależą od danych wejściowych, dlatego kalibracja musi używać obrazów podobnych do danych docelowych. | [U1], [U2], [L2], [L3] |
| Ranking mobilny nie może opierać się tylko na mAP. | Model na telefonie musi spełniać kompromis jakości, latencji, pamięci i stabilności runtime. | [L4], [L5], [U4], [U5] |
| `conf` i `IoU` muszą być zapisane w manifeście. | Są częścią postprocessingu i wpływają na liczbę detekcji, fałszywe alarmy oraz duplikaty ramek. | [U1], [L6] |
| Należy raportować precyzję, czułość i F1. | Jedna metryka może ukrywać charakter błędów; w ALPR różnica między brakiem znaku a fałszywym znakiem jest praktycznie istotna. | [L7] |
| W eksperymencie trzeba kontrolować dataset, urządzenie i runtime. | Bez tej kontroli nie da się przypisać różnic wyników konkretnemu formatowi lub kwantyzacji. | [L4], [L5] |

Najważniejsze uzasadnienie z dokumentacji: eksport modeli jest standardowym etapem wdrożenia poza PyTorch, kwantyzacja INT8 wymaga reprezentatywnej kalibracji, a wybór runtime na Androidzie zależy od sprzętu i dostępnych delegatów. Dlatego nasz pakiet ma manifest i wiele wariantów wykonawczych zamiast pojedynczego pliku modelu bez kontekstu.
