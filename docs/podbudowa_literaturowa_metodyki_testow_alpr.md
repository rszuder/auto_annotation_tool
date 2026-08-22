# Podbudowa literaturowa metodyki testow ALPR

Stan na dzien: 2026-08-19.

Dokument wyjasnia, z czego wynika wiarygodnosc planowanej siatki eksperymentow dla desktopowego ALPR i aplikacji mobilnej Android. Ma byc pomostem pomiedzy literatura, oficjalna dokumentacja runtime i naszym praktycznym planem badan.

## 1. Glowna teza metodyczna

Wynik testu jest wiarygodny dopiero wtedy, gdy wiadomo:

- jaki dokladnie model lub pakiet byl testowany;
- na jakim zbiorze danych byl testowany;
- czy zbior testowy nie byl uzyty do wyboru modelu;
- jakie parametry inferencji byly stale;
- na jakim urzadzeniu i runtime wykonano pomiar;
- czy wynik mozna powtorzyc;
- czy raportujemy nie tylko jakosc, ale tez koszt wdrozenia: czas, pamiec, rozmiar i stabilnosc.

Dla naszego projektu oznacza to, ze ranking finalny nie moze byc zwykla lista modeli posortowana po `mAP`. Musi byc rankingiem pakietow `MT+MZ` albo `MP+MT+MZ`, sprawdzonych na wspolnym torze testowym i pozniej zmierzonych na telefonie.

## 2. Podzial danych: trening, walidacja, ranking i test koncowy

Najwazniejsza zasada wynika z praktyk benchmarkow detekcji obiektow, m.in. PASCAL VOC: zbior testowy sluzy do raportowania wyniku, a nie do strojenia parametrow lub wybierania najlepszej konfiguracji. Jezeli test jest uzywany wielokrotnie do wyboru modelu, przestaje byc niezaleznym sprawdzianem.

Przeklad na nasz projekt:

| Zbior | Rola | Czy wolno na nim wybierac model |
| --- | --- | --- |
| `train` | uczenie wag | tak, posrednio przez trening |
| `val` | wybor epoki `best.pt` i kontrola treningu | tak, w ramach treningu |
| `ranking` | porownanie kandydatow po treningu | tak, to tor wyboru |
| `mobile_benchmark` | pomiar zachowania pakietu na telefonie | tak, dla wyboru runtime/pakietu |
| `final_test` | koncowa ocena do pracy | nie, tylko raport koncowy |

Dlaczego to jest wazne: dzieki temu mozemy uczciwie napisac, ze finalny wynik nie jest efektem przypadkowego "dopasowania sie" do jednego zbioru testowego.

## 3. Metryki detekcji: IoU, AP, mAP, precision, recall, F1

Detekcja tablic i znakow jest zadaniem lokalizacji obiektow. Literatura i benchmarki detekcji standardowo oceniaja:

- czy obiekt zostal wykryty;
- czy klasa jest poprawna;
- czy polozenie predykcji zgadza sie z anotacja referencyjna;
- jak zmienia sie wynik przy roznych progach pewnosci i IoU.

PASCAL VOC daje klasyczny model `TP/FP/FN`, precision, recall i AP dla detekcji. COCO rozszerza ocene przez uzywanie wielu progow IoU, np. `0.50:0.05:0.95`, co lepiej karze niedokladna lokalizacje.

Przeklad na nasz projekt:

| Element ALPR | Metryki obowiazkowe | Sens |
| --- | --- | --- |
| `MT`, model tablic | `mAP50`, `mAP50-95`, precision, recall, F1 | czy tablica i narozniki sa wykrywane stabilnie |
| `MZ`, model znakow | `mAP50`, `mAP50-95`, precision, recall, F1 | czy znaki sa lokalizowane bez brakow i duplikatow |
| progi `conf`/`IoU` | krzywe precision-recall, liczba FP/FN | czy prog nie usuwa prawidlowych znakow albo nie zostawia smieci |

Wniosek: `mAP50-95` powinien byc wazniejszy niz samo `mAP50`, bo w ALPR lokalizacja znaku i naroznika ma znaczenie praktyczne. Luzno trafiona ramka moze wygladac dobrze w `mAP50`, ale popsuc rektyfikacje albo kolejnosc znakow.

## 4. Metryki rozpoznawania sekwencji: accuracy calej tablicy i CER

ALPR nie konczy sie na ramkach. Uzytkownika interesuje numer rejestracyjny. Dlatego potrzebujemy dwoch poziomow oceny:

| Metryka | Co mierzy | Dlaczego potrzebna |
| --- | --- | --- |
| dokladnosc calej tablicy | odsetek tablic rozpoznanych idealnie | najbardziej naturalna miara biznesowa: numer jest poprawny albo nie |
| `CER` | blad znakowy oparty o dystans edycyjny | pokazuje, jak duzy byl blad, nawet gdy cala tablica nie jest idealna |
| histogram bledow znakow | ktore znaki sa mylone | pomaga uzasadnic dalsze poprawki datasetu/modelu |
| braki/nadmiary/duplikaty | bledy strukturalne wyniku | pokazuje, czy problemem jest model, NMS, prog czy skladanie sekwencji |

Prace ALPR, np. Laroca i Velarde, uzasadniaja patrzenie na wynik end-to-end oraz na podobienstwo sekwencji, a nie tylko na metryki detektora. To pasuje do naszego ukladu `MT -> rektyfikacja -> MZ -> skladanie numeru`.

## 5. Testy mobilne: dlaczego nie wystarczy mAP z desktopu

Model najlepszy na komputerze nie musi byc najlepszy na telefonie. Literatura mobilna i benchmarki MLPerf pokazuja, ze liczy sie caly stos:

- urzadzenie;
- system Android;
- runtime, np. TFLite, ONNX Runtime, NCNN;
- delegat, np. CPU, GPU, NNAPI/NPU;
- pre/postprocessing;
- rozmiar modelu;
- pamiec i czas ladowania;
- stabilnosc runtime.

MnasNet jest dobrym uzasadnieniem dla bezposredniego pomiaru latencji na telefonie: proxy typu FLOPs nie musi dobrze przewidywac realnego czasu. MLPerf Mobile doklada do tego rygor: staly system under test, jawne run rules, osobne przebiegi jakosci i wydajnosci, powtarzalnosc oraz raportowanie stosu sprzetowo-programowego.

Przeklad na nasz projekt:

| Metryka mobilna | Dlaczego raportujemy |
| --- | --- |
| p50 latency | typowy czas odpowiedzi |
| p90/p95 latency | plynnosc i najgorsze odczuwalne opoznienia |
| FPS | czy aplikacja moze dzialac blisko czasu rzeczywistego |
| RAM peak | czy model nie zabija telefonu |
| rozmiar pakietu | koszt dystrybucji i pamieci |
| runtime/delegate | warunek porownywalnosci wynikow |
| crashe/bledy importu | model szybki, ale niestabilny, nie jest kandydatem finalnym |

## 6. Kwantyzacja: dlaczego INT8 musi miec osobny test

Kwantyzacja moze zmniejszyc rozmiar i koszt obliczen, ale moze tez pogorszyc jakosc predykcji. Literatura dotyczaca kwantyzacji oraz dokumentacja TensorFlow Lite wskazuja, ze pelna kwantyzacja INT8 wymaga reprezentatywnego zbioru kalibracyjnego, bo trzeba oszacowac zakresy aktywacji powstajace podczas inferencji.

Przeklad na nasz projekt:

| Zasada | Konsekwencja |
| --- | --- |
| FP32 jest wariantem referencyjnym | najpierw mierzymy model bez strat kwantyzacji |
| INT8 jest wariantem badawczo-wdrozeniowym | nie moze byc domyslnym zwyciezca bez testu jakosci |
| kalibracja musi byc reprezentatywna | `MZ` kalibrujemy cropami tablic, `MT` pelnymi obrazami |
| porownujemy ten sam checkpoint | roznice przypisujemy formatowi/kwantyzacji, nie innemu treningowi |

## 7. Wiarygodnosc rankingu pakietow `MT+MZ` / `MP+MT+MZ`

Ranking pakietow jest wiarygodny, jezeli rozdzielamy trzy rzeczy:

| Warstwa | Co ocenia | Przyklad |
| --- | --- | --- |
| model skladowy | jak dobry jest pojedynczy `MT` albo `MZ` | `mAP50-95`, recall, F1 |
| pakiet ALPR | jak dziala potok `MT+MZ` albo `MP+MT+MZ` | dokladnosc calej tablicy, `CER`, kategorie bledow |
| runtime mobilny | jak pakiet zachowuje sie na telefonie | p95, RAM, crashe, wariant TFLite/ONNX/INT8 |

Taki podzial chroni nas przed dwoma bledami:

- wybraniem modelu o wysokim `mAP`, ktory nie daje najlepszego wyniku calego numeru;
- wybraniem modelu dokladnego, ale zbyt wolnego albo niestabilnego na telefonie.

## 8. Minimalne reguly powtarzalnosci

Do pracy inzynierskiej nie musimy robic formalnego benchmarku MLPerf, ale powinnismy przejac jego duch:

- zapisac wersje aplikacji desktopowej i mobilnej;
- zapisac identyfikatory modeli `MT`, `MZ`, datasetow i pakietu;
- zapisac telefon, Android, runtime i delegat;
- wykonac rozgrzewke przed pomiarem;
- mierzyc wiele prob, nie jedna;
- raportowac p50/p90/p95 zamiast tylko sredniej;
- nie zmieniac progow `conf`/`IoU` w trakcie porownania bez zapisania tego jako osobnego wariantu;
- testowac kandydatow na tym samym zbiorze;
- `final_test` uruchomic dopiero na koncu.

## 9. Mapa: wniosek -> zrodlo -> nasza decyzja

| Wniosek | Zrodla | Decyzja w projekcie |
| --- | --- | --- |
| test finalny nie sluzy do strojenia | PASCAL VOC best practice | mamy osobne `ranking` i `final_test` |
| mAP zalezy od IoU i protokolu | PASCAL VOC, COCO | raportujemy `mAP50` i `mAP50-95` |
| ALPR trzeba oceniac end-to-end | Laroca, Velarde | ranking finalny dotyczy pakietu `MT+MZ` albo `MP+MT+MZ` |
| blad jednego znaku psuje cala tablice | Laroca, Velarde, CER/OCR | raportujemy dokladnosc calej tablicy i `CER` |
| model mobilny to kompromis jakosc/szybkosc | MobileNet, MnasNet, MLPerf Mobile | ranking ma jakosc, latency, pamiec i stabilnosc |
| FLOPs nie wystarcza do oceny mobilnej | MnasNet, MLPerf Mobile | mierzymy realny telefon i runtime |
| INT8 moze pogorszyc jakosc | Jacob, Nagel, TensorFlow Lite | INT8 porownujemy z FP32 na tym samym checkpointcie |
| runtime i delegat zmieniaja wynik | MLPerf Mobile, ONNX Runtime, LiteRT | raport Androida zapisuje runtime/delegate/device |
| eksport wymaga kontraktu inferencji | Ultralytics, ONNX Runtime, LiteRT | `.alprmodel` ma manifest i SHA-256 |

## 10. Fragment do wykorzystania w pracy

Proponowany tekst:

```text
Metodyke badan oparto na praktykach stosowanych w benchmarkach detekcji obiektow oraz inferencji mobilnej. Zbiory danych rozdzielono na dane treningowe, walidacyjne, rankingowe i koncowy zbior testowy, aby uniknac strojenia modeli na danych raportowanych jako wynik finalny. Dla modeli detekcyjnych wykorzystano miary precision, recall, F1 oraz mAP przy roznych progach IoU, zgodnie z protokolami znanymi z PASCAL VOC i COCO. Poniewaz system ALPR jest potokiem wieloetapowym, metryki modeli skladowych uzupelniono o ocene wyniku koncowego, w tym dokladnosc rozpoznania calej tablicy i blad znakowy CER. W przypadku aplikacji mobilnej uwzgledniono dodatkowo czas inferencji, rozmiar pakietu, zuzycie pamieci i stabilnosc runtime, poniewaz literatura dotyczaca modeli mobilnych wskazuje, ze najwyzsza jakosc modelu nie musi oznaczac najlepszego rozwiazania wdrozeniowego.
```

## 11. Zrodla lokalne i internetowe

Klucze BibTeX dostepne w `C:\Users\48572\Desktop\dyplom_szablon`:

- `everinghamPascalVisualObject2010`;
- `cocoEvaluationAPI`;
- `rezatofighiGeneralizedIntersectionUnion2019`;
- `larocaEfficientLayoutindependentAutomatic2021`;
- `velardeBenchmarkingAlgorithmsAutomatic2022`;
- `howardMobileNetsEfficientConvolutional2017`;
- `tanMnasNetPlatformAwareNeural2019`;
- `jacobQuantizationTrainingNeural2018`;
- `hanDeepCompressionCompressing2016`;
- `szeEfficientProcessingDeep2017`;
- `jocherUltralyticsYOLO`;
- `LiteRTGooglePlay`;
- `ONNX_Mobile`.

Zweryfikowane zrodla online:

- PASCAL VOC best practice: https://www.robots.ox.ac.uk/~vgg/projects/pascal/VOC/
- PASCAL VOC paper: https://www.robots.ox.ac.uk/~vgg/projects/pascal/VOC/pubs/everingham10.html
- COCO evaluation API: https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/cocoeval.py
- Ultralytics export: https://docs.ultralytics.com/modes/export/
- TensorFlow Lite post-training quantization: https://www.tensorflow.org/model_optimization/guide/quantization/post_training
- ONNX Runtime Mobile: https://onnxruntime.ai/docs/tutorials/mobile/
- MLPerf Mobile paper: https://proceedings.mlsys.org/paper_files/paper/2022/hash/a2b2702ea7e682c5ea2c20e8f71efb0c-Abstract.html
- MLPerf Mobile rules: https://github.com/mlcommons/mobile_open/blob/main/rules/mobile_inference_rules.adoc
- MnasNet: https://research.google/pubs/mnasnet-platform-aware-neural-architecture-search-for-mobile/
- Laroca ALPR: https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/itr2.12030
- Velarde ALPR benchmark: https://link.springer.com/chapter/10.1007/978-3-031-04881-4_27
