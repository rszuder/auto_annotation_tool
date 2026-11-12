# F5A — importer Desktop UX02, odbiór 2026-11-09

**Funkcje i automatyczne testy Tk: PASS. Szersza regresja: PARTIAL (29 historycznych FAIL). Odbiór wizualny: NOT_VERIFIED. Produkcyjny import: NOT_RUN.**

Ten handoff opisuje aktualny przebieg UX02 i zastępuje wcześniejszą instrukcję GUI z ręcznym wyborem profilu. Nie wykonano commit/push ani pomiarów Android. Nie zmieniono modeli, źródłowych archiwów, GT, metryk, logów TV ani decyzji operatora.

## 1. Audyt i przyczyna znikania modala

Pracę rozpoczęto od lokalnego statusu Git i odczytu rzeczywistego kodu, w tym niezacommitowanych zmian UX01. Kopię aktualnego lokalnego kodu/testów zachowano pod `C:\Users\48572\AppData\Local\Temp\f5a-ux02-hou3dndc\baseline`. Nie zastępowano kodu zdalnym HEAD.

W poprzednim przebiegu `_accept_folder()` wywoływało `_close()`, które niszczyło `Toplevel`. Dopiero po powrocie z `wait_window()` metoda `import_report()` uruchamiała `_import_mobile_folder()`. Worker pracował więc przy zamkniętym dialogu, a `_show_folder_import_summary()` tworzyło później drugi `Toplevel`. Znikanie było bezpośrednim skutkiem takiego przepływu sterowania, nie problemem paska postępu.

Drugą przyczyną błędnej kwalifikacji był parametr ręcznie wybranego profilu: `f5a=False` pomijał walidację protokołu. Dla mieszanego korzenia obejmowało to konflikty R1/r02 i nowy pilotaż.

## 2. Poprawiony cykl życia Tk

Istniejący dialog wyboru utrzymuje teraz jeden kontroler `_MobileFolderImportFlow` i jeden `Toplevel` podczas wyboru, sprawdzania, wyniku oraz zapisu. Zmieniają się wyłącznie ramki wewnątrz okna. Usunięto drugi modal podsumowania i dotychczasową osobną metodę importu folderu.

- **Wybór:** istniejąca nawigacja po plikach i folderach, edytowalna ścieżka i przycisk **Wybierz folder…**. Nie ma dropdownu profilu ani przełącznika F5A.
- **Sprawdzanie:** **Sprawdź folder z podfolderami** uruchamia worker, bez zamykania okna i bez zapisu do magazynu. Przy wyszukiwaniu postęp jest nieokreślony; po poznaniu liczby plików wyświetlane są licznik, aktualne archiwum i postęp określony.
- **Wynik:** zwięzłe liczniki, serie odczytane z metadanych, grupy wyników i szczegóły wybranego pliku. Przyciski powrotu, kopiowania, anulowania i świadomego importu pozostają w stopce.
- **Zapis:** dopiero przycisk **Importuj N zgodnych sesji** uruchamia istniejące `MobilePackageExperimentStore.add_report()`/`save()`. Postęp i wynik pozostają w tym samym oknie. Wynik podaje faktyczne liczby zaimportowanych, istniejących, niezaimportowanych i błędów dla całego skanu.

Worker publikuje wyłącznie zdarzenia do `queue.Queue`. Wątek Tk odbiera je przez `after(40, ...)`; worker folderu nie wywołuje Tk ani `after`. Nie ma `join` ani `sleep` na ścieżce produkcyjnego GUI.

Przycisk anulowania sygnalizuje `threading.Event`; operacja kończy się po bieżącym archiwum. Po anulowaniu skanu można wrócić do wyboru i uruchomić nowy skan. Esc/X podczas wyboru, skanu lub podsumowania zamyka dialog i zatrzymuje jego polling. Esc/X podczas zapisu żąda przerwania, ale pozostawia wynik częściowego zapisu widoczny; następne zamknięcie kończy dialog. Udane wcześniejsze zapisy nie są cofane — cały import nie jest transakcją atomową.

Przy niszczeniu okna anulowany jest timer, a zmienne Tcl i cykl referencji kontroler–okno–callback są zwalniane na wątku UI. Testy etapowe ujawniły zbieranie tego cyklu przez GC w workerze, łącznie z błędem Tcl/Windows; poprawiono przyczynę. Końcowe testy nie wykazały tych błędów.

## 3. Automatyczna kwalifikacja i grupy

Właściwe F5A rozpoznawane jest przez dokładną parę:

```text
series_id   = F5A-ROI-A12-01
scenario_id = PAIRED_ROI_01
```

Nie są używane nazwy plików/folderów ani dopasowanie prefiksu. `F5A-ROI-A12-01-PILOT`, inny scenariusz, inna wielkość liter lub dodatkowy znak nie oznaczają właściwego F5A. Sprzeczne deklaracje tożsamości są odrzucane, zamiast przechodzić do trybu ogólnego.

Dla rozpoznanego F5A zawsze działa dotychczasowy walidator protokołu, łącznie z polityką ROI. Pozostawiony dla zgodności wywołań argument `f5a` nie może nadpisać identyfikacji źródła ani wyłączyć walidacji. Kontrolę znanego F5A dodano także do importu plikowego — konfliktu nie można ominąć przez `.zip` lub `.json` zawierający metadane właściwego F5A. Zwykły import historycznych `.zip`/`.json` nadal działa.

Jeśli skan zawiera właściwe F5A, domyślnie kwalifikowana jest jego grupa. Pozostałe serie pozostają widoczne i wymagają oddzielnej akcji **Wybierz zaznaczoną serię do importu**. Samo zaznaczenie wiersza nie zmienia CTA. Jeśli występuje jedna seria, nie ma zbędnej kontrolki wyboru grupy. Przy kilku równorzędnych nieznanych seriach żadna nie jest wybierana arbitralnie, a import pozostaje wyłączony do jawnego wyboru.

Grupy wyników są filtrami: istniejący pilot jest widoczny zarówno w **Pilotaże / inne serie**, jak i **Już zaimportowane**. Nie oznacza to drugiego rekordu magazynu. Główne liczniki i kompletny raport diagnostyczny liczą archiwa jednokrotnie. Widoczne liczniki i kopiowana diagnostyka korzystają z tej samej funkcji modelu planu.

Nie dodano nowego czytnika, magazynu, rejestru odstępstw ani formatu raportów. Zachowano natywną walidację ZIP/manifestu, SHA, ścieżki źródłowe i weryfikacje. `mobile_import_preferences.py`, `mobile_experiment_identity.py` oraz `mobile_scene_evidence.py` sprawdzono; pozostają byte-identical względem lokalnego początku UX02.

## 4. Kontrola rzeczywistych danych — tylko odczyt

| Wynik | `02_sesje` | Korzeń eksperymentu |
|---|---:|---:|
| Znalezione archiwa | 36 | 38 |
| Integralne | 36 | 38 |
| Właściwa seria F5A | 36 | 36 |
| Zgodne F5A | 32 | 32 |
| Konflikty F5A | 4 | 4 |
| Pilotaże | 0 | 2 |
| Pilotaże już w magazynie | 0 | 1 |
| Nowe pilotaże | 0 | 1 |
| Uszkodzone | 0 | 0 |
| Domyślnie gotowe do zapisu | **32** | **32** |
| Domyślne CTA | **Importuj 32 zgodne sesje** | **Importuj 32 zgodne sesje** |

Użyto bieżącego, wyłącznie odczytanego indeksu istniejących raportów. W całym skanie jest 33 nowych integralnych sesji bez konfliktu protokołu, ale nowy pilot jest poza domyślnym wyborem. Dlatego CTA wskazuje 32, a nie 33 ani dawne 37.

Cztery konflikty pozostają w **R1/r02/A–D**, z kodem **VARIANT_POLICY_CONFLICT**. Szczegóły pokazują **Niezgodna strategia ROI**, wariant zapisany **R1**, wykonanie **R2 — maksymalnie 2 ROI (`r2_two_roi`)** i oczekiwanie **R1 — maksymalnie 1 ROI (`r1_one_roi`)**. Nie zmieniono metadanych i nie zakwalifikowano tych sesji do prawidłowej populacji R1.

| Zakres MT | Niekompletne archiwa | Niedokończone wywołania | scene_superseded | session_stopped |
|---|---:|---:|---:|---:|
| 36 właściwych F5A | 23 | 57 | 45 | 12 |
| Cały skan 38 | 24 | 61 | 48 | 13 |
| Inne serie / pilotaże | 1 | 4 | 3 | 1 |

Ostrzeżenie `mt_detection_roles_complete=False` nie blokuje importu i nie jest błędem ZIP/SHA. Liczniki wywołań pochodzą z rekordów zwróconych przez istniejący walidator; nie są wyliczane z geometrii ani nazw plików.

Przed i po audycie sprawdzono **SHA-256, rozmiar i mtime wszystkich 38 archiwów — bez zmian**. Po testach ponownie potwierdzono SHA i mtime. Produkcyjny magazyn pozostał bez zmian, SHA-256: `e80b28e4bf6030cd60b79bd42b30b9eab12b72019bbd2d8281e70a39bbb40786`. W procesie audytu zablokowano metody zapisu magazynu; żadnej nie wywołano. Wszystkie testy zapisujące importera działały na danych syntetycznych w prywatnych katalogach.

## 5. Pliki zmienione w UX02

1. `auto_annotation_tool/gui/z4_mobile_report_browser.py` — jeden dialog, kolejka zdarzeń, grupy i szczegóły, jawne zatwierdzanie, anulowanie, zamykanie i kontrola znanego F5A w imporcie plikowym.
2. `auto_annotation_tool/ranking/mobile_package_experiments.py` — automatyczna tożsamość i wybór grupy, kwalifikacja bez obejścia, liczniki dla rozdzielonych populacji i wspólna diagnostyka.
3. `tests/test_mobile_session_folder_import.py` — testy automatycznej kwalifikacji, grup, natywnego lifecycle i ochrony danych; zastąpiono testy usuniętego drugiego modala.
4. `tests/test_z4_akt89k_import_preferences.py` — aktualna nazwa CTA, sprawdzanie widocznych kontrolek i prywatny magazyn pomocnika Tk.
5. `docs/F5A_IMPORTER_UX02_ODBIOR_2026-11-09.md` — ten handoff.

Zastane pozostałe zmiany lokalne pozostawiono bez nadpisania.

## 6. Rzeczywiste wyniki testów

Końcowe testy funkcjonalne: **135 PASS / 0 FAIL / 0 SKIP**, 32,78 s.

```powershell
python -m pytest -q --tb=short tests/test_mobile_session_folder_import.py tests/test_z4_akt89k_import_preferences.py tests/test_mobile_report_schema_contract.py tests/test_z4mobrep015_source_recovery.py tests/test_mobile_human_review.py
```

Pokrycie UX02:

- **T01–T10:** brak dropdownu, dokładne metadane, oddzielny pilot, 32 + 4, mieszany korzeń 38, istniejący i nowy pilot, CTA 32, brak obejścia przez argument trybu/import plikowy, działające inne serie i jawny wybór grupy.
- **T11–T18:** niezmienny identyfikator `Toplevel`, brak niszczenia podczas skanu, rzeczywiste zdarzenia postępu, anulowanie, brak zapisu przed potwierdzeniem, zapis po CTA, faktyczne wyniki i częściowe przerwanie bez utraty wcześniejszych zapisów.
- **T19–T24:** błąd jednego pliku, niedostępny/pusty folder, długa ścieżka Windows, liczniki MT 36/38, nieblokujące ostrzeżenia, idempotencja i zachowanie weryfikacji, `.zip`/`.json`.
- **T25–T28:** brak Tk/`after` z workera, Esc/X w rzeczywistym pickerze, ponowne sprawdzanie po anulowaniu, kopiowanie pełnej diagnostyki zgodnej z GUI.
- Dodatkowo zmierzono widoczność wszystkich CTA przy 780 × 650 oraz obecność istniejącego pilota w obu właściwych filtrach wyników.

Szersza regresja z zakresu poprzedniego handoffu: **760 PASS / 29 FAIL / 0 SKIP**, 789 testów w 29 plikach, 95,48 s. Obejmuje wszystkie `test_z4mobrep*.py` oraz `test_mobile_report_full_rows.py`, `test_mobile_human_review.py`, `test_f5a_desktop_metadata.py`, `test_f5a12c_scene_evidence.py`, `test_f5a17_mz_input_evidence.py`, `test_f5a19_device_diagnostic.py`, `test_f5a21_tv_bbox.py` i trzy pliki importu/preferencji/schematu.

Wszystkie **29 FAIL** odtworzono na zachowanej kopii **lokalnego stanu sprzed UX02**: 29/29 tych samych niepowodzeń, **0 nowych FAIL**. Dotyczą historycznych oczekiwań etykiet/układu/wykresów i niepełnych obiektów testowych. Nie deklaruje się pełnego PASS repozytorium. Ostatnie doprecyzowanie nakładających się filtrów widoku potwierdzono końcowym zestawem 135 testów po szerszym przebiegu.

`git diff --check`: **PASS**. W toku implementacji wystąpiły i zostały usunięte błędy nowego lifecycle związane z GC/Tk. Końcowe 135 testów oraz szeroki przebieg nie zgłosiły tych problemów; nie oznaczano nowych testów jako SKIP w celu ukrycia niepowodzeń.

## 7. Instrukcja odbioru wizualnego i ograniczenia

1. Uruchom ponownie Desktop, aby wczytał aktualny kod. Otwórz **Importuj raport z telefonu**. Sprawdź brak dropdownu profilu.
2. Wskaż `02_sesje` przez **Wybierz folder…** albo wklej ścieżkę. Kliknij **Sprawdź folder z podfolderami**. To samo okno ma pozostać widoczne ze stanem **Sprawdzanie archiwów**, postępem, bieżącą nazwą i **Anuluj sprawdzanie**.
3. Poczekaj na **Wynik sprawdzenia**. Sprawdź 36 archiwów, 32 zgodne, 4 konflikty, brak zbędnego wyboru grupy i CTA **Importuj 32 zgodne sesje**. Wybierz konflikt, aby zobaczyć R1 kontra R2, kod, session_id, SHA i ścieżkę.
4. Użyj **Wróć do wyboru folderu**, wskaż korzeń eksperymentu i sprawdź ponownie. Oczekiwane są 38 archiwów, 2 pilotaże (1 istniejący, 1 nowy), domyślnie zaznaczone właściwe F5A i nadal CTA 32. Tabela serii pozwala jawnie wybrać inną grupę; samo zaznaczenie wiersza nie zmienia kwalifikacji.
5. Sprawdź grupy wyników, szczegóły pliku, rozdzielone liczniki MT i **Kopiuj podsumowanie**. Powiększ/pomniejsz dialog; długie ścieżki mają zawijać się w szczegółach, a CTA pozostać widoczne.
6. Sprawdź **Anuluj sprawdzanie**, powrót i ponowny skan oraz Esc/X. Na rzeczywistych danych zakończ na kopiowaniu/anulowaniu. **Nie uruchamiaj produkcyjnego zapisu w ramach tego odbioru.** Zapis i częściowe przerwanie przetestowano na syntetycznych danych.

Próba osobnego oglądu przez `computer-use` nie dostarczyła obrazu: dwukrotnie `window capture timed out: timed out waiting on channel`, również po odświeżeniu uchwytu. Zamknięto wyłącznie własny proces syntetycznego podglądu. Dlatego status wizualny UX02 pozostaje **NOT_VERIFIED**, mimo przejścia natywnych testów zachowania i geometrii Tk.

Anulowanie nie przerywa natywnego czytania w połowie pojedynczego archiwum. Grupy wyników mogą się nakładać i nie należy sumować ich wierszy jako liczby unikalnych archiwów. Import nieznanej serii oznacza ogólną kontrolę źródła, nie certyfikację nieznanego protokołu badawczego. Historyczny import zaznaczonych plików zachowuje swój dotychczasowy przebieg; ciągły dialog dotyczy operacji folderowych.

## 8. Dowody i SHA

Katalog dowodów: `C:\Users\48572\AppData\Local\Temp\f5a-ux02-hou3dndc` — `focused-final.xml`, `regression.xml`, `baseline-failures.xml`, `36_sessions.txt`, `38_root.txt`, `real-qualification.json`, `sources-before.json`, `workspace-before.json`, `delivery-sha256.json`.

| Plik | SHA-256 |
|---|---|
| `auto_annotation_tool/gui/z4_mobile_report_browser.py` | `25afe123d5e44e7ca0b2f95b4399aa1f02c45de04d7f9072964e2929c5b94fc8` |
| `auto_annotation_tool/ranking/mobile_package_experiments.py` | `3a6ea9306126b1975d33460d43b7b907c41dc11f04a32fb0ff06ceda6e969c9e` |
| `tests/test_mobile_session_folder_import.py` | `33e65033c1d8dddc734a25d2cc73ef35ba635960b15aeb933154e49c66aae835` |
| `tests/test_z4_akt89k_import_preferences.py` | `ff5bf669289fae9316792fcfec13b02207b7a74bcd2d47e92cc53c9789087c0f` |
