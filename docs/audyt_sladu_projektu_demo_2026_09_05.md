# Audyt śladu projektu demo

Data: 2026-09-05. Projekt: `demo_6D564A`.

## Ustalenia

Wpis `approve_step2` z IT1, z godziny `2026-09-02T19:54:30`, zapisał
`approved_images=0` i `approved_plates=0`. Rejestr artefaktów, lista zatwierdzonych
obrazów w manifeście runu i XML tego runu potwierdzają jednak 10 obrazów i 10 ramek.

Zapis historii pobierał wyłącznie bieżące liczniki puli projektowej. Nie uwzględniał
zatwierdzonego runu przekazywanego do pracy nad znakami. Odczyt uznawał zapisane
zera za kompletne dane i nie porównywał ich z dowodami przypisanymi do iteracji.
Ponadto ten sam licznik całej puli przedstawiano jako przyrost.

| Zasób | Stan potwierdzony dla IT1 | Dowód |
| --- | --- | --- |
| O | Wybrano 1000 obrazów. | `ingest/iter_001_manifest.json`, pole `selected_count`. |
| AT | 10 zatwierdzonych obrazów, 10 ramek tablic. | `plate_approved_set.json`, run `run_001_20260902_192508`: zatwierdzone nazwy i XML. |
| AZ | 10 tablic, 69 znaków. | `run_001_20260902_203521/export_summary.json`, eksport z IT1. |
| Dataset znaków | Źródłowy eksport: 10 tablic i 69 znaków. | Podsumowanie eksportu Z3/PZ3. |
| Przygotowany wariant | 154 obrazy: train 152, val 1, test 1. | `iteration_state.1.step4_dataset`, wariant `Aug_plus144`. |
| MZ | Jeden ukończony model z runu `20260903_115330`, pochodzący z IT1. | Historia treningu, metadane `best.pt`, `results.csv` kończący się epoką 100. |
| MT | Nie znaleziono ukończonego modelu tablic w historii projektu. | Historia treningów zawiera jeden run znaków. |

IT2 dołożyła 3 obrazy i 4 ramki. Łączna zatwierdzona pula wynosi obecnie
13 obrazów i 14 ramek. Te dodatkowe zasoby nie należą do IT1.

## Tor i pochodzenie modelu

Opis `Model znaków: brakujące anotacje tablic` był rozpoznawany jako tor tablic,
ponieważ wyszukiwano słowo `tablic` przed rozpoznaniem znaczenia całego opisu.
Taki tekstowy wpis wyboru ścieżki miał też wyższy priorytet niż późniejszy,
jednoznaczny zapis `char_from_images`. Skutkiem było przypisanie IT1 do toru
tablic i brak numeru iteracji przy modelu MZ.

Zapis ścieżki ma teraz pierwszeństwo przed heurystyką tekstową. Starszy brakujący
wybór ścieżki może być odczytany z późniejszych zdarzeń zatwierdzenia tej samej
iteracji. Nowe zdarzenia wyboru zapisują również pole `path` z żądania użytkownika.

Przy braku jawnego numeru iteracji modelu używana jest data utworzenia runu,
a nie data jego późniejszego zakończenia. Lista produktów nie jest ograniczona
do ostatnich 20 runów. Run bez modelu nie jest przedstawiany jako wytworzony model;
checkpoint nieukończonego treningu jest opisany osobno.

## Przygotowany wariant a użyty dataset

Wariant `Aug_plus144` istnieje, lecz `training_history.json`, `_ipc/job.json`
i `train/args.yaml` runu `20260903_115330` wskazują:

```text
YOLO_MegaDataset_Chars_20260902_220249_Split_20260903_114739
```

Jest to split bazowy, bez dopisku augmentacji. Jego obecne katalogi zawierają
train 8, val 1 i test 1 obraz. Nie należy przypisywać temu modelowi 154 obrazów
tylko dlatego, że taki wariant przygotowano w tej samej iteracji.

Odczyt historii rozdziela `dataset_variant` (przygotowany wariant) od
`training_run.dataset_path` (dataset zapisany przy konkretnym treningu).
Audyt nie odtwarza intencji ówczesnego wyboru użytkownika i nie zmienia
zakończonego treningu ani jego parametrów.

## Sposób naprawy

- Nowe zatwierdzenia zapisują `alpr.project_history_resources.v1`: liczniki,
  identyfikację projektu i iteracji oraz źródła dowodów.
- Historyczne AT są odczytywane według pierwszego zatwierdzenia i daty zdarzenia,
  z uzupełnieniem o zatwierdzone obrazy z właściwego runu. Powtórzenie obrazu
  w puli i runie nie podwaja licznika.
- Przyrost iteracji i łączna pula są odrębnymi wartościami.
- Później nadpisany run lub pakiet nie służy do zmieniania wcześniejszego stanu.
  Jeżeli starej geometrii nie można potwierdzić, jej licznik pozostaje nieznany.
- AZ pokazuje liczbę tablic i znaków oraz iterację pochodzenia. Użycie istniejącego
  eksportu nie jest nazywane stworzeniem nowego AZ w bieżącej iteracji.
- Dane są czytane raz na odświeżenie okna. Odczyt nie enumeruje katalogów obrazów.

Naprawa nie przepisuje pliku `project_history.jsonl`. Widok techniczny rozróżnia
odtworzone liczniki od oryginalnego wpisu historii. Nie zmieniono zatwierdzeń,
geometrii anotacji, manifestów datasetów ani pozycji projektu na grafie.

## Weryfikacja

```powershell
python -m pytest tests/test_project_history_resources.py tests/test_model_training_provenance.py tests/test_mobile_export_project_sources.py tests/test_mobile_report_full_rows.py tests/test_z4_async_training_preflight.py tests/test_app_hardware_scan.py -q
```

Wynik: **87 passed**. Kompilacja zmienionych modułów i `git diff --check`
zakończyły się poprawnie. Odczyt rzeczywistych plików `demo` przez generator
wierszy śladu zwrócił AT 10/10, AZ 10/69 i MZ przypisany do IT1.
Nie uruchamiano pełnego interfejsu aplikacji ani nowego treningu.
