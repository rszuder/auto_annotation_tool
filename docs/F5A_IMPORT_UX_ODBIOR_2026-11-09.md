# F5A — odbiór poprawek UX i kwalifikacji importera, 2026-11-09

**Funkcje importera i testy T01–T18: PASS. Szersza regresja: PARTIAL. Kontrola wizualna: NOT_VERIFIED. Właściwy import F5A: NOT_RUN.**

Nie wykonano commit/push. Nie zmieniono źródłowych archiwów, Androida, modeli, GT, logów TV, metryk ani innych eksperymentów.

## Audyt aktualnego stanu

Przed edycją sprawdzono dirty worktree i odczytano bieżące pliki. Zastane zmiany poprzedniego etapu pozostawiono jako bazę pracy. Kopia aktualnego lokalnego kodu i testów została zachowana pod `C:\Users\48572\AppData\Local\Temp\f5a-import-ux-q9lpi7j2\baseline`; do porównania regresji nie używano zdalnego HEAD.

Potwierdzone przyczyny problemów: domyślnie włączone F5A, brak przycisku selektora katalogów, mieszanie konfliktu konfiguracji z błędem archiwum, utrata dostępnych identyfikatorów po odrzuceniu przez profil, pamiętanie ostatniego podfolderu zamiast korzenia importu oraz nadpisywanie rekordu przy ponownym imporcie pojedynczego pliku.

Sprawdzono także `mobile_experiment_identity.py` i `mobile_scene_evidence.py`. Ich zawartość i SHA pozostały bez zmian. Istniejąca kontrola polityki ROI oraz walidacja dowodów nadal obowiązują.

## Zakres zmian

| Plik | Zmiana |
|---|---|
| `auto_annotation_tool/gui/z4_mobile_report_browser.py` | Przycisk „Wybierz folder…”, edytowalna ścieżka jako jedyne źródło wyboru korzenia, domyślny profil ogólny i jawny wybór F5A, czytelne podsumowanie, kopiowanie diagnostyki, widoczne anulowanie, ochrona istniejących raportów przy imporcie plików. |
| `auto_annotation_tool/ranking/mobile_package_experiments.py` | Rozdzielenie integralności, profilu, obecności i kwalifikacji; zachowanie odczytanej tożsamości także dla konfliktów; opis oczekiwanej i zapisanej polityki ROI; osobne ostrzeżenia i liczniki przerwanych wywołań MT; komunikaty o błędach ścieżek; domyślny profil ogólny; ochrona istniejących weryfikacji przy ponownym imporcie pliku. |
| `auto_annotation_tool/gui/mobile_import_preferences.py` | Opcjonalne wskazanie korzenia udanego importu folderu; zachowanie dotychczasowych zasad ON/OFF i importu plików. |
| `tests/test_mobile_session_folder_import.py` | Rozszerzenie testów do 49 przypadków, w tym scenariusz 32 + 4 i testy T01–T18. |
| `tests/test_z4_akt89k_import_preferences.py` | Aktualizacja oczekiwań dotyczących nowego przycisku i układu kontrolek. |
| `docs/F5A_IMPORT_UX_ODBIOR_2026-11-09.md` | Ten handoff i rzeczywiste wyniki odbioru. |

Nie dodano nowego importera, czytnika `.alprsession`, magazynu ani formatu raportów. Nadal używane są `ReportBundleReader`, `MobilePackageExperimentStore`, natywne otwieranie źródeł oraz dotychczasowy format indeksu. Obserwacje diagnostyczne pozostają w planie kwalifikacji; nie są osobnym rejestrem odstępstw.

## Instrukcja GUI

1. Otwórz **Importuj raport z telefonu** w przeglądarce raportów.
2. Kliknij **Wybierz folder…** i wybierz dowolny dostępny katalog/dysk. Można też wkleić pełną ścieżkę w pole **Folder do skanowania**; Enter pokazuje jego zawartość. Dwuklik folderu na liście również aktualizuje pole. Samo zaznaczenie wiersza nie zmienia korzenia skanu.
3. Ustaw **Profil importu folderu**. Domyślnie wybrany jest **Ogólny import raportów**. Kontrolę eksperymentu uruchamia jawny wybór **F5A-ROI-A12-01 / PAIRED_ROI_01**.
4. Kliknij **Importuj folder (z podfolderami)**. Rekurencja nie zależy od nazw katalogów. Wyszukiwane są `.alprsession`; dowiązania i junctions nie są śledzone. Archiwa nie są rozpakowywane na dysk.
5. W czasie skanu działa pasek postępu i przycisk **Anuluj import**. Anulowanie kończy przetwarzanie po bieżącym archiwum, bez konieczności zamykania aplikacji.
6. W podsumowaniu sprawdź liczniki oraz szczegóły problemów. **Kopiuj podsumowanie** kopiuje całość, włącznie ze ścieżkami, identyfikatorami, SHA, opisami i kodami technicznymi.
7. W obecnym odbiorze F5A zakończ na **Kopiuj podsumowanie** / **Anuluj**. Właściwego importu nie uruchomiono. Dopiero odrębna decyzja operatora i przycisk **Importuj nowe sesje (N)** zapisują zakwalifikowane sesje. Cztery konflikty nie należą do tej liczby.

**Importuj zaznaczone** nadal obsługuje pojedyncze i liczne pliki `.alprsession`, `.zip` i `.json`. Profil folderu nie zmienia tej ścieżki.

Przy włączonym **Zapamiętaj folder ostatniego importu** udany import folderu zapamiętuje korzeń, a import plików — folder ostatniego udanego pliku. Wyłączenie opcji usuwa poprzednią preferencję; przyszłe otwarcie używa zwykłego katalogu domyślnego aplikacji. Żadna ścieżka F5A nie jest wpisana na sztywno w GUI. Anulowanie wyboru/podsumowania nie uruchamia zapisu raportów.

## Rzeczywiste drzewo F5A — sprawdzenie wyłącznie odczytowe

Źródło: `C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\02_sesje`.

| Właściwość | Wynik |
|---|---:|
| Znalezione oryginalne archiwa | 36 |
| Integralne archiwa | 36 |
| Sesje zakończone timerem | 36 |
| Zgodne z planem | 32 |
| Niezgodne z planem | 4 |
| Uszkodzone / nieczytelne | 0 |
| Brakujących plików oryginalnych | 0 |
| Brakujących poprawnych pomiarów R1/r02 | 4 |
| MT: `scene_superseded` | 45 |
| MT: `session_stopped` | 12 |
| Łącznie MT z niedokończonym postprocessingiem | 57 |

Kwalifikację wykonano z pustą listą istniejących raportów, aby osobno ocenić zgodność źródeł. W produkcyjnym GUI liczniki nowych/istniejących mogą zależeć od zawartości magazynu; wynik zgodności 32 + 4 od tego nie zależy.

| Kombinacja | session_id | Kod |
|---|---|---|
| R1/r02/A | `exp-1794229039529-993a59ca` | `VARIANT_POLICY_CONFLICT` |
| R1/r02/B | `exp-1794229601661-5a312b15` | `VARIANT_POLICY_CONFLICT` |
| R1/r02/C | `exp-1794231640453-dd68590c` | `VARIANT_POLICY_CONFLICT` |
| R1/r02/D | `exp-1794232130077-85e40aa6` | `VARIANT_POLICY_CONFLICT` |

Każdy konflikt jest prezentowany jako **Niezgodna strategia ROI**, z wariantem zapisanym **R1**, strategią wykonania **R2 — maksymalnie 2 ROI (`r2_two_roi`)** i oczekiwaniem **R1 — maksymalnie 1 ROI (`r1_one_roi`)**. Dostępne dane nie są zastępowane N/A. Archiwum pozostaje widoczne jako integralne, lecz niekwalifikujące się do importu zgodnych pomiarów R1.

Nie zmieniono `session.variant` ani `execution.roi_budget_policy`. Flaga `mt_detection_roles_complete=False` pozostaje osobnym ostrzeżeniem: **Nie wszystkie wywołania MT zakończyły postprocessing — szczegóły w raporcie**. Liczniki 45/12 pochodzą z rekordów ról zwróconych przez natywny walidator, nie z nazw plików ani liczby obrazów.

SHA-256, rozmiar i mtime wszystkich 36 źródeł porównano przed i po audycie; po testach ponownie sprawdzono SHA i mtime: **36/36 bez zmian**. Produkcyjny magazyn również pozostał byte-identical, SHA-256: `e80b28e4bf6030cd60b79bd42b30b9eab12b72019bbd2d8281e70a39bbb40786`. W skrypcie audytu metody `save`, `add_report` i `import_mobile_session_plan` były blokowane; żadnej nie wywołano.

## Testy

Końcowy zestaw funkcjonalny: **113 PASS / 0 FAIL / 0 SKIP**, 16,52 s.

```powershell
python -m pytest -q --tb=short tests/test_mobile_session_folder_import.py tests/test_z4_akt89k_import_preferences.py tests/test_mobile_report_schema_contract.py tests/test_z4mobrep015_source_recovery.py tests/test_mobile_human_review.py
```

Wynik obejmuje 49 testów importu folderu, 20 preferencji i wyboru plików, 3 kontraktu schematu, 15 odtwarzania źródła i 26 natywnej weryfikacji. Wszystkie zapisujące testy używają danych syntetycznych lub prywatnych katalogów testowych.

| Wymaganie | Pokrycie |
|---|---|
| T01–T04 | Selektor katalogów, ścieżka ręczna, pamiętanie ON/OFF, pierwszeństwo pola nad zaznaczeniem; błędy dostępu/dysku, pusty katalog i działająca ścieżka Windows >260 znaków. |
| T05–T07 | Dowolna struktura katalogów; domyślny profil ogólny; jawny profil F5A z istniejącą kontrolą ROI. |
| T08–T11 | Syntetyczne 32 PASS + 4 CONFLICT; pełne identyfikatory i szczegóły polityki; brak pojedynczego bloku; osobna klasyfikacja błędu ZIP. |
| T12 | Niekompletne role MT nie blokują importu; liczniki i przyczyny pochodzą z rekordów źródłowych. |
| T13–T14 | Idempotencja i zachowanie weryfikacji, ścieżki i SHA przy imporcie folderu oraz plików. |
| T15–T17 | Kopiowanie diagnostyki i anulowanie przed zatwierdzeniem; błąd jednego archiwum nie zatrzymuje reszty; worker poza wątkiem Tk, postęp i anulowanie skanu. |
| T18 | Zachowane importy pojedynczych/wielu plików, ZIP i wieloraportowego JSON; natywne ponowne otwieranie źródeł i próbek. |

Szersza regresja: **736 PASS / 29 FAIL / 2 SKIP**, 767 testów w 29 plikach, 123,59 s. Zakres: `test_z4mobrep*.py` oraz `test_mobile_report_full_rows.py`, `test_mobile_human_review.py`, `test_f5a_desktop_metadata.py`, `test_f5a12c_scene_evidence.py`, `test_f5a17_mz_input_evidence.py`, `test_f5a19_device_diagnostic.py`, `test_f5a21_tv_bbox.py` i trzy pliki importu/preferencji/schematu.

Wszystkie **29 FAIL** odtworzono na kopii **lokalnego stanu sprzed tego zadania**. Zbiory identyfikatorów niepowodzeń są identyczne: **0 nowych błędów**. Historyczne niepowodzenia dotyczą starszych oczekiwań etykiet, układu/wykresów i niepełnych obiektów testowych. Dwa SKIP dotyczą środowiska Tk: `test_integration_tk_bindtags_intercept_focused_treeview` oraz `test_tk_label_footer_physically_lies_below_plot_for_narrow_window`.

W pośrednich przebiegach wystąpiły też przejściowe błędy inicjalizacji Tcl/Tk; końcowy zestaw funkcji przeszedł w całości. Poprawiono nową asercję testu selektora, która porównywała obiekt indeksu Tcl zamiast jego wartości tekstowej. Nie ukrywano błędów produkcyjnych przez osłabianie walidacji lub oznaczanie nowych testów jako SKIP.

`git diff --check`: **PASS**. Audyt zmian względem lokalnego punktu startowego wykazał wyłącznie trzy wymienione moduły produkcyjne i dwa pliki testów; zastane pozostałe pliki zachowano.

## Ograniczenia i dowody

- Nie deklaruje się pełnego PASS repozytorium; pozostaje 29 historycznych błędów i 2 SKIP.
- Testy natywnych kontrolek Tk przechodzą. Osobna kontrola wizualna przez `computer-use` nie została ukończona: `FrameArrived timed out` i po ponownym odnalezieniu okna `window capture timed out`. Nie uzyskano zrzutu i nie deklaruje się wizualnego PASS. Testowe okno zamknięto bez dotykania działającego pokazu TV.
- Zapis F5A wymaga późniejszej decyzji operatora; w tym zadaniu zakończono na odczytowej kwalifikacji. Anulowanie trwającego importu działa między archiwami; wcześniejsze udane zapisy pozostają w magazynie.
- Zliczanie fizycznej obecności korzysta z odczytanych metadanych. Jeżeli archiwum jest nieczytelne lub skan niepełny, podsumowanie wyjaśnia, że liczby brakujących oryginalnych plików nie można rozstrzygnąć. Nie przypisuje brakujących plików na podstawie nazw.
- Profil ogólny nie poświadcza zgodności z F5A. Nie dodano osobnego magazynu odstępstw; konflikty są zachowane w diagnostyce dostępnej do skopiowania.

Dowody lokalne: `C:\Users\48572\AppData\Local\Temp\f5a-import-ux-q9lpi7j2` — `focused.xml`, `regression.xml`, `baseline-failures.xml`, `real-qualification.txt`, `real-qualification.json`, `original-source-before.json`, `workspace-before.json`, `delivery-sha256.json`.

## SHA-256 dostarczonego kodu i testów

| Plik | SHA-256 |
|---|---|
| `auto_annotation_tool/gui/z4_mobile_report_browser.py` | `c42eab5260e305d44b6fc7f6be9a97396547ff67a7e04e9b0e5369d185fffffb` |
| `auto_annotation_tool/ranking/mobile_package_experiments.py` | `13e337bd9ca229f060cc797407dad7241b3241eae897cf0de063c25a698ceed3` |
| `auto_annotation_tool/gui/mobile_import_preferences.py` | `0726aa697ccab3df187a3e86e3028067e715650d8fbb77fdd81335d745f6540a` |
| `tests/test_mobile_session_folder_import.py` | `a9ce3f08594e6c07afa4f31c8bc542c9ba50fdad12599f50a76b5c24243ce5b6` |
| `tests/test_z4_akt89k_import_preferences.py` | `f650b0c921aad431892894f9ae5b524bbc344e7314b36c5ad83c260889bb18a4` |
