# Błędy wykonania MT i ramka ocenianej detekcji

## Baza i zakres

HEAD przed zmianą: `0382817f0214cecbad4c67ef9a6f39d29610f887`, gałąź `main`, czyste drzewo.
Kontrakt: `handoff_desktop_execution_error_detection_overlay_final_hardening_v1.md`.
Zmiana przygotowuje desktop do osobnego audytu Android ↔ desktop i testu end-to-end.

Zmienione pliki:

- `ranking/mobile_mt_invocations.py`: stan błędu grupy, metryki i czysta funkcja mapowania boxa.
- `ranking/mobile_human_review.py`: ukończenie review bez decyzji MT dla błędnych wywołań.
- `gui/z4_mobile_sample_review.py`: diagnostyka błędu, ramka, wybór wejścia i ochrona zaślepienia.
- `gui/app.py`: etykieta Integracje → „Analiza i import raportów mobilnych”.
- `tests/test_mobile_mt_final_hardening.py`: błędy, mapowanie, eksport, ranking i regresja MZ/ALPR.
- `tests/test_mobile_human_review.py`: opcjonalne osobne obrazy wejścia w syntetycznych paczkach.
- `tests/gui_mobile_sample_review_probe.py`: ramki, skalowanie, cropy, błędy i ukończenie review.
- Dokumentacja: niniejszy raport, aktualizacja raportu wcześniejszego oraz kopia handoffu.

## Błąd wykonania a jakość MT

Android ustawia `NO_DETECTION` przed wejściem do backendu. Niepusty, przycięty
`execution_error` z dowolnego dziecka ustawia `MtInvocationGroup.execution_failed=True`.
`execution_errors` zachowuje wszystkie różne teksty w kolejności wystąpienia, bez klasyfikowania
wyjątków po treści. Brak pola lub sam biały tekst oznacza `False` i pustą krotkę.

Pierwszeństwo wyniku: `cancelled` → `not_executed` → `execution_error` → ocena jakości.
Nowy `mt_execution_error_invocations` liczy wyłącznie wykonane, nieanulowane grupy z błędem,
niezależnie od decyzji operatora i dostępności obrazu. Nie jest liczbą dzieci.

Mianownik `evaluable_mt_invocations` wymaga: executed, brak cancellation, brak execution_failed,
`evaluable=true`, dostępnego dowodu całego wejścia oraz `visible_plate_count=one`.
Błędna grupa nie zwiększa success, miss, invalid quad, false detections, multiple ani uncertain.
Jej wynik to `execution_error`, `included=false`; dzieci pozostają dostępne diagnostycznie.
Anulowana grupa nie zwiększa licznika błędów, nawet gdy tekst błędu jest obecny.

Failed invocation nie wymaga decyzji `visible_plate_count` ani `is_plate` do ukończenia review.
Dotychczasowy obowiązek GT lub pominięcia subjectu pozostaje; metryki MZ/ALPR nie są redefiniowane.
UI pokazuje „błąd wykonania”, skrót błędu oraz zablokowane pole „Nie wymaga oceny MT”.
Pełne teksty są w „Sesja i modele” oraz wynikach diagnostycznych eksportu.
Błąd pochodzi z archiwum, nie jest zapisywany jako decyzja operatora.

`summary.csv` oraz `review.json/derived_metrics/summary` zawierają nowy licznik.
Istniejąca publikacja całego podsumowania przekazuje go do quality dopiero po `COMPLETED`.
Latency, memory, obliczenia MZ, CER i ALPR korzystają z dotychczasowej logiki.

## Ramka na wejściu MT

`detection_box_on_mt_input(row)` działa bez Tk. Dla każdej współrzędnej:

```text
x_input = (x_source - roi_left) * input_scale + input_pad_x
y_input = (y_source - roi_top)  * input_scale + input_pad_y
```

Wynik jest przycinany do `[0, input_width] × [0, input_height]`.
Brak pól, wartości nieliczbowe/nieskończone, niedodatnia skala lub rozmiary oraz pusty/odwrócony
box dają `None`. Nie odtwarzamy geometrii legacy na podstawie proporcji cropa.

UI preferuje dostępne `mt_input_evidence_entry` bieżącego dziecka, potem inne dostępne
wejście tej samej grupy. Crop nie zastępuje wejścia MT. Ramka pojawia się wyłącznie na
jawnie zapisanym wejściu MT i dla `VALID_QUAD` lub `DETECTION_INVALID_QUAD`.
Starszy dowód wejścia pozostaje do inspekcji, z komunikatem o braku geometrii.

- 0 detekcji / `NO_DETECTION`: całe wejście, bez ramki.
- 1 detekcja: „Detekcja 1 / 1”.
- N detekcji: tylko aktualnie wybrane dziecko, np. „Detekcja 2 / 3”.
- Invalid quad: ramka bounding box i dopisek „błędna geometria”.
- Brak geometrii: komunikat „Brak geometrii detekcji w tej sesji.”
- Crop MZ: ramka wyłączona.

Ramka ma jasny cyjanowy obrys i ciemną otoczkę, a etykieta ciemne tło.
Do rysowania używamy końcowych rozmiarów bitmapy i rzeczywistego offsetu centrowania Canvas,
uwzględniając wcześniejsze pomniejszenie do 1600×1000 oraz zaokrąglenia rozmiarów PhotoImage.
Rozmiar oryginalnego obrazu musi odpowiadać deklarowanemu wejściu MT; niezgodność daje
komunikat zamiast ramki. Resize i zmiana rekordu przebudowują oznaczenie.

Geometria może być widoczna przed GT. Predykcja, konsensus i porównanie pozostają ukryte.
Status MZ jest również ukryty przed GT, aby „Brak znaków” nie ujawniał wyniku no-read.
Szkic GT i jawne zatwierdzenie nadal działają jak wcześniej.

## Weryfikacja i ograniczenia

```text
python -m pytest tests/test_mobile_mt_final_hardening.py tests/test_mobile_mt_blind_review.py tests/test_mobile_human_review.py tests/test_mobile_report_full_rows.py -q --tb=short -p no:cacheprovider --basetemp output/pytest_mt_final_hardening
python tests/gui_mobile_sample_review_probe.py
```

Testy automatyczne: 107 przeszło. Obejmują E1–E4, G1–G5, braki każdego wymaganego pola,
wartości niefinitywne, precedence, błędy różnych dzieci, ukończenie review, nowy licznik w eksporcie
i rankingu, niezmienność SHA oraz regresję MZ/CER/ALPR.

Natywny test Tkinter sprawdza współrzędne i tagi Canvas, przełączenie drugiej/trzeciej detekcji,
preferencję wejścia dziecka i fallback, wcześniejsze thumbnail, resize, crop i NO_DETECTION,
pojedynczą detekcję invalid quad, brak geometrii, błędy wykonania bez wymaganych decyzji,
zaślepienie, autosave, ukończenie, eksport, reopen i stary sidecar.
Wyniki i zrzuty są w osobnym podkatalogu `output/mobile_sample_review_audit/run-*` każdego uruchomienia.
Końcowy przebieg `run-1788862333046487500`: wszystkie scenariusze zaliczone, `errors: []`.

W katalogu `sesje_testowe` znaleziono dziewięć starszych paczek z 25.08.2026; żadna nie ma
`samples/attempts.csv`. Brak dostępnej tam paczki z kontraktem Androida `355ee2d`.
Nowe pola sprawdzono na syntetycznych archiwach odpowiadających kontraktowi.
Oryginalne archiwa, Android, format samples v2, parser ZIP i tożsamość subjectów nie są zmieniane.
Pilotaż terenowy nie jest częścią tego zadania. SHA kandydata jest podane w odpowiedzi końcowej.
