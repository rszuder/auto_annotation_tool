# F5A — pochodzenie „2/10” i postęp operatora

Stan: **PASS dla poprawki i T01–T14; PARTIAL dla szerszych regresji repozytorium**.
Audyt dotyczy aktualnego lokalnego kodu `start4`, nie GitHub main. Kopię porównawczą kodu wykonano przed zmianą, razem z wcześniejszymi lokalnymi zmianami UX02.

## 1. Udowodniona przyczyna

Poprzedni tekst `Sprawdzone obrazy` powstawał w `gui/mobile_report_canvas_view.py`, funkcja `canvas_overview()`. Otrzymywał `inspected`, `total`, `remaining` z `science_from_verified_bundle()` w `gui/mobile_report_science_dashboard.py`.

Łańcuch obliczeń:

1. `MobileReviewSession` waliduje archiwum, odtwarza indeksy attempts/próbek i grupy wywołań MT. Jeśli istnieje sidecar, wczytuje go po zgodnym `session_id` oraz SHA archiwum. Bez sidecara tworzy wyłącznie w pamięci pusty `NOT_STARTED`, rewizja 0.
2. `mobile_canvas_presentation.build_inventory()` inicjalizuje liczniki od zera przy odczycie widoku. `total += 1` dla każdego `mt_invocation_id`.
3. `mobile_frame_review_state.from_scene()` daje pustemu zestawowi FINAL i GT stan `NO_REFERENCE_EVIDENCE`, `complete=True`, **`metric_complete=False`**. To stan techniczny zakresu oceny, bez deklaracji człowieka o braku tablic.
4. `review_progress()` traktuje ten stan jako rozstrzygnięty operacyjnie. `build_inventory()` zwiększa `inspected`, mimo braku zapisanej oceny, `checked=False` i `persisted=False`.
5. Warstwa prezentacji błędnie nazywała ten licznik „Sprawdzone obrazy” i używała go do paska postępu operatora.

**Stare 2/10 oznaczało dwa technicznie rozstrzygnięte wywołania MT z dziesięciu wywołań.** Nie oznaczało dwóch ocen człowieka, dwóch istniejących JPEG ani dwóch zweryfikowanych GT. Mianownik nie pochodził z pomiarów czasu, choć taki sam wynik liczbowy mógł sugerować ten związek. Licznik odtwarzał się bez decyzji operatora po otwarciu sesji, niezależnie od `review_status`.

Nie zmieniono predykatu operacyjnego ani metodologii F4. Oddzielono go od nowego, wyłącznie odczytowego zestawienia zapisanych ocen dla interfejsu.

## 2. Dokładne rekordy

Obie sesje znajdują się w `C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\02_sesje\R0\PAIRED_ROI_01\r01`.

| Archiwum | session_id | SHA-256 całego archiwum |
|---|---|---|
| `F5A_R0_r01_BLOK_A.alprsession` | `exp-1794214173596-2f59d697` | `f7185aefceba827f695ba59f44774445d081792872995a66f4814d3ad4996ff1` |
| `F5A_R0_r01_BLOK_B.alprsession` | `exp-1794215438762-0fbc7777` | `4a96dc95fc7129783f93deb34bfea386a8116f657d1e55c7c2f9ee84013ca2fa` |

| Blok | mt_invocation_id zaliczony do „2” | scene_event_id | source_sequence | source_timestamp_nanos |
|---|---|---|---:|---:|
| A | `exp-1794214173596-2f59d697-a00000002` | `exp-1794214173596-2f59d697-s00000002` | 9585 | 2064053852609000 |
| A | `exp-1794214173596-2f59d697-a00000005` | `exp-1794214173596-2f59d697-s00000005` | 11662 | 2064143859148000 |
| B | `exp-1794215438762-0fbc7777-a00000001` | `exp-1794215438762-0fbc7777-s00000001` | 17862 | 2065308642880000 |
| B | `exp-1794215438762-0fbc7777-a00000006` | `exp-1794215438762-0fbc7777-s00000005` | 20640 | 2065428219868000 |

Odpowiadające wpisy archiwum, w kolejności tabeli:

```text
samples/frames/tv-camera-bf82c699360c387b804c995df4fed7dda038bd12f3d10369092d415fd5850c2f.jpg
samples/frames/tv-camera-d99bf572756a32b8b7126cb361a742377e77c9fbf148a3598c72c74547d89a8a.jpg
samples/frames/tv-camera-a5f2879feaea5f423482dc8746dd9556d67472f0927e03dd4293a0894af4f19d.jpg
samples/frames/tv-camera-9b3ee3c8e7e5db120b6e657bebb2d56fff54e58e0200ba1ff85a22d6626f9415.jpg
```

Każdy z czterech rekordów ma wykonane MT, bez anulowania/błędu wykonania, `detection_count=0`, `mt_status=NO_DETECTION`, `mz_status=NOT_RUN`. Klatka ma `WRITTEN`; automatyczna projekcja Canvas ma puste objects/parents/events, `checked=False`, `persisted=False`, `NO_REFERENCE_EVIDENCE`. Żaden z tych stanów nie jest decyzją operatora.

| Dowód | A | B |
|---|---:|---:|
| Wywołania MT | 10 | 10 |
| Rekordy attempts | 11 | 16 |
| Cropy | 9 | 14 |
| SCENE_FRAME, wszystkie WRITTEN | 10 | 10 |
| Zapisane decyzje operatora | 0 | 0 |

Dla obu SHA nie istnieje kanoniczny `Workspace/7_rankings/mobile_packages/human_reviews/<SHA>.review.json`. W magazynie brak `human_review` dla tych raportów. Przeszukano również zawartość JSON w katalogu ocen oraz `F5A-ROI-A12-01/03_wyniki` pod kątem obu `session_id` i SHA: brak dopasowań. Zatem w miejscach odczytywanych przez aplikację nie ma wcześniejszych ocen człowieka dla tych archiwów. Nie zerowano ani nie usuwano żadnych ocen.

## 3. Definicja poprawionego licznika

**Jednostka obrazowa:** zarejestrowany obraz pełnej sceny, identyfikowany przez `scene_event_id`, ze zweryfikowanym powiązaniem źródłowym. Nie crop, attempt, wywołanie MT ani pomiar czasu.

**Mianownik:** liczba rekordów kompletnego, zwalidowanego rejestru SCENE_FRAME: rozszerzenie dostępne, `scene_evidence_complete=True`, brak nieznanych strat i wszystkie wymagane obrazy WRITTEN istnieją w archiwum. W A i B te warunki rzeczywiście dowodzą 10 jednostek. Niepełny lub nieobecny rejestr daje „Nie ustalono liczby obrazów do oceny” i ukryty pasek procentowy.

**Licznik:** liczba tych jednostek, dla których zapisany sidecar zawiera jawną decyzję człowieka i natywny walidator potwierdza jej powiązanie oraz rozstrzygnięcie oceny sceny. Pochodzenie obejmuje ścieżkę i SHA sidecara, rewizję, autora oraz datę; brak zapisanej informacji o autorze jest pokazany wprost. Samo wpisanie autora/zmiana trybu/statusu nie tworzy ocenionego obrazu. Częściowe decyzje dają „W toku”, nawet jeżeli nie rozstrzygają jeszcze całego obrazu.

Istniejące oceny MT/ROI mają osobny licznik. Nie są przeliczane na ocenione pełne sceny. Prawidłowe wcześniejsze sidecary są zachowane, a zatwierdzony eksport bez bieżącego sidecara pozostaje widoczny z pochodzeniem jako ocena archiwalna MT/ROI. Błędny lub obcy sidecar daje stan niepotwierdzony, nie fikcyjne zero.

W starszym eksporcie APPROVED_LIMITED pole `inspected` może zawierać techniczne N/A. Pozostaje ono wyłącznie w opisie archiwalnych stanów MT/ROI; nie zasila paska postępu operatora. Zachowane jest zatwierdzenie i pochodzenie eksportu.

Ocena obrazu i zatwierdzenie całej oceny GT/MT/MZ są odrębne. Ukończenie zapisanych ocen bez aktualnego eksportu nadal wymaga eksportu. Żadna dostępność JPEG, predykcja RAW/FINAL, wykonanie MP/MT/MZ ani walidacja ZIP/SHA nie podnosi postępu operatora.

Techniczne „2” pozostaje w sekcji dowodów pod nazwą **„MT/ROI bez referencji: 2”**, wraz z liczbą klatek, wywołań, attempts i cropów. Komunikat źródłowy mówi teraz wprost o integralności ZIP/SHA-256.

## 4. Zakres zmiany

- Nowy `ranking/mobile_operator_progress.py`: wyłącznie odczyt i wspólna prezentacja postępu. Nie jest magazynem ani nowym formatem raportu; jego oznaczenie schematu służy tylko wewnętrznym danym UI.
- `mobile_canvas_presentation.py`, `mobile_review_status.py`: dołączenie wspólnego zestawienia i etykiet; istniejące liczniki operacyjne oraz eksportowane klucze metryk zachowane.
- `mobile_report_canvas_view.py`, `mobile_report_science_dashboard.py`, `mobile_compare_review_gate.py`: nagłówek, pasek, pochodzenie, stan na liście sesji, rozróżnienie od eksportu GT/MT/MZ.
- `mobile_canvas_editor.py`, `mobile_canvas_clean_view.py`, `mobile_canvas_results_panel.py`, `mobile_canvas_scene_frames.py`: ten sam licznik w natywnym weryfikatorze i widoku pełnej sceny.
- `z4_mobile_report_browser.py`: w tym zadaniu wyłącznie dwa teksty o integralności źródła. Importer UX02 niezmieniony.
- Testy: nowy `test_mobile_operator_progress.py` oraz jedna aktualizacja oczekiwania starego testu AKT89F: nieudokumentowane `inspected/total` nie dowodzi populacji ocenianych obrazów.

## 5. Rzeczywiste wyniki testów

Windows, Python 3.12, natywny Tk. Wszystkie zapisy testowe dotyczą danych syntetycznych w katalogach tymczasowych. Użyte starsze fixture F5A/12A również mają `synthetic: true` w swoim delivery_manifest.

**Nowe testy: 21/21 PASS**, obejmujące wszystkie wymagania:

| ID | Sprawdzony warunek |
|---|---|
| T01 | Nowy import i status/reviewer bez decyzji nie tworzą postępu |
| T02 | Predykcje oraz automatyczne NO_REFERENCE nie są decyzjami człowieka |
| T03 | Dwie klatki bez GT: 0/2, mimo 10 pomiarów czasu |
| T04–T05 | Jedna i częściowe rzeczywiste decyzje; osobno pełne sceny i MT/ROI |
| T06 | Ukończone 10/10 odrębne od wymaganego eksportu GT/MT/MZ |
| T07 | Wznowienie zapisanych ocen i zachowanie ich SHA/rewizji |
| T08 | Obcy SHA/session_id, uszkodzony JSON, błędne powiązanie sceny/Canvas |
| T09 | Niepełna populacja: nieznany mianownik, bez zastępowania go czasami |
| T10 | Wspólne liczniki i statusy; natywny Tk, pasek i „Próbki i weryfikacja” |
| T11 | Postęp jednej sesji nie przenosi się do innej |
| T12 | Ponowny odczyt w osobnym procesie Pythona zachowuje zapis |
| T13 | Import nie zapisuje fikcyjnych GT/sidecarów i nie zmienia archiwum |
| T14 | Stare oceny MT/ROI, eksporty F4/Z4 i dotychczasowe metryki zachowane |

| Uruchomiony zestaw | Wynik |
|---|---|
| Główny: nowe testy, human_review, P2B1, P2B2, mt_blind_review, F5A metadata/scene_evidence, folder_import, UX02 preferences, AKT89F | **329 PASS, 4 FAIL** |
| 29 syntetycznych testów `test_z4_auto_frame_completion.py` bez fixture rzeczywistych sesji | **29 PASS** |
| Z4MOBREP016/018/023 i F5A desktop/scene Tk | **45 PASS, 18 FAIL, 1 SKIP** |
| Osobne ponowienie pominiętego `test_T28_existing_canvas_scene_scope_gestures[zero-roi-with-plate]` | **1 PASS** |
| Końcowe sprawdzenie ograniczonych eksportów: nowe testy + AKT89F bez preview wykresów | **32 PASS, 1 FAIL inicjalizacji Tk, 2 DESELECTED** |
| Osobne ponowienie AKT89F `test_native_primary_cards_history_collapsed_and_two_column_readability[1180]` | **1 PASS** |

Łącznie w trzech głównych uruchomieniach: **403 PASS, 22 FAIL, 1 SKIP**. Pominięty test miał przejściowy brak dostępności Tk i przeszedł osobno. Nie jest to wynik całego repozytorium.

Wszystkie 22 FAIL odtworzono na kopii aktualnego lokalnego kodu sprzed poprawki:

- P2B2: `test_flags_keep_geometry_and_gt_and_distinguish_model_vs_operator`, `test_correcting_gt_invalidates_checked_scene`, `test_zero_detection_requires_whole_roi_confirmation` — starsze oczekiwania komunikatu i reguł operacyjnych.
- AKT89F: `test_comparison_preview_keeps_titles_axes_and_model_legend_inside[1649x896]` — etykieta wykresu wychodzi poniżej figury.
- Z4MOBREP016: 9 wcześniejszych niezgodności starych oczekiwań UI; Z4MOBREP018: 2 wcześniejsze niezgodności wykresu/tekstu; Z4MOBREP023: 7 wcześniejszych niezgodności fixture/API.

Porównanie zbiorów nazw FAIL w trzech głównych zestawach przed/po: **brak nowych niepowodzeń**. Pierwszy przebieg wychwycił też stare oczekiwanie `0/19` z niewersjonowanego licznika operacyjnego — zaktualizowano je zgodnie z nowym wymaganiem nieznanego mianownika. Przejściowy błąd inicjalizacji Tcl w teście pickera nie powtórzył się w końcowym pełnym przebiegu. Przy końcowym sprawdzeniu eksportów wystąpił analogiczny błąd inicjalizacji `tk.tcl` w przypadku AKT89F `[1180]`; ten test przeszedł osobno, a wszystkie 21 nowych testów przeszło także w tym przebiegu.

`git diff --check`: PASS. Testy modeli, Androida i pomiary urządzenia: NOT_RUN.

Dowody odczytu, kopia bazowa i pliki JUnit znajdują się lokalnie w:

```text
C:\Users\48572\AppData\Local\Temp\f5a-operator-progress-o2t5kn2q
cause-audit.json          — dokładny stan i cztery rekordy przed poprawką
after-audit.json          — 0/10 dla A/B i kontrola ochrony danych
protected-before.json    — SHA, rozmiary i mtime 98 chronionych plików
final-focused.xml        — główny zestaw, w tym 21 nowych przypadków
auto-eligibility.xml     — 29 testów zachowania reguł MT
gui-regression.xml       — regresja starszych UI i natywnego Tk
gui-retry.xml            — ponowienie przejściowo pominiętego przypadku
baseline-failures.xml    — odtworzenie 4 FAIL przed zmianą
baseline-dashboard.xml  — odtworzenie 18 FAIL przed zmianą
final-view.xml          — końcowa kontrola eksportów i nowych testów
view-tk-retry.xml       — osobne ponowienie AKT89F [1180]
final-protection.json   — końcowy audyt danych i niezmienionych funkcji importera
```

## 6. Odbiór wizualny i ochrona danych

Odczyt oryginałów po poprawce potwierdził w obu sesjach:

```text
Weryfikacja operatora: Nie rozpoczęto
Obrazy ocenione przez operatora: 0/10
Dowody: SCENE_FRAME 10/10; MT/ROI bez referencji: 2
```

Instrukcja ręcznego odbioru, bez importowania ani zapisywania ocen produkcyjnych:

1. Uruchom Desktop ponownie, aby załadować zmieniony kod. Otwórz już istniejący raport bloku A.
2. Sprawdź status na liście, nagłówek „Weryfikacja operatora”, licznik 0/10 i pusty pasek (0%). Przy liczniku nie powinno być dawnego 2/10.
3. Sprawdź sekcję dowodów: 10 zapisanych pełnych klatek i 2 wywołania MT bez referencji. Opis integralności źródła ma wyraźnie mówić ZIP/SHA-256.
4. Otwórz „Próbki i weryfikacja” w trybie odczytu, przełącz pełne sceny. Postęp całej sesji powinien nadal wynosić 0/10, a ocena GT/MT/MZ pozostawać nieukończona.
5. Przejdź do bloku B, wróć do A, zamknij i ponownie otwórz przeglądarkę. Obie sesje powinny zachować swój stan 0/10.
6. Przypadki zapisu 1/10, wznowienia oraz nieznanego mianownika sprawdzaj wyłącznie przez testy syntetyczne `python -m pytest -q tests/test_mobile_operator_progress.py`.

Automatyczne testy natywnego Tk przeszły; **ręczny odbiór wizualny przez operatora: NOT_VERIFIED**. T12 obejmuje nowy proces odczytu oceny, nie ręczny restart całej aplikacji.

Kontrola SHA/rozmiaru/mtime: **98/98 chronionych plików bez zmian**, w tym obie oryginalne sesje, magazyn i istniejące oceny/wyniki. Nie przybyły pliki w human_reviews ani 03_wyniki. Magazyn nadal zawiera 79 raportów; jego SHA pozostało `46f7ed2e3378469547c16d8847eb4bacdc4701b50364ea4b08af10cb2fa32256`. Nie wykonano ponownego importu, zmian GT/inferencji/metryk/Androida ani commit/push.
