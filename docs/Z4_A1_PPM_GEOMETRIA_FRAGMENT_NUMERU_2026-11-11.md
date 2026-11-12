# Z4 / GT fotografii — PPM, orientacyjna lokalizacja i fragment numeru

Data: 11.11.2026. Zakres: lokalne rozszerzenie A1 w istniejącym Canvas.

**Implementacja i testy dedykowane: PASS. Odbiór wizualny operatora: NOT_VERIFIED.** Szersza regresja nie jest w całości zielona: odtworzono 17 wcześniejszych niepowodzeń na kopii kodu sprzed zmiany. Szczegóły poniżej.

## 1. Chronione dane

Produkcyjna referencja:

`C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\01_materialy\04_GT_FOTOGRAFII_Z4\reference_v1.json`

- Przed i po: **40/40**, rewizja **411**, schemat `alpr.photo_reference.v1`.
- Rozmiar: **835640 bajtów**.
- SHA-256 przed i po: `4fb2033ecd7c30872329b494f275b15b07a42e392b6a29c6c5e748068c8fbae0`.
- `mtime_ns`: `1794358401350862900`, bez zmiany.
- **140/140** monitorowanych plików zachowało SHA, rozmiar i czas modyfikacji. Zestaw obejmuje fotografie i kopie TV, manifesty, referencję, istniejące oceny Desktop oraz pozostałe wcześniej chronione artefakty. To kontrola wskazanego zestawu, nie deklaracja pełnego haszowania wszystkich archiwów F4/F5A.
- Nie migrowano produkcji, nie zmieniano jej decyzji, nie uruchamiano modeli, nie wykonywano commit/push/reset/checkout/clean/stash.
- Wcześniejsze lokalne zmiany pozostały zachowane. Spośród istniejących plików Python zmieniono wyłącznie trzy wskazane niżej.

Prywatne zabezpieczenie, stan kodu sprzed poprawki, środowisko testowe, XML wyników i kontrola SHA:

`C:\Users\48572\AppData\Local\Temp\z4_photo_ppm_5e2tqsa6`

Kopia referencji: `production_reference_before.json`. Pliki dowodowe: `production_before.json`, `protected_before.json`, `verification_receipt.json`, `before.patch`, `ppm_changes.patch`, `baseline/`.

## 2. Zmienione pliki i odpowiedzialności

| Plik | Zmiany |
|---|---|
| `auto_annotation_tool/ranking/photo_reference.py` | `text_kind`, `display_text`, `text_complete`, `geometry_kind`, `_explicit`; walidacja v1/v2, `complete`, `PhotoReference.add/edit/_change/_save/scene`; kopia przed pierwszym zapisem v2, zachowanie historii i ochrony przed równoległym zapisem. |
| `auto_annotation_tool/gui/z4_photo_reference.py` | `PhotographCanvasSource.context_menu`, `set_text_kind`, `begin_geometry`, `source_point`, `location_hit/press/motion/release`, `prepare_location`, `cancel_location`, `paint_presence_only`, `paint_location_draft`, `text_caption`; obsługa menu, podglądu i przeciągania na istniejącym Canvas. |
| `auto_annotation_tool/gui/mobile_canvas_editor.py` | Warunkowe wywołania adaptera fotograficznego w istniejących `hit`, `press`, `motion`, `release`, `escape`, `prepare_navigation`, `draw_toggle`; odczyt fragmentu w istniejącym `start_entry`, PPM pola inline, opis fragmentu na etykiecie, podgląd lokalizacji. |
| `tests/test_z4_photo_reference_context.py` | 31 dedykowanych przypadków, w tym parametryzacje, natywne zdarzenia Tk, prywatna kopia rzeczywistych 40 ocen i syntetyczne źródła EXIF. |
| Niniejszy dokument | Kontrakt, dowody, ograniczenia i instrukcja odbioru. |

Nie dodano drugiego Canvas ani mechanizmu nawigacji. Nie zmieniono układu okna, dolnego paska, Z2, mobilnego modelu danych, importerów, scorerów ani Androida. Domyślny mobilny profil Canvas zachowuje swoje działanie PPM; nowe odgałęzienia działają przy `reference_source`.

## 3. Obsługa PPM

Wejście: **Raporty z telefonu → GT fotografii**.

PPM na wolnym obszarze fotografii:

```text
Dodaj tablicę
  Dokładne 4 narożniki
  Przybliżony obszar → powód braku dokładnych narożników
  Wskaż punktem      → powód braku dokładnych narożników
Na zdjęciu nie ma tablic
```

Ostatnia pozycja jest wyłączona, gdy istnieją tablice. Kliknięcie tła nie kieruje menu do poprzednio zaznaczonego obiektu. Menu dodawania nie pozwala umieścić punktu w pustym marginesie Canvas.

PPM na obrysie, etykiecie, polu inline, orientacyjnym obszarze albo punkcie:

```text
Numer
  Wpisz pełny numer
  Wpisz fragment numeru
  Numer nieczytelny
Geometria
  Dokładne 4 narożniki
  Przybliżony obszar → powód
  Punkt lokalizacji → powód
Usuń tablicę
```

Powody dostępne bez osobnego formularza, w menu: „Ucięta krawędzią obrazu”, „Częściowo zasłonięta”, „Granice niewyraźne”, „Nie można ustalić narożników”. Dla starszego obiektu dostępne jest zachowanie jego dotychczasowego powodu. Powód nie jest zgadywany z pliku ani z modelu.

Po wyborze obszaru operator przeciąga myszą po widocznym fragmencie. Punkt korzysta z miejsca PPM, jeśli kliknięto faktyczną powierzchnię fotografii/oznaczenia. PPM na etykiecie lub polu tekstowym nie jest lokalizacją tablicy — wtedy operator wskazuje punkt na zdjęciu. Obszar i punkt można przeciągać. D pozostaje dotychczasowym rysowaniem czterech narożników.

## 4. Kontrakt danych

Magazyn pozostaje ten sam: **`reference_v1.json`**. Nazwa pliku nie oznacza, że nowy dokument ma nadal schemat v1.

- Odczyt obsługuje `alpr.photo_reference.v1` oraz `alpr.photo_reference.v2`.
- Otwarcie nie migruje ani nie zapisuje dokumentu. Nawigacja może zapisać dotychczasowy kursor, bez migracji starych obiektów.
- Pierwsza edycja tablicy lub dodanie tablicy z jawnymi polami zapisuje schemat v2. Decyzje `NO_PLATES` bez obiektów nie potrzebują nowych pól.
- Każdy nowy/edytowany obiekt ma `decision_version: 2`. Nie przepisuje się pozostałych obiektów ani dawnych wersji historii.
- Przed zmianą istniejącego pliku z v1 na v2, pod tą samą blokadą zapisu, powstaje kopia dokładnych poprzednich bajtów: `reference_v1.pre-v2-<SHA256>.json`. Istniejąca kopia nie jest nadpisywana. Błąd jej utworzenia blokuje zmianę referencji.
- Nadal działają rewizja, niezmienne wersje historii, undo/redo, atomic write i kontrola równoległego zapisu. Stary kod obsługujący tylko v1 odmówi odczytu v2 zamiast pomylić fragment z pełnym numerem.

| Geometria | Dane aktywne | Znaczenie |
|---|---|---|
| `EXACT_QUAD` | `quad` z czterema rzeczywistymi punktami | Dokładny obrys; nie stanowi samodzielnego dowodu kwalifikacji do każdej metryki. |
| `APPROXIMATE_REGION` | `quad: null`, `approximate_region: [left, top, right, bottom]`, powód | Obszar widocznego fragmentu, nie dokładny BBOX/Pose. |
| `APPROXIMATE_POINT` | `quad: null`, `approximate_point: [x, y]`, powód | Orientacyjna lokalizacja, nie obrys. |

Współrzędne: `exif_transposed_source_pixels`. Przeliczenia ekranu korzystają z istniejących `to_source` i `to_canvas`. Walidacja odrzuca dane poza fotografią, NaN, niespójne rodzaje i zerowy/odwrócony obszar. Przesuwany obszar zachowuje rozmiar i pozostaje w granicach fotografii.

Starsze `quad=null` bez lokalizacji pozostaje poprawne z zachowaniem powodu. Techniczny stan `UNAVAILABLE` zachowuje tę zgodność; nie jest dodatkową opcją rysowania. Etykieta bez lokalizacji zachowuje dotychczasowe zachowanie, a po wskazaniu położenia jest przy znaczniku. Konwersja dokładnego obrysu na orientacyjny usuwa quad z aktywnej wersji; wcześniejszy quad zostaje w historii.

| Tekst | Zapis | Znaczenie |
|---|---|---|
| `FULL_TEXT` | `gt_text`, pusty `partial_text` | Pełny numer. |
| `PARTIAL_TEXT` | pusty `gt_text`, `partial_text`, jawny powód wyłączenia pełnej oceny tekstu | Fragment; etykieta „Fragment: …”. |
| `UNREADABLE_TEXT` | oba pola tekstowe puste, `text_exclusion_reason` | Jawnie nieczytelny numer, nie brak decyzji. |

Pusty wpis nie staje się automatycznie nieczytelnością. `UNRESOLVED` pozostaje stanem niedokończonej edycji. Pusty fragment lub pusty pełny numer nie jest kompletną oceną. Odczyt starych danych nie zmienia znaczenia krótkich numerów: stare `GWE` nadal znaczy pełny tekst do czasu świadomego wyboru „Wpisz fragment numeru”.

Przykład nowych pól obiektu (pozostałe dane i ID zachowane):

```json
{
  "decision_version": 2,
  "geometry_kind": "APPROXIMATE_POINT",
  "quad": null,
  "approximate_point": [1505, 954],
  "approximate_region": null,
  "geometry_exclusion_reason": "Tablica ucięta krawędzią fotografii",
  "text_state": "PARTIAL_TEXT",
  "gt_text": "",
  "partial_text": "GWE",
  "text_exclusion_reason": "Znany tylko fragment numeru"
}
```

To przykład z prywatnego testu, nie zmiana produkcyjnej decyzji. Identyfikacja fotografii pozostaje w mapach `images`/`reviews` przez `img-sha256-<SHA>`; identyfikator tablicy `PGT:…`, `relative_path` i źródłowy SHA są zachowane.

Orientacyjne dane nie są zamieniane na quad, BBOX GT, IoU, NMCE ani dowód pokrycia ROI. Fragment nie trafia do pola pełnego numeru dla Exact Match/CER. W tym zadaniu nie wprowadzono żadnego scorera. Rozstrzygnięty fragment/nieczytelność i geometria N/A mogą dawać „Gotowe”, bez deklarowania naukowej ocenialności danej metryki.

## 5. Wyniki testów i ograniczenia

Wszystkie testy zapisujące działały na syntetycznych źródłach albo prywatnych kopiach. Profil aplikacji, katalog roboczy i konfiguracja były odseparowane od produkcji.

| Uruchomienie | PASS | FAIL | SKIP |
|---|---:|---:|---:|
| A1 + nowe PPM/geometria/tekst (`photo_final.xml`) | 56 | 0 | 0 |
| Mobilny Canvas, nawigator i ochrona spóźnionego wyboru (`mobile_gui.xml`) | 46 | 15 | 0 |
| Zapis, historia, scene evidence, GT Pack (`persistence.xml`) | 129 | 3 | 0 |
| Importer folderów i preferencje UX02 (`ux02.xml`) | 91 | 0 | 0 |
| Bloki obserwacji (`blocks.xml`) | 31 | 0 | 0 |
| Odtworzenie 18 niepowodzeń na kodzie sprzed poprawki (`baseline_failures.xml`) | 1 | 17 | 0 |
| Ponowienie pełnej sceny i ochrony wyboru na nowym kodzie (`scene_repeat.xml`) | 16 | 0 | 1 |
| Końcowy test rzeczywistej prywatnej kopii po doprecyzowaniu położenia (`real_copy_final.xml`) | 1 | 0 | 0 |

Nie należy sumować powtórek jako odrębnych przypadków. Wcześniejsze 17 niepowodzeń obejmuje 9 testów `test_z4_one_navigator`, 5 starszych testów `test_mobile_p2b2_canvas_gui` oraz 3 `test_mobile_p2b2_canvas_review`. Odtworzono te same przypadki na zabezpieczonym kodzie sprzed poprawki, bez wycofywania lokalnych zmian w worktree.

Pozostałe niepowodzenie pierwszego przebiegu było timeoutem Tk w `test_T28_existing_canvas_scene_scope_gestures[two-roi]`: przeszło zarówno na kopii bazowej, jak i w ponowieniu bieżącego kodu. W powtórce inny test (`test_T19_native_menu_two_final_links_and_source_rows`) zgłosił `SKIP: Tk display required`; wcześniej ten przypadek przeszedł. To ograniczenie środowiska testowego, a nie zaliczony odbiór wizualny.

Natywne menu Windows wymaga interakcji w systemowej pętli menu. Próbę testu czekającego na takie menu przerwano, kończąc wyłącznie prywatny proces pytest. Zakończone testy sprawdzają rzeczywiste bindingi Tk, kontekst, strukturę i polecenia menu, zastępując tylko `tk_popup`. Nie deklarują oceny wyglądu ani ergonomii otwartego menu.

Pokrycie nowego zakresu obejmuje wszystkie rodzaje kontekstu PPM, trzy stany tekstu niezależne od trzech rodzajów geometrii, konwersje z zachowaniem ID, historię i undo/redo, autozapis i Ctrl+S, ponowne otwarcie, NO_PLATES, stare 40/40, przeciąganie bez zapisu podglądu, Esc, blokadę nawigacji po błędzie zapisu, ponowienie, backup i konflikt zapisu, zoom/pan/resize/letterbox/krawędzie, EXIF oraz brak sztucznej referencji geometrii/pełnego OCR.

### Rzeczywisty przypadek GWE

W aktualnym manifeście TV jest to **fotografia 39, tablica 4**, a nie 40. SHA fotografii: `450b50a3cd05fe97b1b6b23e0c139c8ee6bf85ae0b9d82e9d82a505254142ab1`. ID tablicy: `PGT:f87de896a38641f7ad531d71fb8a3321`.

Na prywatnej kopii zachowano ten sam ID i powód, dodano orientacyjny punkt `(1505, 954)` przy widocznym fragmencie na prawej krawędzi fotografii 1520×1528, wybrano `PARTIAL_TEXT: GWE`, a następnie sprawdzono ponowny odczyt i 40/40. Położenie pochodzi z odczytu obrazu; jest wyłącznie punktem testowym, nie dokładną geometrią ani zatwierdzoną decyzją operatora. Produkcyjna tablica pozostała bez zmian. Analogiczny przypadek fotografii 40/tablicy 4 jest dodatkowo objęty syntetyczną referencją.

## 6. Krótki odbiór operatora — jeszcze niezaliczony

1. Uruchom ponownie Desktop, otwórz **Raporty z telefonu → GT fotografii** i wskaż dotychczasowy katalog `02_MATERIAL_ZATWIERDZONY`. Sprawdź stare oznaczenia i **Gotowe: 40/40**. Nie twórz nowego runu.
2. PPM na wolnym fragmencie fotografii: sprawdź trzy sposoby dodawania. Przy istniejących tablicach decyzja „Na zdjęciu nie ma tablic” ma być wyłączona. Próbne dodawanie/usuwanie wykonuj na prywatnym materiale, żeby nie zmieniać gotowych ocen.
3. Na właściwej fotografii z uciętą tablicą kliknij PPM etykiety tablicy 4. W `Geometria → Punkt lokalizacji` zachowaj istniejący powód i wskaż widoczny fragment. Sprawdź ten sam numer/ID tablicy, etykietę przy punkcie, jego przesuwanie oraz Ctrl+Z/Ctrl+Y. Pierwszy rzeczywisty zapis v2 zachowa kopię poprzedniego pliku obok referencji.
4. PPM na polu numeru lub etykiecie → `Numer → Wpisz fragment numeru`. Sprawdź `GWE`, Enter/Ctrl+S i etykietę „Fragment: GWE”. Nie dopisuj brakujących znaków.
5. Na prywatnej kopii sprawdź obszar wokół widocznego fragmentu, przesuwanie, konwersję z/do dokładnego quada, nieczytelność oraz Esc. Przybliżenie nie może pojawić się jako dokładny obrys.
6. Powiększ i przesuń obraz, zmień rozmiar okna, sprawdź punkt przy krawędzi. PPM na marginesie nie może utworzyć nowej lokalizacji. Wygląd i wygodę menu potwierdza operator.
7. Zamknij i ponownie otwórz ten sam materiał. Sprawdź zapisane decyzje, bieżącą fotografię, historię oraz 40/40 po zakończeniu edycji. Nie ma dodatkowego zatwierdzenia ani formularza.

## 7. Poza zakresem

Nie wdrożono nowych metryk ani częściowego OCR, E2E, mapowania fotografii na CameraX, homografii, propagacji GT, treningu, inferencji, F5B ani zmian eksperymentalnych TP/FP/FN/IoU/NMCE/CER. Nie zmieniano XML/GT Pack Z2 ani historycznych eksportów. Stare niezwiązane niepowodzenia regresji nie zostały naprawiane w tej poprawce. Ostateczny odbiór operatora pozostaje **NOT_VERIFIED**.
