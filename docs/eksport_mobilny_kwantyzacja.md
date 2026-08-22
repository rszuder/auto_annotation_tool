# Eksport mobilny, kwantyzacja i parametry inferencji

Dokument opisuje sens opcji widocznych w modalu eksportu modeli do klienta mobilnego ALPR. Celem nie jest opis implementacji GUI, lecz uzasadnienie decyzji projektowych potrzebne do pracy inżynierskiej i do późniejszej interpretacji wyników eksperymentalnych.

## 1. Cel eksportu mobilnego

Model trenowany w aplikacji powstaje jako checkpoint YOLO, najczęściej `best.pt`. Taki plik jest wygodny w środowisku Python/PyTorch, ale nie jest właściwym formatem wdrożeniowym dla aplikacji Android.

Eksport mobilny tworzy pakiet `.alprmodel`, czyli zwykły pakiet ZIP z manifestem i jednym lub wieloma wariantami wykonawczymi modelu.

Pakiet mobilny zawiera:

- `manifest.json` z kontraktem inferencji;
- warianty modelu, np. `LiteRT/TFLite`, `ONNX`, opcjonalnie `NCNN`;
- metadane modelu, roli i zadania;
- progi dekodera, np. `conf` i `IoU`;
- specyfikację wejścia i wyjścia modelu;
- sumy kontrolne SHA-256.

Ważne: zaznaczenie kilku formatów w prawym panelu eksportu oznacza kilka wariantów tego samego checkpointu `best.pt` w jednym pakiecie `.alprmodel`, a nie kilka różnych modeli logicznych.

Przykład:

```text
model.alprmodel
  manifest.json
  variants/tflite/model.tflite
  variants/onnx/model.onnx
```

Telefon może później wybrać najlepszy wariant dla danego urządzenia, np. `LiteRT/TFLite` jako ścieżkę główną, a `ONNX` jako fallback albo wariant kontrolny.

Eksport ma teraz dwa poziomy:

- `alpr.model.v1` - pojedynczy model logiczny, np. tylko `MP`, `MT` albo `MZ`;
- `alpr.package.v1` - kompletny pakiet ALPR, ktory zawiera jawna pare `MT+MZ` albo pelny komplet `MP+MT+MZ` i opis pipeline mobilnego.

To rozdzielenie jest celowe. Pojedynczy model nadal jest potrzebny do diagnostyki, rankingu i testow izolowanych, ale eksperyment wdrozeniowy na Androidzie powinien oceniac kompletny zestaw `MT+MZ` albo `MP+MT+MZ`, bo dopiero taki zestaw realizuje pelne rozpoznanie tablicy na obrazie. Model pojazdow `MP` jest przygotowywany w aplikacji desktopowej, jezeli ma byc czescia kaskady; telefon nie powinien pobierac surowego YOLO i konwertowac go lokalnie.

## 2. Znaczenie prawego panelu eksportu

### Run, rola i checkpoint

Sekcja `Run / Rola / Checkpoint` identyfikuje źródło eksportu.

| Pole | Znaczenie | Cel w inferencji mobilnej |
| --- | --- | --- |
| `Run` | Proces treningowy, z którego pochodzi model. | Umożliwia odtworzenie pochodzenia modelu i powiązanie wyniku z eksperymentem. |
| `Rola` | Typ modelu, np. model tablic `MT` albo model znaków `MZ`. | Telefon musi wiedzieć, jak dekodować wynik: detekcja znaków i detekcja tablic mają inną semantykę. |
| `Checkpoint` | Konkretny plik wag, zwykle `best.pt`. | Wszystkie eksportowane warianty muszą pochodzić z tego samego checkpointu, aby porównanie formatów było uczciwe. |

### Formaty

| Opcja | Co powstaje | Sens praktyczny |
| --- | --- | --- |
| `LiteRT/TFLite FP32` | Model `.tflite` bez kwantyzacji INT8. | Najbezpieczniejszy wariant mobilny. Zwykle najlepszy punkt startowy dla Androida. |
| `LiteRT/TFLite INT8` | Model `.tflite` po kwantyzacji INT8. | Mniejszy model, potencjalnie szybszy i oszczędniejszy energetycznie, ale wymaga dobrej kalibracji. |
| `ONNX FP32` | Model `.onnx`. | Wariant kontrolny/fallback, wygodny do diagnostyki i porównywania z oryginalnym modelem. |
| `NCNN` | Pliki `.param` i `.bin`. | Wariant eksperymentalny dla runtime NCNN. Nie powinien być jedynym formatem pakietu. |

Rekomendacja wdrożeniowa:

- minimum: `LiteRT/TFLite FP32 + ONNX FP32`;
- wariant badawczy: dodać `LiteRT/TFLite INT8` i porównać jakość oraz szybkość z FP32;
- `NCNN` traktować jako wariant dodatkowy, dopóki klient mobilny nie ma pełnej ścieżki wykonawczej NCNN.

### Jak wybierac formaty swiadomie

Eksport kilku formatow ma sens wtedy, gdy porownujemy warianty wykonawcze tego
samego checkpointu albo chcemy zostawic aplikacji mobilnej bezpieczny fallback.
Nie powinien byc domyslnym mnozeniem artefaktow bez celu.

Model decyzyjny:

| Cel uzytkownika | Zalecany wybor | Sens |
| --- | --- | --- |
| stabilna demonstracja Android | `LiteRT/TFLite FP32` | najprostszy i najbezpieczniejszy wariant mobilny |
| porownanie badawcze runtime | `LiteRT/TFLite FP32 + ONNX FP32` | porownujemy TFLite z niezaleznym wariantem kontrolnym |
| test rozmiaru i szybkosci | `LiteRT/TFLite FP32 + LiteRT/TFLite INT8` | sprawdzamy, czy kwantyzacja daje zysk bez istotnej utraty jakosci |
| eksperyment embedded/mobile | `NCNN FP32` jako dodatek | sensowne dopiero po implementacji runtime NCNN w kliencie |

Wniosek: finalny wariant domyslny powinien wynikac z pomiaru na telefonie:
czas inferencji, rozmiar modelu, zgodnosc dekodera, stabilnosc oraz metryki
jakosci. Sam fakt, ze wariant jest mniejszy albo teoretycznie szybszy, nie
wystarcza do uznania go za najlepszy.

### Parametry eksportu

| Parametr | Znaczenie | Wpływ na telefon |
| --- | --- | --- |
| `imgsz` | Rozmiar wejścia modelu, np. `640`. | Większy obraz może poprawić detekcję małych znaków, ale zwiększa czas obliczeń, RAM i zużycie energii. |
| `conf` | Minimalna pewność detekcji. | Niższy próg daje więcej wykryć, ale więcej fałszywych alarmów. Wyższy próg ogranicza śmieci, ale może usuwać słabe prawidłowe detekcje. |
| `IoU` | Próg NMS do usuwania nakładających się detekcji. | Zbyt niski może usuwać sąsiednie znaki, zbyt wysoki może zostawiać duplikaty ramek. |

Parametry `conf` i `IoU` trafiają do manifestu, ponieważ telefon wykonuje własne post-processing/NMS. Dzięki temu aplikacja mobilna nie musi zgadywać progów użytych podczas eksperymentu.

### Kalibracja INT8

Pole `data.yaml` jest używane tylko dla wariantu `LiteRT/TFLite INT8`.

Kalibracja nie jest treningiem. Jest etapem pomiarowym wykonywanym po treningu, podczas konwersji modelu FP32 do INT8.

Proces:

1. Eksporter otrzymuje wytrenowany model FP32.
2. Użytkownik wskazuje `data.yaml` opisujący reprezentatywny zbiór obrazów.
3. Konwerter przepuszcza próbkę obrazów przez model.
4. Dla tensorów i aktywacji mierzone są typowe zakresy wartości.
5. Na podstawie tych zakresów wartości FP32 są mapowane na zakres INT8.
6. Powstaje mniejszy model `.tflite`.

Uzasadnienie: sama konwersja wag nie wystarcza. W trakcie pracy modelu powstają wartości pośrednie zależne od obrazu wejściowego. Żeby ograniczyć stratę jakości, konwerter musi zobaczyć obrazy podobne do tych, które model zobaczy na telefonie.

Dla modelu znaków kalibracja powinna używać cropów tablic podobnych do docelowych danych mobilnych. Dla modelu tablic powinna używać pełnych obrazów/scen podobnych do tych, które trafią z kamery telefonu.

### Zależności eksportu i jawne importy kontrolne

Eksport mobilny nie jest zwykłym kopiowaniem pliku `best.pt`. Jest etapem konwersji checkpointu treningowego do formatów wykonawczych, które mogą działać poza środowiskiem PyTorch. Dlatego aplikacja sprawdza zależności przed eksportem, a nie dopiero po wystąpieniu błędu konwertera.

Jawny preflight ma trzy cele:

- potwierdzić, że checkpoint YOLO można wczytać w bieżącym środowisku;
- sprawdzić tylko te biblioteki, które są potrzebne do aktualnie wybranych formatów eksportu;
- zatrzymać ukryte, automatyczne instalowanie zależności przez biblioteki narzędziowe.

To jest ważne metodologicznie. Jeżeli środowisko badawcze zmienia się samoczynnie w trakcie eksperymentu, wynik eksportu i późniejszy pomiar mobilny są trudniejsze do odtworzenia. Jawna lista zależności, preflight, instalacja krok po kroku i ponowna walidacja środowiska pozwalają opisać eksport jako powtarzalny etap przygotowania artefaktu.

Uzasadnienie poszczególnych zależności:

| Zależność | Dlaczego jest importowana lub sprawdzana | Zakres |
| --- | --- | --- |
| `ultralytics` | Ładuje checkpoint YOLO i udostępnia `model.export(...)`. | Wspólne dla wszystkich formatów. |
| `torch` | Checkpoint `best.pt` jest artefaktem PyTorch. Bez poprawnego `torch` nie można go wiarygodnie odczytać. | Wspólne dla wszystkich formatów. |
| `torchvision` | Musi być zgodne z `torch`; niespójność wersji potrafi ujawnić się dopiero przy imporcie Ultralytics albo operatorów detekcyjnych. | Wspólne dla wszystkich formatów. |
| `onnx` | Reprezentuje model w standardzie ONNX i pozwala odczytać strukturę grafu. | ONNX, TFLite pośrednio. |
| `onnxruntime` | Pozwala sprawdzić wariant ONNX i bywa wymagany przez ścieżki konwersji. | ONNX, TFLite pośrednio. |
| `onnxslim` | Upraszcza graf ONNX, co zmniejsza ryzyko problemów z runtime mobilnym. | ONNX, TFLite pośrednio. |
| `tensorflow` i `tf_keras` | Są używane w ścieżce konwersji i inspekcji TFLite. | LiteRT/TFLite. |
| `onnx2tf`, `onnx_graphsurgeon`, `sng4onnx` | Tworzą techniczny most między reprezentacją ONNX/TensorFlow/TFLite. | LiteRT/TFLite. |
| `ai-edge-litert` | Dostarcza aktualne komponenty Google AI Edge/LiteRT wymagane przez eksport TFLite. | LiteRT/TFLite. |
| `protobuf` | Serializuje grafy i metadane używane przez TensorFlow oraz ONNX. | LiteRT/TFLite, ONNX. |
| `jsonschema` | Waliduje `manifest.json`, czyli kontrakt importu dla Androida. | Pakiet `.alprmodel`. |
| `ncnn` i `pnnx` | Są wymagane tylko dla wariantu NCNN, traktowanego jako opcjonalny runtime eksperymentalny. | NCNN. |

W UI nazwa `LiteRT/TFLite` opisuje docelowy wariant dla Androida. W wywołaniu Ultralytics używany jest format `tflite`, ponieważ to jest nazwa obsługiwana przez lokalną wersję biblioteki. Dzięki temu unikamy ostrzeżenia o niepoprawnym formacie i nie pozwalamy, aby Ultralytics samoczynnie uruchamiał instalację brakujących pakietów w tle.

Po eksporcie plik `.tflite` jest otwierany przez interpreter TFLite, zwykle `tf.lite.Interpreter`. Ten krok nie służy inferencji w aplikacji desktopowej. Jego celem jest odczyt rzeczywistego kształtu wejścia, wyjścia, typu danych i parametrów kwantyzacji. Dzięki temu manifest pakietu `.alprmodel` opisuje faktycznie powstały model, a nie tylko założenia eksportera.

W modelach tablic `pose` manifest zapisuje nie tylko liczbę keypointów, ale też `keypoint_dimensions`. To pole jest konieczne, bo różne eksporty YOLO mogą zwrócić punkty jako `(x, y)` albo `(x, y, confidence)`. Przykładowo model z jedną klasą, czterema narożnikami i `keypoint_dimensions=2` może mieć wyjście `[1, 300, 14]`: `4` współrzędne ramki, `1` objectness, `1` klasa i `8` wartości narożników. Android musi czytać ten parametr z manifestu, a nie zakładać stałego wzoru `3 * keypoint_count`.

Część modeli YOLO, w tym modele end-to-end, może zwracać wyjście w formacie gotowych detekcji. Dla modelu znaków przykładowy kształt `[1, 300, 6]` oznacza `300` najlepszych detekcji, a ostatni wymiar to `x1, y1, x2, y2, score, class_index`. Taki wariant w manifeście ma `output_format=end2end_detections`, `box_format=xyxy` i `nms_required=false`. Nie należy wtedy oczekiwać `4 + class_count` kanałów ani wykonywać drugiego NMS na telefonie.

## 3. Kwantyzacja

Kwantyzacja to zamiana reprezentacji liczbowej modelu na mniej kosztowną obliczeniowo.

W modelu FP32 liczby są zapisywane jako 32-bitowe liczby zmiennoprzecinkowe. W modelu INT8 część obliczeń wykonywana jest na liczbach 8-bitowych. Typowe przybliżenie można zapisać jako:

```text
q = round(x / scale) + zero_point
```

gdzie:

- `x` to wartość zmiennoprzecinkowa;
- `q` to wartość skwantyzowana;
- `scale` opisuje krok skali;
- `zero_point` przesuwa zakres liczbowy.

### FP32

FP32 jest wariantem bazowym.

Zalety:

- najwyższa zgodność z oryginalnym checkpointem;
- najłatwiejsza diagnostyka;
- najniższe ryzyko degradacji jakości.

Wady:

- większy plik;
- większe zużycie pamięci;
- potencjalnie wolniejsza inferencja.

### FP16

FP16 oznacza 16-bitowe liczby zmiennoprzecinkowe. Nie należy mylić go z INT16.

Zalety:

- mniejszy model niż FP32;
- często korzystny na GPU;
- zwykle mniej ryzykowny jakościowo niż INT8.

Ograniczenie w naszym obecnym torze: osobny eksport `LiteRT FP16` nie jest podstawowym wariantem GUI. W praktyce część runtime może wykonywać obliczenia z obniżoną precyzją na wariancie FP32 przez delegata GPU.

### INT8

INT8 jest głównym wariantem kwantyzacji dla urządzeń brzegowych.

Zalety:

- mniejszy plik;
- potencjalnie mniejsze zużycie RAM;
- potencjalnie szybsza inferencja;
- możliwie mniejsze zużycie energii.

Ryzyka:

- możliwa utrata dokładności;
- silna zależność od jakości kalibracji;
- nie każdy operator i delegat zachowuje się identycznie na każdym telefonie.

Wniosek: INT8 powinien być wariantem badawczo-wdrożeniowym, ale nie jedynym wariantem pakietu.

### W8A16 i INT16

Pojęcie `INT16` bywa mylące. W kontekście eksportu Ultralytics/LiteRT praktycznie istotny jest raczej wariant mieszany `W8A16`, czyli:

- wagi modelu w 8 bitach;
- aktywacje w 16 bitach.

Taki wariant może być kompromisem między rozmiarem a dokładnością, ale obecnie nie jest podstawową opcją naszego GUI. Może zostać dopisany jako wariant eksperymentalny po potwierdzeniu obsługi po stronie eksportera i klienta Android.

## 4. Uzasadnienie wielu wariantów w jednym pakiecie

W pracy inżynierskiej ważne jest, aby porównywać formaty wykonawcze uczciwie. Dlatego kilka zaznaczonych formatów powinno pochodzić z tego samego checkpointu.

Jeżeli `LiteRT FP32`, `LiteRT INT8` i `ONNX FP32` powstają z tego samego `best.pt`, to różnice w wynikach można przypisać głównie formatowi, runtime albo kwantyzacji, a nie różnemu treningowi.

To pozwala badać:

- rozmiar modelu;
- czas inferencji;
- wpływ kwantyzacji na jakość;
- stabilność detekcji na telefonie;
- różnice między runtime;
- koszt energetyczny i pamięciowy.

## 5. Proponowana metodyka badań

Dla pracy inżynierskiej sugerowany schemat eksperymentu:

1. Wybrać jeden model źródłowy `best.pt`.
2. Wyeksportować warianty: `LiteRT FP32`, `ONNX FP32`, opcjonalnie `LiteRT INT8`.
3. Dla INT8 użyć reprezentatywnego `data.yaml`.
4. Uruchomić inferencję na tym samym zbiorze testowym.
5. Porównać:
   - jakość detekcji;
   - liczbę błędów;
   - czas inferencji;
   - rozmiar pakietu;
   - stabilność działania na telefonie.
6. Dla INT8 osobno ocenić, czy spadek jakości jest akceptowalny względem zysku szybkości i rozmiaru.

Wniosek projektowy powinien być formułowany nie jako "INT8 jest lepszy", tylko jako relacja:

```text
wariant formatu -> koszt obliczeniowy -> jakość inferencji -> użyteczność na smartfonie
```

Rozszerzona metodyka wyboru kompletnego pakietu `MT+MZ` / `MP+MT+MZ`, zakres odpowiedzialności aplikacji desktopowej i mobilnej oraz lista wykresów do rozdziału wynikowego są opisane w `docs/siatka_eksperymentow_mobilnych_alpr.md`.

## 6. Źródła

- Ultralytics, dokumentacja eksportu YOLO: https://docs.ultralytics.com/modes/export/
- TensorFlow, post-training quantization: https://www.tensorflow.org/model_optimization/guide/quantization/post_training
- Google AI Edge, LiteRT delegates: https://developers.google.com/edge/litert/performance/delegates
- Lokalny kontrakt projektu: `alpr_python_exporter_handoff.md`

Szczegółowa bibliografia i mapa `wniosek -> źródło` są w dokumencie:

- `docs/specyfikacja_agenta_aplikacji_mobilnej_alpr.md`
- `docs/podbudowa_literaturowa_metodyki_testow_alpr.md`

Kluczowa literatura naukowa użyta do uzasadnienia decyzji:

- Redmon, J., Divvala, S., Girshick, R., Farhadi, A. (2016). `You Only Look Once: Unified, Real-Time Object Detection`. CVPR 2016. DOI: 10.1109/CVPR.2016.91.
- Jacob, B. et al. (2018). `Quantization and Training of Neural Networks for Efficient Integer-Arithmetic-Only Inference`. CVPR 2018. DOI: 10.1109/CVPR.2018.00286.
- Nagel, M. et al. (2021). `A White Paper on Neural Network Quantization`. arXiv:2106.08295. DOI: 10.48550/arXiv.2106.08295.
- Janapa Reddi, V. et al. (2022). `MLPerf Mobile Inference Benchmark: An Industry-Standard Open-Source Machine Learning Benchmark for On-Device AI`. Proceedings of Machine Learning and Systems, 4, 352-369.
- Lin, T.-Y. et al. (2014). `Microsoft COCO: Common Objects in Context`. ECCV 2014. DOI: 10.1007/978-3-319-10602-1_48.
- Sokolova, M., Lapalme, G. (2009). `A systematic analysis of performance measures for classification tasks`. Information Processing and Management, 45(4), 427-437. DOI: 10.1016/j.ipm.2009.03.002.
