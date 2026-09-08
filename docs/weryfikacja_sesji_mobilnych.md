# Weryfikacja sesji mobilnych — 2026-09-08

Aktualizacja jednostki MT i zaślepienia: [raport hardeningu](mt_invocation_blind_review_hardening.md).
Nowe review domyślnie używa `blinded_gt_v1`: autosave zachowuje szkic, a pierwsze odsłonięcie predykcji
wymaga jawnego „Zapisz GT”. MT jest obecnie liczone per wywołanie backendu, nie per rekord detekcji.
Poniższy opis dokumentuje także pierwotne wdrożenie; nowszy raport doprecyzowuje te dwa obszary.

Implementacja handoffu `handoff_desktop_mobile_session_human_review_v1.md`, na bazie `1248b4b`.
Kontrakt wejściowy porównano z lokalnym kodem Androida: `ResearchSessionStore.ATTEMPT_COLUMNS`,
`AcquisitionAttemptRecord`, `ResearchSampleIdentity` oraz `ResearchArchive` w projekcie `ALPR_v1`.

## Obsługa

1. Otwórz **Raporty z telefonu**, zaimportuj `.alprsession` lub ZIP i wybierz sesję.
2. Wybierz **Weryfikacja próbek**.
3. Na liście tablic wybierz subject. Wpisz GT raz; zostanie zastosowane do jego cropów.
   Dostępne są też „Zgodne z predykcją” i „Nie do oceny”.
4. Lista pod obrazem przełącza próby i cropy. Lista przy obrazie pozwala przełączyć dowód próby i powiązany crop.
5. Oceń widoczność tablicy lub zaznacz, że detekcja nie przedstawia tablicy. Nie trzeba ręcznie liczyć znaków.
6. **Statystyki** zawierają osobno MZ, lokalizację MT i skuteczność ALPR dla tablic.
   **Sesja i modele** pokazuje metadane eksperymentu, urządzenie, konfigurację, pochodzenie modeli oraz lokalizację zapisu.
7. **Zakończ weryfikację** sprawdza wymagane decyzje. **Eksport wyników** zapisuje JSON i trzy tabele CSV.

GT i notatka zapisują się po 750 ms przerwy w pisaniu, a przyciski zapisują decyzję od razu.
Kliknięcie oceny próby przed upływem tych 750 ms również zachowuje wpisane GT.
Zamknięcie panelu albo nadrzędnego okna raportów czeka na zapis. Błąd zapisu pozostawia okno otwarte.
Usunięcie GT przywraca stan wymagający decyzji; jawne zapisanie GT pozwala ponownie oceniać pominiętą tablicę.

## 1. Zmienione pliki

- `ranking/mobile_package_experiments.py`: rozszerzenie readera, odczyt dowodów, obsługa jakości z review i korekta interpretacji CER.
- `ranking/mobile_human_review.py`: model, indeks pełnych danych, decyzje, zapis, porównanie tekstów, statystyki i eksport.
- `ranking/__init__.py`: publiczne eksporty nowych typów i funkcji.
- `gui/z4_mobile_sample_review.py`: panel weryfikacji, kolejka pracy poza Tk, podgląd obrazów i autosave.
- `gui/z4_mobile_report_browser.py`: wejście do panelu, prezentacja zweryfikowanej jakości i zamykanie po zapisie.
- `tests/test_mobile_human_review.py`: testy kontraktu, metryk, zapisu i rankingu.
- `tests/gui_mobile_sample_review_probe.py`: natywna próba UI z ograniczeniem zapisów do `output`.
- Dokumentacja: niniejszy opis i kopia handoffu w `docs`.

## 2. MobileReportBundle i reader

Rozszerzono istniejący reader ZIP, bez budowania drugiego parsera archiwum.
Nowe pola: `sample_schema`, `collection_session`, `attempt_rows`, `attempt_total`, `attempts_available`.
Czytane są addytywnie `samples/schema.json`, `samples/attempts.csv` i `session.json`.
Oryginalne `samples/annotations.jsonl` jest odczytywane z zachowaniem zagnieżdżonych metadanych.

Publiczne funkcje: `iter_full_attempt_rows`, `iter_full_sample_annotations`, `read_mobile_sample_image`.
Istniejące `iter_full_sample_rows` nadal dostarcza pełny indeks. Ograniczenie 1000 wierszy w podglądzie
nie ogranicza obliczeń review. Indeks cropów jest łączony z adnotacjami po identyfikatorze próbki,
a z próbami po `attempt_id`. Sprzeczne tożsamości i zduplikowane klucze są odrzucane.

Obraz jest pobierany pojedynczo z ZIP. Limity domyślne: 20 MiB na wpis, 12 000 px na bok,
40 mln pikseli po dekodowaniu. Pozostają wspólne kontrole ścieżek, duplikatów i rozmiaru archiwum.
Odczyt, dekodowanie, obliczenia i zapisy odbywają się poza wątkiem Tk; `PhotoImage` powstaje w wątku UI.

## 3. MobileHumanReview

Schemat `alpr.mobile_human_review.v1` przechowuje identyfikator review, SHA-256 i ścieżkę źródła,
sesję, daty, opcjonalny identyfikator osoby weryfikującej, status, rewizję, politykę normalizacji,
`subjects`, `attempt_annotations`, `sample_annotations` oraz provenance modeli i konfiguracji.
Operator zbierający sesję pozostaje w jej oryginalnych metadanych; reviewer jest osobnym polem.

Stany: `NOT_STARTED`, `IN_PROGRESS`, `COMPLETED`. Brak GT lub wymaganej oceny próby blokuje ukończenie.
Można jawnie pominąć tablicę lub próbę. Próby anulowane nie wymagają decyzji.
Bez obrazu dowodowego próba wymaga jawnego pominięcia lub oznaczenia niejednoznaczności.
Lista pokazuje również pozostałe decyzje dla tablicy, której GT zostało już zapisane.

## 4. Sidecar i ochrona źródła

Domyślna lokalizacja względem katalogu roboczego aplikacji:

```text
Workspace/7_rankings/mobile_packages/human_reviews/<SHA-256>.review.json
```

Każda zmiana zwiększa rewizję. Zapis: plik tymczasowy w tym samym katalogu → flush/fsync → replace.
Nieudany replace zachowuje poprzednią rewizję na dysku i w pamięci.
Sprawdzana jest także rewizja już zapisana przez inne okno, aby nie nadpisać jej starszym stanem.

SHA źródła jest weryfikowane przy otwarciu, przy wykryciu zmiany pliku oraz przed eksportem i publikacją jakości.
Sidecar o innym SHA lub identyfikatorze sesji nie jest automatycznie podpinany.
Nie przepakowuje się `.alprsession`, nie dopisuje GT do ZIP i nie podmienia oryginalnych adnotacji.

## 5. Porównanie tekstów

Normalizacja `uppercase_alphanumeric.v1`: wielkie litery, usunięcie spacji/separatorów,
bez korekcji O/0 i I/1. Odpowiada podstawowej normalizacji OCR desktopu.
Levenshtein zwraca pełne dopasowanie, liczbę poprawnych, błędnie rozpoznanych, brakujących i nadmiarowych znaków.
Remisy rozstrzyga deterministycznie: najmniejsza odległość, najwięcej trafień, następnie ustalona kolejność operacji.

CER to suma błędnie rozpoznanych, brakujących i nadmiarowych znaków podzielona przez liczbę znaków GT.
Dla pustego GT jest niedostępny. CER sesji jest liczony z sum znaków, nie jako nieważona średnia CER cropów.
CER może przekraczać 1. Poprawiono również ranking i przeglądarkę raportów, aby np. 1,5 oznaczało 150%, a nie 1,5%.

## 6. Grupowanie tablic

Nowe dane używają gotowego `subject_key` z Androida. Crop związany z próbą dziedziczy jej tożsamość;
sprzeczne klucze są błędem. OCR i konsensus nigdy nie są identyfikatorem tablicy.

Legacy: sesja + scena (jeżeli dostępna) + identyfikator entity/track; przy braku tych identyfikatorów — pojedynczy rekord.
Takie grupy mają `legacy_identity` i oznaczenie w UI. Dane legacy nie dają gwarancji tożsamości między resetami sceny,
jeżeli stare archiwum nie zapisało generacji sceny.

## 7. MT miss i pozostałe wyniki MT

MT miss: tablica oznaczona jako widoczna i `mt_status=NO_DETECTION`.
Osobno liczone są poprawne lokalizacje (`VALID_QUAD`) oraz błędna geometria (`DETECTION_INVALID_QUAD`).
„To nie jest tablica” ma pierwszeństwo przed `VALID_QUAD`: jest fałszywą detekcją, a nie sukcesem.
Oznaczenie cropa jako nie-tablicy wpływa też na powiązaną próbę.

Mianownik MT obejmuje oceniane, nieanulowane próby z dowodem i widoczną tablicą, w których MT faktycznie wykonał detekcję.
Niewidoczne, niejednoznaczne, pominięte i anulowane próby są wyłączane. `NOT_RUN` nie jest błędem detekcji.
Fałszywe detekcje raportowane są osobno. Miara nie jest mAP.

## 8. Statystyki, ranking i eksport

- MZ per crop: poprawny odczyt, niepoprawny odczyt, brak odczytu, dopasowanie znaków i CER.
  Brak uruchomienia MZ i anulowanie nie są zaliczane jako brak odczytu.
- Tablica: GT, liczby prób/cropów, oceniane odczyty, MT miss, postęp decyzji i sukces systemu.
- ALPR: co najmniej jeden poprawny świeży odczyt **lub** poprawny konsensus dla tablicy.
  Konsensus nie zastępuje świeżej predykcji w metrykach MZ. Jego naprawienie wyniku jest osobnym polem.
- Macierz błędów: pary GT → rozpoznany znak; braki i nadmiary pozostają osobnymi licznikami.
- Jeśli dane to umożliwiają: liczba prób do pierwszego trafienia, źródło obrazu i zoom,
  trafienie przed AZ / tylko po AZ, mediana i P90 czasu.

Czas jest odstępem od startu pierwszej ocenianej próby subjecta do startu próby z poprawnym wynikiem,
przy wspólnym zegarze. `time_basis` zapisuje tę podstawę. Nie jest to wyliczony czas zakończenia inferencji.
Brakujących znaczników czasu, źródła obrazu czy zoomu nie uzupełnia się domysłami.

Eksport: `review.json` (decyzje i odtwarzalne metryki), `summary.csv`, `subjects.csv`, `character_confusion.csv`.
Eksport zachowuje SHA, rewizję i dokładne pochodzenie modeli/wariantów/runtime/precision.

Ranking otrzymuje `quality_source=human_review` dopiero po `COMPLETED`.
Edycja ukończonej weryfikacji przywraca bazową jakość zaimportowanego raportu do czasu ponownego ukończenia.
Sprawdzenie rewizji sidecara zapobiega użyciu nieaktualnej oceny po przerwaniu aktualizacji rankingu.
Surowe latency/memory pozostają niezmienione. Tożsamość archiwum, a nie sam `report_id`, rozróżnia wyniki.

## 9. Zgodność wsteczna

Stara `.alprsession` bez `attempts.csv` jest przyjmowana. UI wyświetla komunikat o ograniczonej ocenie MT.
Możliwa jest ocena cropów i skuteczności odczytu dla tablic; pełne miary MT pozostają niedostępne.
Import samych raportów JSON nadal działa w istniejącej przeglądarce. Weryfikacja obrazów wymaga źródłowego ZIP.
`PARTIAL` / `ERROR` i `collection_complete=false` są widocznie oznaczane jako niekompletna sesja.

## 10. Walidacja

```text
python -m pytest tests/test_mobile_human_review.py tests/test_mobile_report_full_rows.py -q
```

34 testy przeszły. Obejmują D1–D5, dokładne statystyki S1–S4, pełny rejestr ponad limit podglądu,
normalizację, grupowanie, SHA mismatch, niezmienność źródła, awarię replace, konflikt rewizji,
próby anulowane, NOT_RUN, brak dowodu, false detection, GT i postęp, ranking przed/po ukończeniu oraz eksport.

Natywna próba:

```text
python tests/gui_mobile_sample_review_probe.py
```

Używa syntetycznych paczek zgodnych z kolumnami Androida, rzeczywistego Tk i stylów aplikacji.
Sprawdza wejście z przeglądarki, niekompletność sesji, GT i oceny, ukończenie, eksport, ponowne otwarcie,
stary format oraz zachowanie GT przy zamykaniu okna. Zapisy są ograniczone do `output/mobile_sample_review_audit`.
Końcowy wynik próby: `errors: []`; potwierdzone ponowne otwarcie, eksport, niezmieniony SHA źródła
oraz zachowanie szkicu GT przy zamykaniu nadrzędnego okna raportów. Układ sprawdzono w jasnym i ciemnym motywie.
Nie wykonywano zbierania nowej sesji na fizycznym telefonie w ramach tej zmiany.
