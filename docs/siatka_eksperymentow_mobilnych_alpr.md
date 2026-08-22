# Siatka eksperymentow ALPR i pakietow mobilnych

Stan na dzien: 2026-08-19.

Dokument projektuje metodyke badan dla pracy inzynierskiej i dla eksportu modeli do klienta Android. Celem nie jest samo znalezienie modelu z najwyzszym `mAP`, tylko wybor kompletnego pakietu ALPR, ktory ma dobra jakosc, miesci sie w ograniczeniach telefonu i jest powtarzalnie testowany.

Szczegolowe uzasadnienie literaturowe tej metodyki jest w `docs/podbudowa_literaturowa_metodyki_testow_alpr.md`. Ten dokument odpowiada na pytanie, dlaczego taki podzial testow i metryk jest wiarygodny.

## 1. Wniosek po przegladzie plikow TeX

W `C:\Users\48572\Desktop\dyplom_szablon\tresc_pracy.tex` sa juz przygotowane miejsca, w ktore ta metodyka naturalnie wchodzi:

| Rozdzial pracy | Co powinno tam trafic |
| --- | --- |
| `Implementacja wybranych rozwiazan` | opis aplikacji desktopowej, klienta mobilnego, eksportu `.alprmodel`, manifestu i roli modeli `MT`/`MZ` |
| `Przygotowanie zbioru danych i szkolenie sieci` | opis iteracji, datasetow, splitow, augmentacji, treningow i wyboru kandydatow |
| `Analiza uzyskanych wynikow` | metodyka, tabele wynikow, ranking, porownanie modeli, wykresy i analiza bledow |
| `Wydajnosc na urzadzeniu mobilnym` | pomiary czasu, pamieci, rozmiaru pakietu, runtime i stabilnosci na Androidzie |
| `Ocena kompletnego systemu ALPR` | wynik end-to-end: obraz -> tablice -> rektyfikacja -> znaki -> numer rejestracyjny |

Najwazniejsze ograniczenie metodologiczne jest juz zapisane w TeX: modeli nie wolno uczciwie porownywac na roznych zbiorach testowych. Ranking koncowy musi miec wspolny tor testowy.

## 2. Jednostka badania: model czy pakiet

Do pracy badawczej potrzebujemy dwoch poziomow oceny:

| Poziom | Co porownujemy | Po co |
| --- | --- | --- |
| Model skladowy | pojedynczy `MT` albo pojedynczy `MZ` | zeby wiedziec, ktory element potoku jest mocny albo slaby |
| Pakiet ALPR | para `MT + MZ` albo kaskada `MP + MT + MZ` oraz warianty runtime, np. TFLite/ONNX/INT8 | zeby wybrac zestaw nadajacy sie do aplikacji mobilnej |

Wniosek praktyczny: finalnym kandydatem do Androida nie jest sam `MZ`, bo sam model znakow nie wykryje tablicy na pelnym obrazie. Pelny pakiet powinien zawierac co najmniej:

- `MT`: model tablic, zwykle YOLO Pose, wykrywa tablice i narozniki;
- `MZ`: model znakow, zwykle YOLO Detect, wykrywa znaki na zrektyfikowanym cropie tablicy;
- manifest `.alprmodel` z rola, formatem, progami, klasami, metrykami i pochodzeniem modelu;
- wariant wykonawczy, np. TFLite FP32, TFLite INT8 albo ONNX FP32.

Model pojazdow `MP` nie musi byc czescia badan glownych, ale jezeli aplikacja mobilna ma go uzywac, desktop musi wyeksportowac go jako gotowy wariant `.alprmodel`. Telefon nie powinien dociagac surowego YOLO ani konwertowac go lokalnie. W wynikach nalezy wtedy wyraznie rozdzielic pakiet `MT+MZ` od pelnej kaskady `MP+MT+MZ`, bo `MP` zmienia zakres pracy modelu tablic i koszt inferencji.

## 3. Warstwy eksperymentu

Eksperyment powinien byc warstwowy. Dzieki temu po porazce wiemy, gdzie system sie wysypal: na tablicy, rektyfikacji, znakach, runtime czy w skladaniu wyniku.

| Warstwa | Nazwa robocza | Dane wejsciowe | Wynik | Gdzie mierzymy |
| --- | --- | --- | --- | --- |
| E0 | kontrakt danych | dataset, split, lista obrazow testowych | zamrozony tor testowy | ALPR desktop |
| E1 | model tablic `MT` | pelne obrazy | tablice, narozniki, confidence | ALPR desktop, opcjonalnie Android |
| E2 | rektyfikacja | narozniki tablic | crop tablicy | ALPR desktop i Android |
| E3 | model znakow `MZ` | cropy tablic | boxy znakow, klasy, confidence | ALPR desktop, opcjonalnie Android |
| E4 | wynik sekwencji | uporzadkowane znaki | numer rejestracyjny | ALPR desktop i Android |
| E5 | pakiet mobilny | `.alprmodel` | import, runtime, wariant | Android |
| E6 | wydajnosc mobilna | obraz albo seria obrazow | p50/p90/p95, RAM, rozmiar, stabilnosc | Android |

## 4. Zbiory danych potrzebne do badan

| Zbior | Czy uzywany do treningu | Kto go uzywa | Sens |
| --- | --- | --- | --- |
| `train` | tak | ALPR desktop | uczenie modelu |
| `val` | nie bezposrednio, ale uzywany w treningu do wyboru epoki | ALPR desktop | monitorowanie treningu i wybor `best.pt` |
| `ranking` | nie | ALPR desktop | uczciwe porownanie kandydatow po treningu |
| `mobile_benchmark` | nie | Android | rzeczywisty pomiar na telefonie |
| `calibration_int8` | nie jako trening | eksporter ALPR | kalibracja INT8 |
| `final_test` | nie | ALPR desktop i Android | koncowy test raportowany w pracy |

Zasada: `final_test` nie powinien byc uzywany do wyboru modelu. To jest ostatni egzamin, nie tor treningowy ani rankingowy.

## 5. Siatka eksperymentow modeli

### 5.1. Modele tablic `MT`

| Zmienna | Warianty | Metryki |
| --- | --- | --- |
| rodzina YOLO | np. `n`, `s`, `m`, zalezne od realnie wytrenowanych modeli | liczba parametrow, rozmiar checkpointu |
| dataset | warianty datasetu tablic | liczba obrazow, liczba tablic, iteracja, augmentacja |
| augmentacja | brak, lekka, pogodowa, geometryczna dla toru tablic | zmiana `mAP50-95`, recall, bledy naroznikow |
| checkpoint | `best.pt`, ewentualnie wznowiony/dotrenowany | epoka najlepsza, liczba epok lacznie |
| progi inferencji | `conf`, `IoU` | precision, recall, F1, liczba FP/FN |

Metryki obowiazkowe `MT`:

- `mAP50`;
- `mAP50-95`;
- `precision`;
- `recall`;
- `F1`;
- blad naroznikow po rektyfikacji, np. sredni blad w pikselach lub jako procent przekatnej tablicy;
- odsetek obrazow, dla ktorych tablica zostala poprawnie wycieta.

### 5.2. Modele znakow `MZ`

| Zmienna | Warianty | Metryki |
| --- | --- | --- |
| rodzina YOLO | np. `n`, `s`, `m`, zalezne od realnie wytrenowanych modeli | liczba parametrow, rozmiar checkpointu |
| dataset | warianty datasetu znakow | liczba tablic, liczba znakow, iteracja, augmentacja |
| augmentacja | brak, swiatlo, pogoda, zabrudzenia, mokry film | wplyw na znaki trudne |
| checkpoint | `best.pt`, dotrenowanie | epoka najlepsza, laczna liczba epok |
| progi inferencji | `conf`, `IoU` | braki, duplikaty, bledna klasa |

Metryki obowiazkowe `MZ`:

- `mAP50`;
- `mAP50-95`;
- `precision`;
- `recall`;
- `F1`;
- dokladnosc znaku;
- blad sekwencji `CER`;
- dokladnosc calej tablicy na cropach;
- liczba brakujacych znakow;
- liczba nadmiarowych znakow;
- liczba duplikatow po NMS.

## 6. Siatka eksperymentow pakietow mobilnych

Pakiet kandydacki powinien miec czytelny identyfikator, np.:

```text
PKG-IT12-MT2608A-MZ2608C-TFLITE-FP32
```

Minimalny rekord pakietu:

| Pole | Znaczenie |
| --- | --- |
| `package_id` | stabilny identyfikator pakietu |
| `MT` | model tablic uzyty w pakiecie |
| `MZ` | model znakow uzyty w pakiecie |
| `formats` | warianty runtime w pakiecie |
| `imgsz_mt` | rozmiar wejscia modelu tablic |
| `imgsz_mz` | rozmiar wejscia modelu znakow |
| `conf_mt`, `iou_mt` | progi tablic |
| `conf_mz`, `iou_mz` | progi znakow |
| `dataset_ranking` | tor testowy, na ktorym pakiet byl oceniany |
| `exported_at` | data eksportu |
| `app_version` | wersja aplikacji Android uzytej w pomiarze |
| `device` | telefon i wersja Androida |

Siatka mobilna:

| Eksperyment | Co zmieniamy | Co trzymamy stale | Wynik |
| --- | --- | --- | --- |
| format runtime | TFLite FP32, TFLite INT8, ONNX FP32, opcjonalnie NCNN | ten sam `MT`, `MZ`, obraz testowy i progi | wplyw formatu na czas, rozmiar i jakosc |
| kwantyzacja | FP32 vs INT8 | ten sam checkpoint i kalibracja reprezentatywna | strata jakosci vs zysk wydajnosci |
| rodzina YOLO | `n/s/m` dla `MT` albo `MZ` | ten sam dataset i format runtime | kompromis jakosc/szybkosc |
| progi `conf`/`IoU` | kilka wartosci progow | ten sam model i dataset | krzywe precision-recall, liczba brakow i duplikatow |
| komplet pakietu | rozne zestawy `MT+MZ` albo `MP+MT+MZ` | ten sam telefon, ten sam test end-to-end | wybor zwyciezcy wdrozeniowego |

## 7. Ranking i wybor zwyciezcy

Ranking powinien miec dwa etapy.

Etap 1: bramki twarde. Kandydat odpada, jezeli:

- nie importuje sie w aplikacji mobilnej;
- ma niezgodny manifest albo sumy SHA-256;
- nie uruchamia sie na wybranym runtime;
- nie osiaga minimalnej skutecznosci end-to-end;
- przekracza ustalony limit pamieci lub czasu;
- ma niestabilny runtime, np. crashe albo bledy dekodowania.

Etap 2: punktacja. Dopiero kandydaci, ktorzy przeszli bramki twarde, sa szeregowani.

Proponowana funkcja rankingowa:

```text
S = 0.50 * Q + 0.25 * L + 0.15 * M + 0.10 * R
```

gdzie:

| Symbol | Znaczenie | Przykladowe skladowe |
| --- | --- | --- |
| `Q` | jakosc rozpoznawania | dokladnosc calej tablicy, `CER`, `mAP50-95`, recall |
| `L` | opoznienie | p50, p90, p95, FPS kompletnego potoku |
| `M` | koszt pamieci i rozmiaru | rozmiar pakietu, RAM peak, czas ladowania |
| `R` | stabilnosc | brak crashy, zgodnosc runtime, powtarzalnosc wynikow |

Wagi sa propozycja startowa. Do pracy warto zapisac, dlaczego zostaly przyjete. Jezeli celem jest demonstracja mobilna, jakosc powinna miec najwyzsza wage, ale nie moze calkowicie przykryc czasu i pamieci.

## 8. Wykresy potrzebne do pracy

Minimalny zestaw wykresow:

- wykres Pareto: jakosc end-to-end kontra p95 latency;
- wykres Pareto: jakosc end-to-end kontra rozmiar pakietu;
- slupki `mAP50-95` dla `MT` i `MZ`;
- slupki dokladnosci calej tablicy dla pakietow `MT+MZ` i `MP+MT+MZ`;
- wykres FP32 vs INT8 dla tego samego checkpointu;
- wykres p50/p90/p95 dla wariantow runtime na telefonie;
- histogram bledow znakow, np. najczestsze pomylki klas;
- macierz pomylek dla znakow, jezeli liczba prob jest wystarczajaca;
- tabela przypadkow blednych z kategoria bledu: brak tablicy, zle narozniki, brak znaku, zly znak, duplikat, zla kolejnosc.

Najwazniejszy wykres do obrony wyboru: Pareto `jakosc -> koszt`. Pokazuje, ze wybrany pakiet nie jest przypadkowy.

## 9. Odpowiedzialnosc: ALPR desktop vs Android

| Obszar | ALPR desktop | Aplikacja mobilna |
| --- | --- | --- |
| dane treningowe | tworzy, importuje, waliduje, dzieli na splity | nie dotyka |
| anotacje | AT/AZ, kontrola, eksport YOLO | nie dotyka, poza testami referencyjnymi |
| augmentacja | generuje i raportuje profile | nie dotyka |
| trening | uruchamia, wznawia, monitoruje, zapisuje runy | nie dotyka |
| ranking modeli | porownuje `MT` i `MZ` na wspolnym torze | moze wyswietlic wynik raportu, ale go nie tworzy |
| eksport | buduje `.alprmodel`, manifest, warianty i SHA-256 | importuje `.alprmodel` |
| kalibracja INT8 | wybiera `data.yaml`, uruchamia konwersje | tylko uruchamia gotowy wariant INT8 |
| walidacja manifestu | sprawdza przed zapisem pakietu | sprawdza ponownie przy imporcie |
| inferencja | test referencyjny/offline | glowna odpowiedzialnosc runtime |
| pomiary mobilne | definiuje protokol i przyjmuje raport | mierzy czas, RAM, runtime, crashe, wynik end-to-end |
| raport badawczy | scala wyniki i tworzy wykresy | eksportuje surowe JSON/CSV z telefonu |

Prosty podzial odpowiedzialnosci: desktop jest laboratorium i fabryka pakietow, Android jest stanowiskiem pomiarowym i demonstratorem.

## 10. Co musi raportowac aplikacja mobilna

Raport mobilny powinien byc plikiem `json` albo `csv` mozliwym do importu w ALPR desktop.

Minimalne pola:

| Pole | Sens |
| --- | --- |
| `package_id` | jaki pakiet testowano |
| `model_ids` | identyfikatory `MT` i `MZ` |
| `variant_id` | np. `tflite-fp32`, `tflite-int8`, `onnx-fp32` |
| `device_name` | telefon |
| `android_version` | wersja systemu |
| `runtime` | TFLite, ONNX, NCNN |
| `delegate` | CPU, GPU, NNAPI/NPU |
| `warmup_runs` | liczba przebiegow rozgrzewki |
| `measured_runs` | liczba przebiegow mierzonych |
| `latency_mt_ms_p50/p90/p95` | czas modelu tablic |
| `latency_mz_ms_p50/p90/p95` | czas modelu znakow |
| `latency_pipeline_ms_p50/p90/p95` | czas calego potoku |
| `ram_peak_mb` | maksymalna pamiec procesu |
| `package_size_mb` | rozmiar pakietu |
| `success_rate` | odsetek poprawnych odczytow |
| `cer` | blad znakowy |
| `error_counts` | kategorie bledow |

## 11. Co musi dopisac nasz ALPR

Po stronie desktopowej przydalby sie nastepny krok rozwojowy:

- manager pakietow kandydackich `MT+MZ` / `MP+MT+MZ`;
- ranking pakietow, nie tylko pojedynczych modeli;
- eksport kompletnego pakietu ALPR, a nie tylko pojedynczego modelu;
- import raportu mobilnego z Androida;
- widok porownania `desktop metrics + mobile metrics`;
- generator wykresow do pracy;
- zapis wersji eksperymentu: dataset, modele, formaty, progi, telefon, runtime.

To nie musi rozbijac stabilizacji, jezeli zostanie dopiete do istniejacego eksportu i rankingu jako osobna warstwa raportowa.

Pierwszy bezpieczny fundament kodowy:

- `auto_annotation_tool/ranking/mobile_package_experiments.py` - kontrakt kandydata pakietu `MT+MZ` / `MP+MT+MZ`, wariantow runtime, raportu mobilnego i punktacji;
- `auto_annotation_tool/exporters/mobile_model_exporter.py` - eksport pojedynczego modelu `alpr.model.v1` oraz kompletnego pakietu `alpr.package.v1` z para `MT+MZ` albo pelna kaskada `MP+MT+MZ`;
- `Workspace/7_rankings/mobile_packages/mobile_package_experiments.json` - docelowy plik zapisu kandydatow, raportow i wynikow.

## 12. Minimalny plan badan do pracy

Wersja minimalna, realna czasowo:

1. Wybrac 2-3 modele `MT`.
2. Wybrac 3-5 modeli `MZ`.
3. Utworzyc 4-8 pakietow `MT+MZ` lub `MP+MT+MZ`.
4. Dla kazdego pakietu wyeksportowac co najmniej TFLite FP32 i ONNX FP32.
5. Dla 2-3 najlepszych pakietow dodac TFLite INT8.
6. Przeprowadzic ranking offline na tym samym zbiorze `ranking`.
7. Przeprowadzic test mobilny na tym samym zestawie `mobile_benchmark`.
8. Zestawic wykres Pareto i wybrac pakiet finalny.
9. Na koniec wykonac test `final_test`, nieuzywany w rankingu.

Wersja rozszerzona:

- dodac porownanie runtime CPU/GPU/NNAPI;
- dodac test dzien/noc/deszcz/rozmycie;
- dodac analize bledow w podziale na klasy znakow;
- dodac porownanie wplywu augmentacji.

## 13. Jak to opisac w pracy

Proponowana narracja:

```text
W pracy nie wybrano modelu wylacznie na podstawie metryk treningowych. Najpierw oceniono modele skladowe, a nastepnie utworzono pakiety kandydackie skladajace sie z modelu tablic i modelu znakow. Pakiety zostaly porownane na wspolnym torze testowym oraz na urzadzeniu mobilnym. Ostateczny wybor oparto o kompromis pomiedzy jakoscia rozpoznawania, czasem inferencji, rozmiarem pakietu i stabilnoscia dzialania.
```

To jest bezpieczna narracja badawcza: pokazuje, ze system byl oceniany jako calosc, a nie tylko przez jeden atrakcyjny wskaznik.

## 14. Literatura i klucze BibTeX

Pelna mapa `wniosek -> literatura -> decyzja projektowa` znajduje sie w `docs/podbudowa_literaturowa_metodyki_testow_alpr.md`.

W szablonie pracy sa juz wpisy, ktore wspieraja te metodyke:

| Obszar | Klucze |
| --- | --- |
| YOLO i detekcja | `Redmon_2016_CVPR`, `Redmon_2017_CVPR`, `DBLP:journals/corr/abs-1804-02767`, `jocherUltralyticsYOLO` |
| metryki detekcji | `everinghamPascalVisualObject2010`, `cocoEvaluationAPI`, `rezatofighiGeneralizedIntersectionUnion2019` |
| ALPR i ocena end-to-end | `larocaEfficientLayoutindependentAutomatic2021`, `velardeBenchmarkingAlgorithmsAutomatic2022`, `liDetailedReviewLicense2026` |
| rozwiazania mobilne i brzegowe | `howardMobileNetsEfficientConvolutional2017`, `tanMnasNetPlatformAwareNeural2019`, `ammarMultiStageDeepLearningBasedVehicle2023`, `fernandesRobustAutomaticLicense2020`, `sonnaraEfficientRealtimeLicense2025`, `lambertiLowPowerLicensePlate2026` |
| kwantyzacja i optymalizacja | `jacobQuantizationTrainingNeural2018`, `hanDeepCompressionCompressing2016`, `szeEfficientProcessingDeep2017` |
| runtime mobilny | `LiteRTGooglePlay`, `ONNX_Mobile` |

## 15. Decyzja architektoniczna

Najrozsadniejszy kierunek:

- ranking pojedynczych modeli zostaje, bo pomaga diagnozowac `MT` i `MZ`;
- do wyboru finalnego dodajemy ranking pakietow `MT+MZ` / `MP+MT+MZ`;
- eksport pojedynczego modelu zostaje jako narzedzie techniczne;
- eksport do pracy i Androida powinien promowac kompletny pakiet ALPR;
- Android nie wybiera najlepszego modelu naukowo, tylko mierzy zachowanie gotowego pakietu na urzadzeniu.

To ustawia odpowiedzialnosci czysto i konczy chaos typu: "ktory z 22 koni naprawde startuje w wyscigu".
