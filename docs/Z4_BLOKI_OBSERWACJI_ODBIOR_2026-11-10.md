# Z4 — nawigacja według bloków obserwacji sceny

Data: 10.11.2026. Repozytorium: `C:\Users\48572\Desktop\dyplom\start4`.

Wdrożono grupowanie nawigacyjne według udokumentowanych zdarzeń zmiany sceny, zgodnie ze zmienionym wymaganiem operatora. Dla poprawnego K02/B istnieje jedna lista **10 bloków obserwacji**, zawierająca **44 unikalne wywołania MT** i **51 powiązanych wyników MZ**. Wykorzystano dotychczasowy Canvas i magazyn ocen Z4.

**Testy dedykowane: PASS, 31/31. Rozszerzone regresje: PARTIAL. Odbiór wizualny operatora: NOT_VERIFIED.** Testy zdarzeń natywnego Tk nie stanowią akceptacji wyglądu ani ergonomii przez operatora. Nie uzyskano użytecznego zrzutu okna aplikacji: pulpit był zablokowany.

Poprzedni [audyt K02](Z4_K02_AUDYT_BLOKOW_STABILNEJ_SCENY_2026-11-10.md) pozostaje dokumentem historycznym. Nowa decyzja operatora pozwala grupować przedziały obserwacji bez potwierdzenia stabilności. **Stabilność pozostaje N/A**; bloki nie dowodzą początku stabilności ani tożsamości fotografii TV.

## 1. Zmienione pliki i funkcje

| Plik | Zmiana w tym zadaniu |
|---|---|
| `auto_annotation_tool/gui/mobile_canvas_observation_blocks.py` | Nowy adapter listy. `build_blocks()` weryfikuje granice i przypisania; `_call_state()` odczytuje istniejące statusy; `render()` aktualizuje istniejący Treeview; `select()` i `sync_selection()` synchronizują wybrany dowód; `open_gid()`, `navigate()`, `next_pending()` obsługują istniejące wejścia nawigacyjne; `resume()` odtwarza kliknięcie odłożone podczas zapisu. |
| `auto_annotation_tool/gui/mobile_canvas_editor.py` | Integracja adaptera w `refresh_tree()`, `sync_tree_selection()`, `select_tree_row()`, `open_result_image()`, `navigate()` i `next_pending()`. Zachowana stara ścieżka dla sesji niekwalifikujących się do grupowania. |
| `auto_annotation_tool/gui/mobile_canvas_scene_frames.py` | `context()` pokazuje przedział względem początku sesji oraz `Stabilność: N/A` dla aktywnego bloku. |
| `auto_annotation_tool/gui/z4_mobile_sample_review.py` | `_poll()` wznawia odłożoną nawigację po udanym istniejącym zapisie; przy błędzie usuwa odłożony cel. |
| `tests/test_mobile_observation_blocks.py` | 31 testów syntetycznych i testów prywatnej kopii K02, w tym rzeczywiste zdarzenia Tk. |
| `tests/test_z4_canvas_linked_measurement_tree.py` | Udostępnienie prawdziwego adaptera bloków w izolowanym, sztucznym pakiecie testowym. Brak rejestru scen nadal uruchamia starą nawigację. Nie zmieniano asercji starszych testów. |
| `docs/Z4_BLOKI_OBSERWACJI_ODBIOR_2026-11-10.md` | Niniejszy raport. |

`ranking/mobile_canvas_presentation.py` jest wykorzystywany przez istniejący `inventory()`, bez zmian jego logiki. Nie zmieniano modułów metryk, importera, Z2, kampanii ani Androida. Zachowano wcześniejsze lokalne poprawki w edytowanych plikach.

## 2. Struktura listy operatora

```text
Bloki obserwacji sceny
└─ Scena 01 — Do oceny
   MT: 2 · Zadań: …
   ├─ Pełna klatka — ocena sceny
   │  Do oceny / Brak tablic potwierdzony / Oceniono
   ├─ Wywołania MT/ROI (…)
   │  └─ MT 01 — Do oceny / Oceniono
   │     FINAL: … · Zapisane: …
   ├─ Powiązane wyniki MZ (…)
   │  └─ MZ 01 — Zapisany wynik / Brak odczytu / Wynik ukryty
   └─ Niepełne / anulowane (…)       [jeżeli występują]
      └─ MT 01 — Anulowano · N/A / Niepełne · N/A
         RAW: … · FINAL: N/A

Dowody nieprzypisane / niepełne       [jeżeli występują]
└─ wywołania, próby, wyniki lub odwołania bez pewnego przypisania
```

Nie ma równoległej listy „Obraz 01–10”. Liczby w opisach mają odrębne znaczenie:

- **MT**: liczba wywołań z potwierdzonym przypisaniem do bloku, a nie liczba tablic.
- **Zadań**: nieoceniona pełna klatka i zadania oceny przypisanych, ocenialnych MT. Techniczne N/A nie tworzy fikcyjnego zadania rozstrzygnięcia detekcji.
- **FINAL**: liczba źródłowo potwierdzonych końcowych detekcji. Nieustalona rola pozostaje N/A.
- **Zapisane**: rozstrzygnięcia z istniejącego stanu oceny MT, liczone tylko przy zapisanej ocenie. Nie jest to liczba wszystkich detekcji ani liczba wykonanych modeli.

Zatwierdzona pełna klatka z oczekującymi MT daje status bloku „MT do oceny”. Niewyjaśnione, zadeklarowane powiązanie albo niepełne wywołanie nie pozwala oznaczyć całego bloku jako ocenionego. Sama pełna klatka zachowuje własny status. Nie zmieniono globalnych zasad zatwierdzania raportu ani liczników naukowych.

## 3. Podstawa grupowania i bezpieczeństwo powiązań

Adapter korzysta z już zweryfikowanego `MobileReviewSession` i `MobileReportBundle`; nie skanuje ponownie archiwum przy odświeżaniu drzewa.

Warunkiem włączenia grupowania są: poprawna walidacja źródła, niesprzeczny `analysis_mode=static`, kompletny rejestr scen, znany początek i koniec obserwacji, jednoznaczne identyfikatory i rosnące czasy zdarzeń. Brak dowodu, tryb dynamiczny lub sprzeczne metadane zachowują dotychczasową nawigację.

Źródła:

1. `collection_session` / metadane wykonania: `analysis_mode`, `started_elapsed_nanos`, `finished_elapsed_nanos`, `scene_evidence_expected`, `scene_evidence_complete`, `scene_evidence_pending_loss_unknown`.
2. `samples/scene_evidence.jsonl`: `scene_event_id`, `session_id`, `event_type`, `event_elapsed_nanos`, `event_stamp`, `mt_invocation_ids`. Pierwszy przedział zaczyna `SESSION_START`, następne `SCENE_BOUNDARY`; ostatni kończy zapisany `finished_elapsed_nanos`.
3. `samples/mt_detection_roles.jsonl`: `mt_invocation_id`, `scene_event_id`, `source_stamp`, `raw_attempt_ids`, `final_attempt_ids` i statusy kompletności/anulowania.
4. Próby i wyniki w istniejącym modelu sesji: `attempt_id`, `mt_invocation_id`, ewentualne `f5a_scene_event_id`, `mt_detection_index`, `mz_executed` oraz odwołania próbek do prób.

Pełny stamp obejmuje `scene_generation`, `visual_epoch`, `camera_transform_generation`, `source_sequence`, `source_timestamp_nanos`, `source_timestamp_domain`. Stamp wejścia MT musi odpowiadać jego rzeczywistym rekordom prób. Generacja, epoka, transformacja i domena muszą być zgodne ze zdarzeniem sceny; sekwencja wejścia nie może poprzedzać zdarzenia. Weryfikowane jest też jednoznaczne odwołanie sceny do wywołania i zgodność zbioru prób RAW.

Nie używa się nazw plików, numeru wiersza, wyniku OCR, czasu zakończenia inferencji ani domyślnej liczby dziesięciu scen do ustalania przynależności. Liczba bloków pochodzi z rejestru; testy obejmują także 1, 3 i 12 bloków.

Nie wymaga się identyczności stampu reprezentatywnej `SCENE_FRAME` i wejścia MT. Kliknięcie bloku otwiera `open_scene()`; kliknięcie MT używa `_multi_focus_attempt()` i `_select_record()`. Wynik MZ kieruje do konkretnej źródłowej próby oraz istniejącego wskazania FINAL, jeśli takie wskazanie jest dostępne. Nie powstaje obiekt GT na podstawie samego wyniku MZ.

Nie zmieniono `source_binding`, obrazów, transformacji geometrii ani zasad zapisu ocen. Nie kopiuje się polygonów między różnymi klatkami. Nawigacja zachowuje wybór wyniku, rozwinięcia gałęzi i viewport podczas odświeżenia tego samego źródła. Zmiana rzeczywistego obrazu korzysta z dotychczasowego zachowania Canvas.

## 4. Niepełne dowody i przypadki K02

- Bloki 04 i 05 istnieją mimo zera MT. Rozpoczynają jako nieocenione; `NO_PLATES` wymaga osobnej, świadomej decyzji operatora.
- Trzy anulowane wywołania pozostają przy swoim źródłowym zdarzeniu. Późne anulowanie lub zakończenie nie przenosi ich do kolejnego bloku.
- Cztery rekordy z nierozstrzygniętą rolą nie są awansowane do FINAL.
- Uszkodzone, nieobecne, sprzeczne lub wielokrotne powiązanie trafia do diagnostyki. Powiązane wyniki MZ i osierocone odwołania nadal są reprezentowane; żaden rekord źródłowy nie jest usuwany.
- Wyniki MZ respektują dotychczasową widoczność predykcji w trybie ślepej oceny.
- W K02 wszystkie 44 wejścia MT mają inne pełne stampy niż reprezentatywne klatki scen. Ocena sceny i oceny MT pozostają oddzielne.

## 5. Testy i ograniczenia

Testy zapisujące używały `tmp_path`, syntetycznych archiwów albo prywatnej kopii K02. Procesy miały odrębny profil, katalog roboczy i katalogi wyników poza produkcyjnym Workspace. Nie uruchamiano modeli.

| Zestaw | PASS | FAIL |
|---|---:|---:|
| Nowe bloki obserwacji, końcowy przebieg `focused_verified` | 31 | 0 |
| Pełne sceny, MT/MZ, model ocen, kontrakty raportów — `core` | 230 | 5 |
| Postęp operatora | 21 | 0 |
| Pełne sceny — natywny Tk | 13 | 0 |
| Starsze testy Canvas GUI | 5 | 5 |
| Starsze testy Canvas UX | 17 | 17 |
| Starsze testy zaznaczania i drzewa | 7 | 21 |
| Starsze testy skrótów | 0 | 12 |
| Import folderów UX02 | 71 | 0 |
| Preferencje importera | 20 | 0 |
| Izolowany starszy test listy powiązanych obrazów | 0 | 7 |
| Istniejący nawigator warstw, 32 wybrane testy syntetyczne | 24 | 8 |

Rozszerzony zestaw obejmował **483 przypadki: 408 PASS, 75 FAIL**. **74 błędy odtworzono również na prywatnej kopii kodu sprzed tego zadania**, zachowującej wcześniejsze lokalne modyfikacje. Dotyczą m.in. historycznych oczekiwań komunikatów, zachowania dawnych kontrolek/skrótów, reguł ocen i brakującego `review_progress` w starej atrapie modułu testowego. Nie poprawiano backendu ani nie osłabiano tych asercji w celu uzyskania zielonego wyniku.

Pozostały przypadek, `test_native_corner_drag_keeps_original_and_does_not_add_a_plate`, nie przeszedł w pierwszym zbiorczym przebiegu, ale przeszedł przy osobnym ponowieniu aktualnego kodu oraz na kopii sprzed zmiany. Jest traktowany jako niestabilny wynik testu Tk, nie jako udowodniona naprawa ani potwierdzona regresja. Dwa niewybrane przypadki nawigatora wymagające historycznej prywatnej sesji lub dawnego protokołu odbioru nie są zaliczone do wykonanych testów.

Dedykowane testy potwierdziły: granice 9→10; zmienną liczbę bloków; zero i wiele MT; wiele podmiotów bez duplikowania wywołań; różne stampy; anulowanie po zmianie; niepełne role; uszkodzone powiązania i zachowanie diagnostyki; dynamiczny powrót do starej listy; wybór konkretnego MT/MZ; zachowanie wyboru, rozwinięcia i viewportu; D, tekst inline, autosave, Enter i Spację; cofnięcie i ponowienie; kolejkę wyboru podczas zapisu; zamknięcie i ponowne otwarcie okna; niezależność ocen sceny i MT; niezmienność statystyk, sidecara i SHA źródła przy samej nawigacji.

Dowody wykonania, logi i JUnit XML znajdują się w:

```text
C:\Users\48572\AppData\Local\Temp\z4_observation_blocks_wsd05h0k
```

Końcowy test dedykowany: `focused_verified.xml`. Zestawy porównawcze: `baseline_core.xml`, `baseline_canvas_gui_full.xml`, `baseline_canvas_ux.xml`, `baseline_canvas_selection.xml`, `baseline_canvas_keys.xml`, `baseline_legacy_tree.xml`, `baseline_navigator.xml`. Ponowienie pojedynczego testu przeciągania: `corner_current.xml`.

## 6. Ochrona danych i metryk

- Oryginalny K02/B zachował SHA-256 `140c20115cf34c67de7e591752b540d152ec07fea2bf7488a8546e97d8899a10`.
- Wszystkie **47 kontrolowanych plików** zachowały SHA-256, rozmiar i czas modyfikacji: oryginalny K02, magazyn raportów, plik preferencji oraz kontrolowane pliki ocen operatora.
- Magazyn zachował **83 raporty i 83 wpisy scores**. Nie importowano duplikatów ani nie zapisywano nowych ocen do produkcyjnego magazynu.
- Kontrola 264 wcześniejszych plików wykazała zmiany wyłącznie w trzech wskazanych plikach GUI oraz w opisanym adapterze starego testu. Żaden wcześniejszy plik nie zniknął. Nowe pliki to moduł nawigacji, jego testy i ten raport.
- Nie zmieniano TP/FP/FN, IoU, NMCE, CER, mianowników, populacji FINAL ani algorytmu dopasowania. Test na prywatnym K02 porównał pełne wyniki `statistics()` przed i po grupowaniu/nawigacji oraz potwierdził 44 MT, 51 MZ, 53 FINAL i 4 nierozstrzygnięte role.
- Nie zmieniano produkcyjnego runu Z2 F5A, fotografii, manifestów, logów TV, Androida, APK ani archiwów. Nie wykonywano reset/checkout/clean, commit ani push.

## 7. Odbiór wizualny na istniejącym K02

1. Uruchomić ponownie ALPR Desktop, aby wczytać zmieniony kod. Otworzyć **Raporty z telefonu** i wybrać istniejący poprawny raport K02/B, bez ponownego importu. Wyszukiwanie `KOREKTA_K02` może pomóc, ale ostatecznie sprawdzić źródło `F5A_R1_r02_BLOK_B_K02.alprsession`, sesję `exp-1794265037188-43dc06b8` i wskazaną wyżej sumę SHA.
2. Wejść do **Weryfikacji próbek**. Sprawdzić, czy istnieje jedna lista „Bloki obserwacji sceny” z dziesięcioma głównymi pozycjami „Scena”, bez równoległych „Obraz 01–10”.
3. Kliknąć Scenę 01: powinien otworzyć się pełny obraz SCENE_FRAME. Sprawdzić przedział obserwacji i opis „Stabilność: N/A”. Rozwinąć MT/ROI i MZ; ocenić czytelność nazw i statusów przy normalnym rozmiarze okna oraz po jego zwężeniu.
4. Wybrać MT wewnątrz bloku, następnie konkretny MZ w bloku z wieloma wynikami. Canvas ma pokazać rzeczywisty obraz wejścia MT i właściwe wskazanie, a nie utrzymać reprezentatywną SCENE_FRAME z przeniesionymi polygonami.
5. Zmienić zoom i położenie obrazu, ponownie wybrać ten sam dowód i odświeżyć listę. Sprawdzić brak niezamierzonego przeładowania obrazu oraz zachowanie wybranego wyniku i rozwinięcia gałęzi.
6. Sprawdzić Sceny 04 i 05: są dostępne przy `MT: 0`, a brak MT sam nie potwierdza braku tablic. Sprawdzić także gałęzie anulowanych/niepełnych MT; mają N/A, a nie fikcyjny FINAL lub ocenę operatora.
7. Kontrolę zapisu wykonać na **prywatnej kopii archiwum i sidecara**, z oddzielnym katalogiem ocen: D, cztery narożniki, istniejące pole GT inline, Enter/autosave, Spacja, cofnięcie/ponowienie, zamknięcie i wznowienie. Ocena pełnej klatki nie może sama zatwierdzić pozostałych MT. Produkcyjnego K02 używać w tym odbiorze do nawigacji i oglądania; nie zapisywać testowych decyzji.

Operator powinien osobno potwierdzić czytelność listy, poprawność przełączania dowodów i komfort pracy. **Takiego potwierdzenia jeszcze nie otrzymano.**
