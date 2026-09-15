# PZ3 — stabilizacja, 14.09.2026

## Wynik

Domknięto ingest mieszanej puli, odświeżanie tabeli członków, kontrolę ważności audytu i obsługę dużych paczek w tle. Zachowano lokalne zmiany użytkownika oraz istniejący układ w z4_evaluation_tracks_layout.py.

Punktem wyjścia był lokalny kod, który zawierał już część zmian opisanych w handoffie jako niepotwierdzone: decyzje dla zależności, edycję nazw inline, podgląd z zoomem oraz selektor modeli z sortowaniem i szybkim odświeżaniem.

## Zmiany

- CLEAN jest dodawany niezależnie od odrzuconych nowych kandydatów DEPENDENT i UNKNOWN. Dla SUSPECT działają decyzje TAK / NIE / ANULUJ.
- Preflight rozróżnia duplikaty SHA, powtórzenia logicznego źródła i kolizje nazw, także w jednym wyborze. Wykorzystuje wcześniej policzone hashe oraz zbiorczy odczyt tożsamości źródeł.
- Komunikat „Dodano do toru” korzysta z wyniku zapisu, a liczba rekordów jest porównywana z przyrostem członków i zawartością rzeczywistego Treeview.
- Po zapisie otwiera się zakładka „Obrazy toru”. Programowe zaznaczanie toru nie przebudowuje wielokrotnie tej samej tabeli.
- Haszowanie, audyt, kopiowanie i zapis stanu audytu działają w zadaniu w tle; zdarzenia Tk i aktualizacja postępu pozostają w wątku GUI.
- Zmiana pliku po audycie jest wykrywana przez sprawdzenie SHA kopii przed zatwierdzeniem paczki.
- Błąd manifestu po zatwierdzeniu transakcji nie usuwa plików należących już do zapisanych rekordów. GUI odczytuje rzeczywisty stan również po takim błędzie.
- Dodanie paczki i usunięcie członków unieważniają audyt w warstwie usługi.
- Niepełna historia modelu, brak materiału w ancestry albo częściowe pokrycie pHash nie dają wyniku CLEAN. Powtórzenie tego samego datasetu w ancestry nie obniża sztucznie pokrycia.
- Raport może nadać stan CURRENT tylko wtedy, gdy obejmuje aktualnych uczestników i wszystkich zachowanych członków. Akceptowane podejrzane SHA są zapisywane w stanie audytu.
- Zmiana checkpointu, runu lub statusu historii w rejestrze blokuje korzystanie ze starego audytu.
- Cache odrzuca stary pHash po zmianie pliku oraz zapamiętuje fingerprinty zweryfikowanych kopii wewnątrz toru.
- Dialog nazw zachowuje obsługę Enter / Esc / strzałek, sortowanie i centralny parser. Zapis zatwierdza aktywną edycję. Dodano przewijanie poziome tabeli i anulowanie timerów podglądu przy zamykaniu.
- Potwierdzono checkboxy, sortowanie skali n/s/m/l/x, polskie etykiety historii, aktualizację statusu zaznaczenia oraz odświeżanie modeli bez bootstrapu Workspace.
- Ponowny audyt jest dostępny również dla VERIFIED, aby można było ponownie sprawdzić pulę przed pieczętowaniem.

## Ważne dla istniejących torów

Fingerprint uczestników obejmuje teraz również status historii treningu. Wcześniejsze audyty wymagają ponowienia przez „Audytuj pulę”; przycisk działa także dla VERIFIED. Same obrazy i GT pozostają w torze.

## Testy

Stan bazowy: 526 testów OK.

Końcowy stan: **562 testów OK**, w tym 36 nowych testów regresji. Wykonano także osobno:

| Wzorzec | Liczba | Wynik |
| --- | ---: | --- |
| test_pz3_*.py | 47 | OK |
| test_evaluation_*.py | 46 | OK |
| test_participant_*.py | 26 | OK |
| test_source_filename*.py | 20 | OK |
| test_*.py | 562 | OK |

git diff --check: OK.

Testy integracyjne korzystają z prawdziwego SQLite, rzeczywistych plików obrazu i widgetów Tk. Sprawdzają m.in. mieszaną pulę, wszystkie trzy decyzje dla SUSPECT, ponowne dodawanie, zmianę nazwy przed audytem, błąd zapisu manifestu, aktywację kontekstu Z2, weryfikację kontrolnego XML GT i blokadę/powtórzenie audytu przed SEAL.

Wykonano także smoke okien i kontrolę wizualną zrzutów panelu, przeglądu nazw oraz selektora. Smoke GT używa kontrolowanego XML; nie jest pomiarem jakości ręcznej anotacji ani preanotacji rzeczywistym modelem.

Log całego suite zawiera także komunikaty Tk z wcześniejszych testów (mock koloru scrollbara i timer lambda). Te same komunikaty występowały w logu bazowym przed zmianami. Zestawy nowych testów PZ3 przechodzą bez tych komunikatów.

Logi: output/pz3_verify_1.log … output/pz3_verify_5.log.
Zrzuty: output/pz3_smoke_panel.png, output/pz3_smoke_names.png, output/pz3_smoke_models.png.

## Benchmark 1000 rzeczywistych zdjęć

Dane wejściowe: Workspace/1_raw_images/sample_1000, 1000 plików, 233 416 557 bajtów.
Scenariusz kontrolowany: osobny tymczasowy Workspace, dwóch uczestników testowych, 1000 rzeczywistych obrazów referencyjnych train/val. Metadane uczestników są fixture'em do pomiaru wydajności, a wyniki nie stanowią oceny rzeczywistych modeli użytkownika. Oryginalne zdjęcia i produkcyjny rejestr nie były zmieniane.

| Pomiar | Pierwsze dodanie | Ponowne dodanie tej samej puli |
| --- | ---: | ---: |
| Cała operacja | 20,19 s | 4,09 s |
| Nowe rekordy | 769 | 0 |
| Wiersze „Obrazy toru” po operacji | 769 | 769 |
| Audyt | 5,42 s | 2,71 s |
| SHA + obsługa cache w audycie/preflight | 1,59 s | 0,97 s |
| pHash + obsługa cache | 4,33 s | 1,37 s |
| Zbiorczy ingest wraz z kontrolą kopii | 10,99 s | — |
| Największa przerwa między zdarzeniami kontrolnymi Tk | 0,245 s | 0,246 s |

Czasy składowe są zagnieżdżone i nie należy ich sumować.

Podział 1000 wejściowych plików: 20 duplikatów, 769 CLEAN, 98 DEPENDENT, 113 SUSPECT, 0 UNKNOWN. Podejrzane pominięto. Pierwsza operacja zapisała 769 rekordów i dokładnie tyle wierszy pojawiło się w tabeli. UNKNOWN jest sprawdzany osobnym testem na uszkodzonym obrazie i niepełnej historii.

W drugim audycie: 980 trafień SHA, 1978 trafień pHash i **0 nowych obliczeń SHA/pHash**. W pierwszej operacji lineage odczytano jednym wywołaniem rekurencyjnego SQL, paczkę zapisano jednym wywołaniem transakcji i raz zapisano manifest.

Pełne metryki: output/pz3_benchmark_report.json.

Odtworzenie:

~~~powershell
python tests/pz3_benchmark.py
python tests/pz3_visual_smoke.py
python -m unittest discover -s tests -p "test_*.py"
git diff --check
~~~


## Doprecyzowanie komunikatów audytu

Usunięto niejasne określenie „Podejrzane obrazy już są w DRAFT”.
Komunikat wskazuje, że audyt objął także obrazy dodane wcześniej, wyjaśnia
podobieństwo do danych treningowych/walidacyjnych uczestników i podaje pliki
do sprawdzenia. Podobieństwo wyglądu nie jest przedstawiane jako dowód
wspólnego pochodzenia.

W audycie i podczas dodawania „Tak” oznacza pozostawienie/dołączenie obrazów
po sprawdzeniu ich pochodzenia. „Nie” dla obrazów już należących do toru
otwiera zakładkę „Obrazy toru” i zaznacza wskazane pozycje bez ich usuwania;
audyt wymaga wtedy ponowienia. Dla nowych kandydatów „Nie” pomija je
i dopuszcza pozostałą pulę, a „Anuluj” przerywa dodawanie.

Dodano trzy testy decyzji i przejścia do właściwych wierszy. Końcowy suite:
562 testy OK. Native smoke komunikatu sprawdził wybór „Nie” w rzeczywistym
oknie systemowym oraz zaznaczenie odpowiedniego obrazu.
Zrzut: output/pz3_audit_message.png.
