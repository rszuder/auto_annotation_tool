# Z4 A1 — referencja GT oryginalnych fotografii

Data raportu: 11.11.2026. Repozytorium: `C:\Users\48572\Desktop\dyplom\start4`.

**Stan: implementacja A1 gotowa do odbioru operatora. Testy dedykowane: 25/25 PASS. Odbiór wizualny operatora: NOT_VERIFIED.**

Nie oznaczono produkcyjnych fotografii. Nie utworzono produkcyjnego pliku referencji podczas testów. Nie zakończono oceny 40 fotografii ani całego F5A.

## 1. Zakres i reużycie Canvas

Nowe wejście znajduje się w Z4, w oknie **Raporty z telefonu**, pod przyciskiem **GT fotografii**. Po wyborze materiału otwiera się lista fotografii i duży Canvas. Nie jest potrzebny raport ani sesja Androida.

Widok korzysta z rzeczywistej klasy `CanvasReviewEditor`, z opcjonalnym adapterem `reference_source`. Wspólne pozostają rysowanie czterech narożników, hit-testy, zaznaczanie, przeciąganie narożników, pole numeru inline, autosave tego pola, skróty oraz mechanizmy pan/zoom. Renderer obrazu i transformacja viewportu są współdzielone z `MobileSampleReviewWindow`.

Profil fotografii tworzy własną niewielką kompozycję kontenerów i wykorzystuje wspólny silnik interakcji. Panele mobilnej oceny MT/MZ nie są tworzone dla tego profilu. Nie skopiowano Canvas ani jego algorytmu rysowania do drugiego edytora.

```text
GT fotografii                                      Gotowe: X/40
┌─────────────────────────┬────────────────────────────────────┐
│ Fotografia     Status   │ Status bieżącej fotografii         │
│ 01 …           …        ├────────────────────────────────────┤
│ 02 …           …        │                                    │
│ …                       │              CANVAS                │
│                         │       obraz i oznaczenia GT        │
└─────────────────────────┴────────────────────────────────────┘
Dodaj tablicę (D) | Brak tablic | Więcej | Wstecz | Dalej | Następne niegotowe
Krótka wskazówka skrótów
Zapisano / czytelny błąd zapisu
```

Lista ma pojedyncze wiersze, skrócone nazwy, numer pozycji i status. Szerokość statusu jest obliczana z używanej czcionki. W teście okna 1000×700 Canvas zachował ponad 650 px szerokości i 500 px wysokości. To pomiar układu Tk, nie ocena ergonomii przez operatora.

## 2. Fotografie i niezależność referencji

`Material` w `ranking/photo_reference.py` odczytuje rekursywnie materiał i weryfikuje go względem:

- `sorting_manifest.json`;
- `../03_POKAZ_TV/manifest_blokow.json`.

Wymaganych jest 40 unikalnych SHA, zgodnych między manifestami i rzeczywistymi plikami. Kolejność pochodzi z `presentation_order`. Nazwa katalogu, np. DAY_0, nie tworzy decyzji GT. Jednakowe basenames w różnych katalogach nie łączą ocen. Dodatkowa ścieżka do tego samego SHA jest aliasem, nie nowym zadaniem.

Zachowywane są `image_id=img-sha256-<SHA>`, `source_file_sha256`, `relative_path`, aliasy, liczba bajtów, wymiary, orientacja EXIF i przestrzeń współrzędnych. Obraz jest wyświetlany z uwzględnieniem EXIF; współrzędne referencji odnoszą się do `exif_transposed_source_pixels`. Oryginalne bajty JPEG nie są zmieniane.

Skan pomija symlinki i Windows reparse points, w tym junctions. Zawartość jest haszowana podczas otwierania materiału. Przełączanie nie przelicza ponownie SHA niezmienionych fotografii. Zmiana metadanych pliku powoduje ponowną kontrolę zawartości; brak lub zmiana pliku blokuje zapis. Zmiana manifestu również jest wykrywana.

Adapter nie buduje `MobileReviewSession`, fikcyjnych wywołań MT ani wpisów CameraX. Nie ładuje predykcji do modelu fotografii. Wspólny Canvas otrzymuje wyłącznie ręczne obiekty, z pustą listą rodziców modelowych. Ścieżka stosów MT jest dla tego profilu wyłączona na granicy adaptera.

Referencja zapisuje:

```json
{
  "schema": "alpr.photo_reference.v1",
  "annotation_protocol": "MANUAL_SOURCE_PHOTOGRAPH_NO_PREDICTIONS_V1",
  "predictions_exposed": false,
  "dataset_independence": {
    "status": "INCOMPLETE",
    "ok": false
  }
}
```

`dataset_independence` jest zachowywane z manifestu, wraz z jego rzeczywistymi dodatkowymi polami. Walidacja nie pozwala wczytać referencji deklarującej inną niezależność zbioru niż potwierdzona w źródle. Brak predykcji w tym trybie opisuje sposób anotacji; nie potwierdza niezależności zbioru od treningu, walidacji i kalibracji.

## 3. Typowa praca operatora

### Obraz z tablicami

1. Wybrać fotografię.
2. Nacisnąć **D** lub **Dodaj tablicę** i wskazać cztery narożniki.
3. W automatycznie otwartym polu przy obrysie wpisać numer.
4. Nacisnąć Enter albo przejść do kolejnej fotografii. Pole zapisuje się także przez autosave.

Następną tablicę dodaje się ponownie przez D, po zakończeniu wpisywania numeru. Narożniki można przeciągać; kliknięcie numeru pozwala go zmienić. R usuwa wybraną tablicę, a Ctrl+Z/Ctrl+Y cofają i ponawiają zapisane zmiany. F dopasowuje cały obraz, A korzysta z istniejącego dopasowania do kolejnych tablic. Rolka przybliża, przeciągnięcie tła przesuwa obraz.

Ctrl+S zapisuje edytowany numer. Spacja nie jest dodatkowym obowiązkowym zatwierdzeniem GT w tym profilu. Standardowy mobilny Z4 zachowuje dotychczasowe znaczenie swoich skrótów.

### Obraz bez tablic

Jedno kliknięcie **Brak tablic** zapisuje `NO_PLATES` i kończy zadanie dla obrazu negatywnego. Nie ma dodatkowego checkboxa. Decyzję można cofnąć przez Ctrl+Z.

Brak obrysów bez świadomej decyzji jest `UNRESOLVED`. Usunięcie ostatniej ręcznej tablicy wraca do `UNRESOLVED`, nie do `NO_PLATES`.

### N/A tekstu i geometrii

- **Numer nieczytelny** jest dostępny kontekstowo dla tablicy, także pod PPM w polu numeru. Zapisuje pusty tekst i jawny powód `Numer nieczytelny na fotografii`. Puste pole bez tej decyzji pozostaje nieuzupełnione.
- **Dodaj tablicę bez możliwego obrysu** znajduje się w menu Więcej i menu kontekstowym. Operator wybiera powód, np. zasłonięte narożniki lub ucięcie krawędzią fotografii. Powstaje rzeczywisty obiekt GT z `quad=null`, bez sztucznych rogów.
- Obiekt bez obrysu ma niewielką etykietę na Canvas, umożliwiającą wpisanie numeru. Etykieta nie jest zapisywana jako geometria tablicy.
- Istniejący obrys można zastąpić jawnym N/A, zachowując ID obiektu. Narysowanie obrysu dla wybranej tablicy bez geometrii również zachowuje jej ID.

## 4. Kompletność, zapis i wznowienie

Kompletność wynika ze stanu danych:

- `NO_PLATES` przy pustym wykazie obiektów jest gotową sceną negatywną;
- `PRESENT` wymaga obiektów o stabilnych ID oraz geometrii lub przyczyny N/A, a także tekstu lub przyczyny N/A;
- niedokończony obiekt nie jest gotowy;
- trwający szkic, niezapisany tekst, przeciąganie lub błąd zapisu oznaczają bieżącą pracę w UI.

Interfejs używa statusów **Do oznaczenia**, **W trakcie**, **Gotowe**, **Wymaga uzupełnienia**. Na zwartej liście ostatni status jest skrócony do **Uzupełnij**. Licznik uwzględnia aktualnie niedokończoną edycję.

Jedynym aktywnym magazynem referencji tego trybu jest wersjonowany dokument JSON. Zawiera metadane 40 fotografii, referencję do manifestów, rewizję, ostatnio wybrany obraz, obiekty i historie. Każda zmiana zapisuje wersję stanu fotografii; undo/redo zmienia pozycję w historii. Wersje z poprzedniej gałęzi nie są usuwane z wykazu wersji.

Zapis wykorzystuje istniejący atomowy zapis JSON z `gt_pack.py`. Blokada systemowa jest zwalniana przez system również po zakończeniu procesu; mały plik blokady może pozostać. Kontrola SHA dokumentu zapobiega nadpisaniu zmian z drugiego okna. Błąd zapisu nie zmienia zatwierdzonego stanu w pamięci.

Niezapisany tekst, szkic lub korekta pozostają w oknie. Zmiana fotografii jest blokowana, a przy błędzie pojawia się **Ponów zapis**. Przy zamykaniu po błędzie operator może jawnie zrezygnować z niezapisanych zmian; wcześniejsze zapisane oceny pozostają zachowane. Nie ma modalnego potwierdzenia po zwykłej anotacji.

Ponowne otwarcie odtwarza postęp, historię i ostatnią fotografię. **Następne niegotowe** znajduje kolejne wymagające pracy zdjęcie, z przejściem na początek listy po dojściu do końca.

## 5. Dokładne miejsce zapisu F5A

```text
C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\01_materialy\04_GT_FOTOGRAFII_Z4\reference_v1.json
```

Plik powstanie po pierwszym zapisie użytkownika, także zapisie miejsca nawigacji. Podczas testów używano wyłącznie prywatnych lokalizacji wyjściowych; powyższy plik produkcyjny nie został utworzony.

Dane nie trafiają do `human_reviews` żadnego raportu Androida. Nie powstaje run Z2, nowy raport mobilny ani kopia zestawu JPEG. Informacje o lokalizacji zapisu są dostępne w menu **Więcej → Informacje o zapisie**.

Historyczny `current_work.alprgt` i jego decyzja NO_PLATES pozostały bez zmian. Nie wykonano migracji ani automatycznego uznania dawnej decyzji za niezależną. Najmniejszą bezpieczną ścieżką jest ponowne świadome potwierdzenie tej jednej fotografii w nowym trybie. Historyczne źródło decyzji nadal istnieje.

## 6. Zmienione pliki i punkty integracji

| Plik | Zakres |
|---|---|
| `ranking/photo_reference.py` — nowy | `Material`: skan, manifesty, SHA, źródła. `PhotoReference`: odrębna referencja fotografii, walidacja, wersje, zapis, undo/redo, wznowienie. |
| `gui/z4_photo_reference.py` — nowy | `PhotoReferenceWindow`: dwukolumnowy host. `PhotographCanvasSource`: adapter widoku i zapisu. `open_photo_reference()`: otwieranie materiału. |
| `gui/mobile_canvas_editor.py` | Opcjonalny `reference_source`, punkty podłączenia źródła/zapisu i prezentacji. Wspólne gesty i renderer pozostają w tej samej klasie. Zachowanie szkicu po błędzie zapisu. |
| `gui/mobile_canvas_stacks.py` | Granica wyłączająca odczyt stosów modelowych dla fotografii oraz przekierowanie zapisu referencji do adaptera. |
| `gui/mobile_canvas_selection.py` | Kontekst zaznaczenia korzysta z rewizji referencji fotografii, bez wymagania mobilnego sidecara. |
| `ranking/mobile_manual_frame_guard.py` | Istniejąca kontrola kolizji otrzymuje ręczne obrysy fotografii bez odczytu kandydatów MT. |
| `gui/z4_mobile_report_browser.py` | Przycisk GT fotografii, metoda otwierania oraz kontrolowane zamykanie otwartych okien referencji. |
| `tests/test_z4_photo_reference.py` — nowy | Testy źródeł, kompletności, zapisu, konfliktów i rzeczywistych zdarzeń Tk. |
| `docs/Z4_A1_GT_FOTOGRAFII_ODBIOR_2026-11-11.md` — nowy | Ten raport. |

Ścieżki kodu w tabeli są względne względem `auto_annotation_tool`, poza testem i dokumentem. Przyrost w pięciu istniejących plikach był kontrolowany względem kopii stanu sprzed A1, a nie względem czystego HEAD. Wcześniejsze lokalne poprawki zachowano.

## 7. Wyniki testów

| Zestaw | PASS | FAIL | SKIP |
|---|---:|---:|---:|
| Dedykowane A1 | 25 | 0 | 0 |
| Bloki obserwacji Z4 | 31 | 0 | 0 |
| Pełne sceny Z4 — natywny Tk | 13 | 0 | 0 |
| Trwałość ocen, Canvas, pełne sceny, GT Pack | 129 | 3 | 0 |
| Istniejący nawigator Canvas | 24 | 7 | 1 |
| Importer folderów i preferencje UX02 | 91 | 0 | 0 |
| Nazwy/notatki i przeglądarka raportów | 22 | 0 | 1 |
| **Łącznie** | **335** | **10** | **2** |

Wszystkie 10 niepowodzeń odtworzono na odizolowanej kopii kodu sprzed A1, zawierającej wcześniejsze lokalne modyfikacje. Nie zmieniano historycznych asercji, aby uzyskać zielony wynik. Stan rozszerzonych regresji pozostaje PARTIAL.

Pominięte przypadki:

- `test_U04_single_selected_badge`: fixture zgłosił `Tk display required`;
- `test_real_archives_and_83_record_private_copy`: nie przekazano osobnego fixture do tego istniejącego testu. Niezmienność produkcyjnego magazynu sprawdzono niezależnie przez SHA.

Dodatkowo dwa historyczne przypadki nawigatora zależne od dawnych materiałów/protokołu odbioru nie były wybrane do uruchomienia.

Dedykowane testy obejmują 40 obrazów z podkatalogów, jednakowe nazwy, identyfikację SHA, zero/nieprawidłową populację, negatyw, 1/2/4 tablice, nieczytelny tekst, geometrię N/A, niepełny obiekt, korekty, usuwanie, undo/redo, autosave, Ctrl+S, wznowienie ostatniego obrazu, następne niegotowe, pan/zoom, błędy zapisu i ich ponowienie, zmieniony/brakujący plik, konflikt równoległego zapisu, alias SHA, pomijanie junctions i niezmienność źródeł. Wykonano też odczyt rzeczywistego materiału F5A z prywatną lokalizacją referencji, bez zapisania produkcyjnych ocen.

Logi, JUnit XML, kopia stanu bazowego i inwentarz chronionych plików:

```text
C:\Users\48572\AppData\Local\Temp\z4_photo_gt_a1_ut9d9g6z
```

Główne dowody: `a1_final.xml`, `blocks.xml`, `scene_gui.xml`, `persistence.xml`, `navigator.xml`, `import.xml`, `browser.xml`, `baseline_persistence.xml`, `baseline_navigator.xml`.

## 8. Ochrona istniejących danych

Kontrola 138 chronionych plików nie wykazała zmian SHA-256, rozmiaru ani czasu modyfikacji. Zakres obejmował oryginalny K02, magazyn raportów, kontrolowane oceny operatora, preferencje oraz fotografie, manifesty i istniejący GT Pack materiału/pokazu F5A.

Nie zmieniano Z2, Androida, APK, kampanii ani algorytmów TP/FP/FN, IoU, NMCE i CER. Nie uruchamiano modeli, nie importowano raportów i nie wykonywano commit/push/reset/checkout/clean. Nie usuwano danych historycznych.

## 9. Odbiór w działającej aplikacji

1. Uruchomić ponownie ALPR Desktop, aby wczytać zmieniony kod.
2. W Z4 otworzyć **Raporty z telefonu → GT fotografii**.
3. Wskazać `C:\Users\48572\Desktop\ALPR_EKSPERYMENTY\F5A-ROI-A12-01\01_materialy\02_MATERIAL_ZATWIERDZONY`.
4. Sprawdzić 40 pojedynczych pozycji, duży obraz i jeden licznik postępu. Kolejność odpowiada pokazowi TV; nie jest to kolejność dawnych katalogów Z2.
5. Dla rzeczywistej sceny negatywnej wybrać Brak tablic. Powinna wystarczyć jedna decyzja; Ctrl+Z powinno ją cofnąć.
6. Na zdjęciu z tablicą: D, cztery narożniki, numer przy obrysie, Enter lub przejście dalej. Sprawdzić korektę narożnika i numeru.
7. Sprawdzić zdjęcie wielotablicowe, Numer nieczytelny i obiekt bez geometrii. Oceny muszą pozostać niezależne dla poszczególnych tablic.
8. Sprawdzić zoom, pan, rozmiar 1000×700, czytelność listy oraz brak zbędnych paneli i technicznych identyfikatorów.
9. Zamknąć okno i ponownie otworzyć ten sam materiał. Zweryfikować postęp, ostatnią fotografię oraz Następne niegotowe.

Na produkcyjnych fotografiach należy zapisywać wyłącznie rzeczywiste decyzje operatora. Dowolne próbne obrysy, testowe numery i symulacje błędów należą do prywatnego materiału testowego.

Automatyczne testy zdarzeń Tk nie zastępują tego odbioru. Próba podglądu przez dostępne narzędzia computer-use zakończyła się błędem inicjalizacji `failed to write kernel assets: System nie może odnaleźć określonej ścieżki. (os error 3)`. Nie uzyskano narzędziowego oglądu okna i nie deklaruje się akceptacji wizualnej za operatora.

## 10. Zakres pozostawiony na później

Nie wdrożono mapowania fotografii na 386 zdarzeń, homografii, transportu geometrii do CameraX, propagacji GT do sesji, agregacji E2E, nowych metryk, F5B ani final_test F6. Niezależność materiału badawczego nadal ma status INCOMPLETE.

A1 udostępnia warunki do ręcznego utworzenia referencji fotografii. Liczba rzeczywiście oznaczonych fotografii będzie wynikać z pracy operatora, nie z samego wdrożenia narzędzia.
