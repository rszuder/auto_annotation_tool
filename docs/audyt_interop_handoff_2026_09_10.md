# Audyt Desktopu względem handoffu interoperacyjności

Stan audytu: 10 września 2026.

Źródło wymagań: `C:/Users/48572/Downloads/HANDOFF_DESKTOP_ALPR_FULL_INTEROP_2026-09-10.md`.
Sprawdzony working tree: `C:/Users/48572/Desktop/dyplom/start4`.
HEAD: `8f4de4d14982e0953805cfbef215d982d0a76b78`.
Uwzględniono lokalne, niezatwierdzone zmiany importera Akwizycji.
Kopia `C:/Users/48572/Desktop/ALPR_Desktop` nie jest przedmiotem tego audytu.

## Co już mamy

| Wymaganie handoffu | Stan implementacji | Dowód |
|---|---|---|
| Osobny model `alpr.model.v1` | Eksporter ról MP/MT/MZ, warianty, SHA-256 i provenance | `MobileModelExporter`, testy model/package, checkpoint identity i NCNN |
| Komplet `alpr.package.v1` | Eksport MT+MZ i MP+MT+MZ; odrzucanie niekompletnych konfiguracji | `MobileAlprPackageExporter`, testy D1–D9 |
| Kontrakty tensorów | Inspekcja ONNX/TFLite, rozróżnienie surowego NCNN i wyjścia end-to-end, typy i kwantyzacja | `_inspect_onnx_variant`, `_inspect_tflite_variant`, `_resolve_ncnn_output_spec` |
| Checkpoint identity | Konflikt SHA-256/epok zatrzymuje eksport | `validate_checkpoint_metadata`, `test_mobile_export_checkpoint_identity.py` |
| Badania, benchmark legacy, thesis | Czytnik ZIP/JSON, metadane i referencje modeli, zadeklarowane hashe | `ReportBundleReader`; walidacja schematów nadal wymaga uszczelnienia |
| Pełne dane ponad preview | Oddzielne iteratory; review czyta pełne próbki i próby | Test 12 000 wierszy przy preview 5000/1000; testy review |
| MT 0/1/N i mianownik invocation | Grupowanie niezależne od OCR, count/index, geometria i kontekst | `group_mt_invocations`, testy blind review |
| Kategorie błędów MT | Execution error i cancellation wyłączane z głównej miary | `calculate_mt_invocations`, testy final hardening |
| Dowód MT | Osobne wejście MT, mapowanie ROI/scale/padding; brak parametrów daje brak geometrii | `detection_box_on_mt_input`, testy brakujących pól |
| Human review badania | Oddzielny sidecar, SHA źródła, session/review ID, rewizja, tryb, polityka, decyzje | `MobileReviewSession`, testy niezmienności i ponownego otwarcia |
| Adapter zwykłych cropów | Osobny parser/model i galeria Z3, szkice/GT, przekazanie do anotacji | `mobile_acquisition.py`, `z3_mobile_acquisition.py`, 26 testów adaptera |
| Zachowanie materiału Akwizycji | Oryginalny ZIP, surowe teksty, obserwacje, encje, tracki, czas, ramki i telemetria | `mobile_acquisition.crops`, `source.zip`, testy provenance |
| Akwizycja bez benchmarku | Jawne odrzucenie w czytniku badawczym, brak wymyślonych prób MT i metryk pipeline'u | Test ZIP oraz zmienionego rozszerzenia `.alprsession` |
| Pochodzenie w datasetach | Eksport YOLO/klasyfikacji zachowuje provenance; split Z3 grupuje sesję | `acquisition_provenance`, `build_split_entries` |
| GUI niepełnych danych | Notices legacy, PARTIAL/ERROR, brak dowodu; część metryk zwraca `None` | `z4_mobile_sample_review.py`, `mobile_human_review.py` |

Gotowość implementacji nie oznacza potwierdzonej zgodności wykonania na telefonie.

## Rozbieżności potwierdzone

### 1. Dwie polityki normalizacji numeru

Priorytet: wysoki. Handoff: 0.6 i 8.

- [Adapter cropów](../auto_annotation_tool/mobile_acquisition.py): `GROUPING_POLICY="uppercase.v1"`, tylko `text.upper()`.
- [Review badawcze](../auto_annotation_tool/ranking/mobile_human_review.py): `uppercase_alphanumeric.v1`, wielkie litery i pozostawienie znaków alfanumerycznych.

Próba wykonana na aktualnym kodzie:

```text
raw                   wx 123ab
klucz Akwizycji        WX 123AB
klucz badania          WX123AB
```

Oba moduły łączą `aaa123` z `AAA123`. Różnią się obsługą spacji i separatorów.
Handoff wymaga centralnej polityki porównawczej także w adapterze.
Surowych tekstów nie należy zmieniać.

Zmiana grupowania wymaga także polityki otwierania wcześniejszych review Akwizycji:
po złączeniu dotychczas odrębnych grup zmienią się ich identyfikatory i możliwe
powiązania GT. Nie wystarczy podmienić stałej w starym sidecarze. Obecny reader
odrzuca niezgodną `grouping_policy`, co pozwala zaprojektować jawną migrację
lub rozpoczęcie nowego review z zachowaniem starego pliku.

### 2. Walidator kompletnego modelu jest słabszy od Androida

Priorytet: wysoki. Handoff: 4.2.

[Desktop `validate_package`](../auto_annotation_tool/exporters/mobile_model_exporter.py)
sprawdza hashe dzieci, poprawność paczek zagnieżdżonych oraz ich role.
Nie porównuje całej kopii manifestu z manifestem wewnątrz dziecka i nie
porównuje `models.<role>.model_id` z identyfikatorem dziecka.

Oba przypadki zostały zaakceptowane w próbie kontrolnej:

1. Zmiana `models.plate.model_id` w poprawnym komplecie MT+MZ.
2. Zmiana model ID w bocznym manifeście MT i aktualizacja jego sumy SHA-256,
   przy pozostawieniu oryginalnej paczki dziecka.

Androidowy `AlprPackageImporter.validateChild` porównuje rolę, task i model ID
zarówno z dzieckiem, jak i kopią manifestu; dodatkowo sprawdza równoważność
JSON obu manifestów. Taki komplet zostanie tam odrzucony.
Typowy eksport Desktopu buduje spójne dane; luka dotyczy walidacji zmienionej paczki.

### 3. Nieznany schemat raportu przechodzi jako legacy

Priorytet: wysoki. Handoff: 0.1, 5.1 i 13.

[Czytnik ZIP](../auto_annotation_tool/ranking/mobile_package_experiments.py)
przyjął archiwum z `manifest.schema="unrelated.schema.v99"`, poprawnym
`report.json` i poprawną deklarowaną sumą. Wynik:

```text
validation.ok = True
bundle_kind = legacy_zip
warnings = []
```

Potrzebne jest rozdzielenie wspieranej zgodności ze starszymi formatami od
jawnie nieznanego schematu. Schemat descriptorów próbek również nie ma
osobnej, pełnej walidacji kontraktu. Brak manifestu legacy i nieznany manifest
nie powinny oznaczać tej samej sytuacji.

### 4. Brakuje części walidacji spójności statusów MT

Priorytet: wysoki. Handoff: 0.4 i 6.

[Grupowanie invocation](../auto_annotation_tool/ranking/mobile_mt_invocations.py)
odrzuca sprzeczne liczby i indeksy detekcji, lecz zaakceptowało:

- `NOT_RUN`, `mt_executed=false`, niepusty invocation ID i count 0;
- `NOT_RUN`, `mt_executed=true`, niepusty invocation ID i count 0.

Druga kombinacja jest traktowana jako wykonane wywołanie.
Potrzebna jest walidacja wzajemnej zgodności flag, statusu, ID i liczności.

Wykonane MT bez invocation ID także przechodzi, jako `legacy_identity=true`.
Taki fallback ma uzasadnienie dla legacy, ale funkcja nie otrzymuje informacji,
czy konkretna paczka deklaruje pełny kontrakt wymagający invocation ID.

### 5. Brak wspólnego opisu możliwości paczki

Priorytet: wysoki. Handoff: 0.7 i 10.

Są częściowe flagi `artifact_flags`, np. `has_mt_attempts`, oraz
`MobileReportBundle.attempts_available`. Obecność `samples/attempts.csv`
ustawia `attempts_available`, bez potwierdzenia pełności kontraktu.

Nie ma jednego obiektu/funkcji opisującego razem:

- pełność rejestru MT i obecność invocation ID;
- dowody wejściowe i świeże MZ;
- dostępność czasu źródłowego;
- referencje modeli;
- kompletność kolekcji;
- zakres pokrycia hashami.

GUI, review i scoring używają odrębnych warunków. Należy je oprzeć na
wspólnym wyniku analizy konkretnej paczki, zachowując stan „nieznane”.
Sprawdzenie istniejącego hasha nadal działa; brakuje jednolitej informacji
o pokryciu wszystkich wymaganych wpisów.

## Pozostałe prace i weryfikacja

### Test rzeczywistej granicy

Priorytet: warunek zakończenia. Handoff: 12 i 15.

Nie znaleziono w sprawdzonym zestawie testów powtarzalnego przebiegu, który
używa aktualnego producenta jednej aplikacji i konsumenta drugiej dla:

- pełnej i częściowej sesji badawczej;
- zwykłej paczki cropów;
- pojedynczego MT, MZ i kompletu MT+MZ, opcjonalnie z MP.

Generatory fixture Desktopu istnieją. Testy pakietów zastępują konwersję
modeli atrapami; bajty `converted runtime fixture` nie są wykonywalnym modelem.
W `output/ncnn_contract_audit` są też wcześniejsze rzeczywiste eksporty modeli
i wyniki inspekcji tensorów. Samo ich istnienie nie potwierdza aktualnego
importu/wykonania w Androidzie ani obu kierunków wymiany.

Potrzebne są fixture lub generatory obu repozytoriów z wersją producenta,
oczekiwanymi ID/counts/key i testem uruchomionym po stronie odbiorcy.
Warto objąć wspólnym obrazem preprocessing, dekodowanie i rektyfikację.

### Eksport raw i normalized

Handoff 8.2 zaleca jawne zachowanie obu wartości w eksporcie wyników.
Surowe próbki pozostają w źródłowym archiwum; `derived_metrics.reads.prediction`
zawiera wynik po normalizacji, bez osobnego pola raw w tym samym rekordzie.
Do uzupełnienia są czytelne `raw_prediction`, `normalized_prediction`
i polityka porównania w wynikach odczytów. Nie jest to utrata oryginalnego ZIP.

### Warunkowa obsługa hashy cropów

Obecny `CropSessionStore` nie deklaruje hashy obrazów. Adapter wiąże review
z hashem całego archiwum, lecz nie ma mechanizmu weryfikacji deklarowanych
sum poszczególnych cropów. Jeśli kontrakt Androida wprowadzi takie deklaracje,
należy obsłużyć ich ustaloną lokalizację i semantykę zgodnie z handoffem 9.2.
Nie należy wymagać `entry_sha256` od obecnych starszych paczek cropów.

### Dokumentacja kontraktu

Istnieją osobne opisy eksportu modeli, review, invocation i Akwizycji.
Do uzgodnienia pozostają wspólna macierz schematów, wymagane/opcjonalne pola,
zasady addytywności, capabilities i wspólna normalizacja. Dokument
`mobile_acquisition_import.md` opisuje obecne `uppercase.v1`; musi zostać
zaktualizowany wraz ze zmianą semantyki i zasad otwierania dawnych review.

## Wykonane sprawdzenia

- Wszystkie moduły `tests/test_mobile*.py`: **232 passed**, 38,91 s.
- Dodatkowy [probe rozbieżności](../tests/audit_mobile_interop_probe.py):
  potwierdza różnicę normalizacji, akceptację obu niespójnych paczek modeli,
  nieznanego schematu i sprzecznych rekordów MT.
- Nowy test fizycznego telefonu lub aktualnego generatora Androida: **niewykonany**.
- Implementacja aplikacji i schematy w ramach tego audytu: **bez zmian**.
- Dodano tylko ten raport i probe audytowy; wcześniejsze zmiany adaptera
  pozostają w working tree, bez nowego commita.

Zgodność implementacyjna jest przygotowana w dużej części, ale pełna
kompatybilność nie została jeszcze potwierdzona artefaktem drugiej aplikacji.
Handoff wymaga również usunięcia opisanych wyżej rozbieżności walidacji
i normalizacji przed uznaniem prac za zakończone.
