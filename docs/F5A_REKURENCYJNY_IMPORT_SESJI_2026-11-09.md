# F5A — natywny rekurencyjny import sesji, 2026-11-09

Status funkcji: **PASS w zakresie testów syntetycznych i natywnego Tk**.
Status szerszej regresji: **PARTIAL — wcześniejsze błędy i jeden SKIP środowiska Tk**.
Import oryginalnych 36 sesji eksperymentu: **NOT_RUN**. Ręczna akceptacja wizualna: **NOT_VERIFIED**.

Baza audytu: `70f980d1a33b230626f4e9375a7049f9164342fd`.
Zmiany pozostają lokalne; nie wykonano commitu ani publikacji.

## Audyt przed zmianą

- `z4_mobile_report_browser.py`: istniejący wielokrotny wybór plików Tk, worker importu, pasek postępu, kompaktowanie indeksu raportów oraz późniejsze odtwarzanie oryginalnego źródła.
- `mobile_package_experiments.py`: istniejący `ReportBundleReader`, odczyt ZIP bez ekstrakcji, walidacja wpisów i SHA manifestu, `desktop_ingest`, `MobilePackageExperimentStore.add_report()` oraz atomowy zapis istniejącego magazynu JSON.
- Brakowało rekurencyjnego skanu, podsumowania przed zapisem i kontroli kombinacji F5A. Dotychczasowa tożsamość raportu uwzględniała datę; brak daty w archiwum mógł powodować użycie bieżącego czasu przy ponownym odczycie.
- Odczytano wyłącznie metadane jednej oryginalnej paczki `R0/PAIRED_ROI_01/r01/F5A_R0_r01_BLOK_A.alprsession`, bez uruchamiania importera. Potwierdzono `session_id`, pola serii/scenariusza/wariantu/powtórzenia oraz `BLOK_A` w `report.json → experiment.notes` i `experiment.session.notes`. Manifest zawierał SHA `session.json` i `report.json`.
- Nie wykonywano testowego importu, kopiowania, przenoszenia ani modyfikowania oryginalnych 36 archiwów. Nie zmieniano Androida, GT, logów TV, metryk ani innych modułów Z2/Z3/Z4. Nie uruchamiano modeli.

## Obsługa

1. W przeglądarce wybrać **Importuj raport z telefonu**.
2. W polu folderu wskazać `C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\02_sesje` albo przejść do niego w istniejącym oknie wyboru.
3. Pozostawić zaznaczony tryb **F5A-ROI-A12-01 / PAIRED_ROI_01 (36 sesji)**.
4. Wybrać **Importuj folder (z podfolderami)**. Można też zaznaczyć konkretny podfolder. Wpisana nowa ścieżka ma pierwszeństwo przed poprzednim zaznaczeniem.
5. Sprawdzić przewijane podsumowanie i wybrać **Importuj nowe sesje**. Zamknięcie podsumowania nie zapisuje raportów.

Dotychczasowy przycisk **Importuj zaznaczone** nadal obsługuje pojedyncze i liczne pliki `.alprsession`, `.zip`, `.json`, w tym listy raportów JSON. Wyłączenie kontroli F5A dotyczy tylko świadomie wybranego importu folderu innych sesji; nadal obowiązuje walidacja archiwum, manifestu i identyfikatora sesji.

## Zasady implementacji

- Skan i import pracują w osobnych wątkach. Komunikaty i istniejący pasek postępu są aktualizowane na wątku UI.
- Rekurencja obejmuje wyłącznie `.alprsession`, również wielkimi literami; nie podąża za dowiązaniami i junctions. Błędy odczytu katalogów są widoczne w podsumowaniu.
- Każdy plik przechodzi istniejący czytnik i walidator. Nie dodano niezależnego czytnika ZIP, nowego magazynu ani nowego formatu raportów.
- Import folderu wymaga `session.json`, zgodnego identyfikatora sesji i manifestu z SHA `session.json` oraz `report.json`. Deklaracje tożsamości muszą być zgodne; nazwa i położenie pliku nie stanowią dowodu tożsamości.
- F5A: dokładna seria i scenariusz; warianty R0/R1/R2, powtórzenia r01/r02/r03, bloki A/B/C/D. Kolejność wynika z tych metadanych. Blok pochodzi z jawnego pola `block`/`block_id` albo notatki `BLOK_A`–`BLOK_D` wewnątrz archiwum. Brak lub konflikt bloku jest błędem.
- Obce serie, pilotaże i scenariusze są pomijane w trybie F5A. Tożsamość eksperymentu dodatkowo sprawdza istniejący `mobile_experiment_identity.from_bundle()`.
- Rozróżniane są nowe sesje, istniejące SHA w magazynie, identyczne kopie w folderze, błędy i sesje obce. Różne archiwa dla tego samego `session_id` lub kombinacji nie są automatycznie rozstrzygane. Zapamiętane kombinacje z wcześniejszych importów folderu również są chronione.
- SHA sprawdzane jest po odczycie oraz ponownie przed zapisem. Zmiana pliku po podsumowaniu uniemożliwia import tego pliku.
- Zapis przechodzi przez istniejące `add_report()`/`save()`. Błąd jednego pliku lub zapisu jest przypisany do ścieżki i logowany; następne pliki są przetwarzane. Nieudany zapis przywraca poprzednią listę w pamięci. Udane zapisy sprzed anulowania pozostają w magazynie.
- Ponowny import folderu nie nadpisuje istniejących raportów ani ich weryfikacji. SHA źródłowej paczki jest trwałym kluczem deduplikacji sesji; wieloraportowy JSON zachowuje osobne raporty.
- Zachowano bezwzględną ścieżkę, SHA i istniejący indeks eksperymentu. Dodano wyłącznie opcjonalne metadane w dotychczasowym `raw.desktop_ingest`. `mt_detection_roles_complete=False` pozostaje w danych i jest wyświetlane osobno; samo w sobie nie blokuje importu.
- Brak źródłowej daty archiwum pozostaje pusty także po odczycie magazynu. Nie generuje nowego czasu pomiaru i nie zrywa powiązania przy ponownym otwarciu źródła.
- Podsumowanie pokazuje liczniki, pełne ścieżki, identyfikatory, SHA, błędy, ostrzeżenia o rolach MT i konkretne brakujące kombinacje. Kompletność dotyczy wybranego drzewa, bez uzupełniania go sesjami z innych folderów.

## Testy i rzeczywiste wyniki

Końcowy zestaw dotyczący funkcji: **98 PASS / 0 FAIL / 0 SKIP**, 11,56 s.

```powershell
python -m pytest -q --tb=short tests/test_mobile_session_folder_import.py tests/test_z4_akt89k_import_preferences.py tests/test_mobile_report_schema_contract.py tests/test_z4mobrep015_source_recovery.py tests/test_mobile_human_review.py
```

W tym 34 nowe przypadki importu folderu, 20 przypadków preferencji/wyboru plików, 3 kontraktu schematu, 15 odtwarzania źródła i 26 natywnej weryfikacji próbek. Testy obejmują:

- syntetyczne drzewo 36 sesji, celowo nieinformacyjne nazwy plików, kolejność R0/R1/R2 → r01/r02/r03 → A/B/C/D;
- dokładnie jeden brakujący blok w drzewie 35 sesji;
- powtórny import i ponowny odczyt magazynu bez duplikatów oraz bez zapisu przy samych istniejących sesjach;
- zachowanie bajtów i mtime źródeł, zgodność SHA, zakaz ekstrakcji ZIP;
- błędny ZIP/JSON, manifest/SHA, sprzeczne identyfikatory, brak/konflikt bloku, obcą serię/scenariusz/pilotaż;
- identyczne kopie, konflikt sesji i kombinacji, zmianę magazynu od podsumowania;
- zmianę źródła podczas skanu i przed zapisem, błąd zapisu jednego pliku, anulowanie, niedostępny podfolder i junction;
- przechowanie flagi niekompletnych ról MT, ponowne otwarcie wszystkich 36 źródeł, odczyt próbki JPEG przez natywny czytnik i weryfikator;
- natywne kontrolki Tk, podsumowanie/anulowanie, potwierdzenie przed zapisem, pracę poza wątkiem UI i postęp;
- zachowanie importu pojedynczych/wielu plików, wieloraportowego JSON i archiwum o tej samej zawartości pod rozszerzeniem ZIP.

Szerszy przebieg: **722 PASS / 28 FAIL / 1 SKIP**, 751 testów w 29 plikach, 70,68 s. Zakres: wszystkie `tests/test_z4mobrep*.py`, `test_mobile_report_full_rows.py`, `test_mobile_human_review.py`, `test_f5a_desktop_metadata.py`, `test_f5a12c_scene_evidence.py`, `test_f5a17_mz_input_evidence.py`, `test_f5a19_device_diagnostic.py`, `test_f5a21_tv_bbox.py` oraz trzy pliki testów importu/preferencji/schematu wskazane powyżej. Starsze testy rozszerzeń korzystają z dostarczonych fixture'ów producenta i prywatnych katalogów, nie z 36 archiwów eksperymentu.

Porównanie z niezmienionym `HEAD`, wyeksportowanym do prywatnego katalogu tymczasowego: **29 FAIL / 66 PASS** w dziewięciu plikach zawierających niepowodzenia. Porównano identyfikatory przypadków w JUnit: **0 nowych błędów**. Istniejące błędy dotyczą wcześniejszych oczekiwań etykiet, układu i wykresów oraz niepełnych obiektów testowych weryfikacji.

Jedyny SKIP szerokiego przebiegu to `test_review_and_refresh_keyboard_accessible_buttons_invoke_callbacks`: przejściowy błąd ładowania biblioteki Tk. Ten przypadek kończy się FAIL na bazowym HEAD, a także w pierwszym szerokim przebiegu tej zmiany (665 PASS / 29 FAIL / 1 SKIP). Oddzielny pośredni zestaw funkcji miał jeden błąd inicjalizacji Tk (95 PASS / 1 FAIL); końcowe ponowienie funkcji zakończyło się 98/98 PASS. Nie deklaruje się pełnej zielonej regresji repozytorium.

Ostatnie doprecyzowanie pierwszeństwa wpisanej ścieżki folderu i jego nowy test zweryfikowano końcowym zestawem 98 testów po szerszym przebiegu.

Dowody JUnit: `C:\Users\48572\AppData\Local\Temp\f5a-import-baseline-odg9995y\focused-final.xml`, `regression-final.xml`, `baseline-failures.xml`. `git diff --check`: PASS.

## SHA-256 plików dostarczonych

| Plik | SHA-256 |
|---|---|
| `auto_annotation_tool/gui/z4_mobile_report_browser.py` | `ebed346ed27a9306a922e95394df9969de95e342e5aa5450eec46c91d846f613` |
| `auto_annotation_tool/ranking/mobile_package_experiments.py` | `13d55ba23c39b112f86db3df84984a8f30c42513ddd3f64d7ac77d91b940feb7` |
| `tests/test_mobile_session_folder_import.py` | `9669754c51d92f41ea5390548c85f35ed2c0666d121b0d93ccbba3b3958b95a8` |
| `tests/test_z4_akt89k_import_preferences.py` | `beb6bbc00cda26be4f69494977a86b2c51cde14a4daad0ec5634d7b6fd00c175` |
