# F4 — korekta INT8 MT Pose w Desktop GUI, wyłącznie badawcza

**Status:** Patch badawczy 2026-10-12; NIE udowodniono wykonania Android INT8 ani poprawności na `final_test`.

## Cel

Po wyborze modelu tablic **MT**, wariantu **Android lekki — LiteRT INT8**, trybu
**Badawcza kalibracja INT8 — bez final_test** i prawidłowego manifestu,
aplikacja wykonuje normalny eksport Ultralytics/onnx2tf. Jeśli otrzyma
`signed I/O + MIXED` i rozpozna **ściśle** udokumentowaną strukturę
jednoklasowej głowicy YOLO26 Pose, próbuje konwersji końcowego TopK/Concat
na wyjście wyłącznie całkowitoliczbowe **wewnątrz programu**, bez skryptów
wykonywanych przez operatora podczas eksportu.

## Warunki bezpieczeństwa i niezależne walidacje

- Nie zmieniamy PyTorch checkpointów, wag, TensorFlow, Ultralytics ani zbiorów danych.
- Tryb ścisły `strict` nadal wymaga rzeczywistego `final_test`; korekta nie jest w nim wywoływana.
- Korekta jest ograniczona do jednego podgrafu, 764 tensorów, 472 operatorów,
  7 określonych tensorów FLOAT32, dokładnych indeksów i kodów operatorów,
  1 klasy, 300 detekcji, 4 keypointów x/y, I/O signed INT8 512x512.
- Każdy z trzech strumieni wyjściowych ma skalę i zero-point identyczne
  z wyjściem i score; inaczej **odmowa** bez częściowego sukcesu.
- Oryginalny model pozostaje niezmieniony. Zmieniamy tylko jego kopię.
- Kandydat MUSI przejść niezmienione kontrole `analyze_tflite_bytes` i
  zwykłe `_require_tflite_precision`; wynik `INT8`, bez `issues`.
- Inspektor dodaje JEDYNIE rozpoznaną sygnaturę `CAST INT64 → INT8`
  o **dokładnym** kształcie `[1,300,1]`, `scale=1.0`, `zero_point=0`.
  To rzeczywiście całkowitoliczbowa operacja, której implementacja TFLite
  obsługuje ten typ. Nie zmieniamy reguł `MIXED`/FLOAT32 ani signed I/O.
- Obowiązkowy test interpreterów TensorFlow 2.19.0 na 8 wejściach:
  czarne, szare, białe, gradient, paski, szachownica, 2 szumy.
  **Każdy z 33 600 elementów musi być identyczny.** Inaczej odmowa.
- Przed sukcesem tworzymy trwałe kopie `source_mixed.tflite`,
  `candidate_int8.tflite`, `recovery_report.json` z SHA i wynikami CPU
  w `output/mobile_export_diagnostics/recovered_int8_*/`.
  W przypadku braku dowodów / braku zapisu eksport nie przejdzie.
- Gdy struktura jest nieznana albo porównanie nie przechodzi, zwykły
  `FULL_INT8_OUTPUT_NOT_PROVEN` pozostaje aktywny i zapisuje pierwotną
  diagnostykę `rejected_int8_*/` — bez FP32 fallback i bez zwalniania bramek.

**Nie jest to poprawka wewnętrznego MLIR quantizera TensorFlow.** Jest to
ograniczona, zweryfikowana przez CPU korekta po wyjściu z konwertera.
Zaletą jest brak powtórzenia pełnej kalibracji wewnątrz tej samej operacji.
Nowe uruchomienie w UI nadal musi wykonać normalną czasochłonną konwersję
Ultralytics, zanim korekta będzie miała zastosowanie.

## Interfejs operatora

1. Zamknij aktualne okno aplikacji przed instalacją jednorazowego patcha.
2. Uruchom `python main.py` po sprawdzeniu patcha i testów.
3. `Integracje → Eksport mobilny → Centrum eksportu mobilnego`.
4. Zaznacz **wyłącznie MT-DAY** → `Eksportuj zaznaczone`.
5. `Android lekki` włącz, `Android stabilny`, ONNX i NCNN wyłącz.
6. Ustaw `imgsz=512`, `conf=0.25`, `IoU=0.45`; wybierz
   `Badawcza kalibracja INT8 — bez final_test` i dotychczasowy manifest
   `Workspace/E-MZ-DN-01/raporty_do_pracy/calibration_plate_EXPLORATORY_ONLY.json`.
7. `Sprawdź gotowość eksportu`, następnie `Eksportuj model mobilny (.alprmodel)`.
8. Jeśli graf przejdzie wszystkie kontrole, program sam użyje badawczej
   korekty i odnotuje dowody. **Nie wolno publikować artefaktu jako
   zatwierdzonego produkcyjnie bez dodatkowych etapów.**

## Słowa-klucze w logach

- `Badawcza korekta TopK/Concat INT8 przeszla statyczny i CPU parity gate` —
  wyłącznie potwierdzona korekta badawcza.
- `RESEARCH_INT8_RECOVERY_FAILED` — struktura inna, test niezgodny lub
  niemożność zapisu; standardowa odmowa nadal obowiązuje.
- `FULL_INT8_OUTPUT_NOT_PROVEN` — zwykła bariera aplikacji przed opakowaniem
  grafu `MIXED`.

## Ograniczenia weryfikacji

1. W środowisku autora patcha nie było TensorFlow/LiteRT, więc końcowego
   odczytu przez inspektor projektu i integracji całej aplikacji nie uruchomiono.
   Te kroki MUSZĄ przejść w lokalnym Windows Desktop przed pełnym eksportem.
2. Sprawdzono, że korekta dokładnie reprodukuje wcześniejszy eksperymentalny
   kandydat MT-DAY, SHA
   `1cc49f7c0ff72d56301c7ea560f7fa32b2e3f6915f28b4ac794c3a96bf7d115f`,
   którego 8 testów CPU uprzednio zakończyło się PASS.
3. Samo podpisane wejście/wyjście, statyczne INT8 i parytet CPU nie
   dowodzą użycia integer kernel/delegata na Androidzie.
4. Testy na prawdziwych zdjęciach oraz porównanie jakości/latencji
   są kolejnymi zadaniami i nie są wykonane przez ten patch.
5. Zakaz uznania EVAL396 za `final_test`, jego niezależność nie jest potwierdzona.
