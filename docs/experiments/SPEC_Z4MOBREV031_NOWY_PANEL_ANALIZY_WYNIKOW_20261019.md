# SPEC_Z4MOBREV031 — czytelny panel „Analiza wyników”

**Projekt:** ALPR Desktop → Raporty z telefonu → Próbki i weryfikacja → Analiza wyników
**Data:** 19.10.2026
**Status:** SPECYFIKACJA DO IMPLEMENTACJI; **nie jest to wykonany patch**
**Zakres:** wyłącznie warstwa prezentacji i odczytu istniejących wyników naukowych.
**Proponowane ID wdrożenia:** `Z4MOBREV031_SCIENCE_DASHBOARD_TABLE_CARDS_20261019`.

## 1. Cel i problemy obecnego ekranu

Zastąpić obecną, wieloakapitową zawartość „Analiza wyników” panelem, który pozwoli operatorowi w kilka sekund ustalić:

1. **Co zostało zmierzone?** Wyniki i ich jednostki.
2. **Co pozostaje do weryfikacji?** Brakujące decyzje i brakujące GT.
3. **Czego nie wolno wyliczać?** Brak mianownika, brak niezależnego GT, brak udokumentowanego ROI, nieuruchomiony MZ itp.
4. **Na jakiej podstawie otrzymano wynik?** Licznik, mianownik, próba, źródło oraz proweniencja GT.

Obecne okno zawiera te informacje, ale miesza je w długim tekście. Docelowo podstawą jest **kompaktowa tabela metryk i cztery kafle**, a pełne zastrzeżenia znajdują się w rozwijanych szczegółach.

### Nienaruszalne ograniczenia

- Nie zmieniać `.alprsession`, sidecarów, GT, predykcji, modeli, czasów ani danych Androida i TeX.
- Nie zmieniać funkcji liczących miary; UI ma czytać istniejący kanoniczny wynik `make_scientific_summary(...)`, `session.statistics()` oraz statusy formularza `verification_progress(...)`.
- **Brak danych ≠ zero.** `None`, brak mianownika, `NOT_RUN`, `NOT_EVALUABLE`, `PARTIAL` nie mogą być wyświetlone jako `0`, `0/0`, `0%` ani „błąd modelu”.
- **Ukończony formularz ≠ formalnie policzalna nauka.** W szczególności dla scen wielotablicowych obowiązuje zabezpieczenie Z4MOBSAFE030: przypisania operatora są diagnostyką, nie formalnymi `TP/FP/FN`.
- Zostawić dostęp do istniejącego raportu technicznego i pełnych danych źródłowych.
- Tryb asystowany (operator widział predykcje) pozostaje jawnie oznaczony; pomiary z korektą asystowaną nigdy nie są podstawiane pod niezależny GT.

## 2. Docelowy ekran

Proponowana kolejność pionowa — bez długich opisów na pierwszym planie:

```text
PODSUMOWANIE WYNIKÓW SESJI                                      [Tabela techniczna]
Stan: Weryfikacja w toku  •  Tryb GT: asystowany  •  Wyniki: wstępne
Scenariusz / wariant / telefon: [krótko, z istniejących metadanych]

┌─────────────────────┬─────────────────────┬─────────────────────┬─────────────────────┐
│ WYKRYWANIE TABLIC   │ POŁOŻENIE OBRYSU   │ ODCZYT ZNAKÓW      │ CAŁY SYSTEM ALPR   │
│ MT                  │ Pose                │ MZ                  │                     │
│ Brak wyniku         │ Brak porównania     │ Brak wyniku         │ Brak wyniku         │
│ Brak decyzji MT     │ Brak niezależnego GT│ Brak GT numeru      │ Brak par GT–wynik   │
└─────────────────────┴─────────────────────┴─────────────────────┴─────────────────────┘

WYNIKI I ICH WIARYGODNOŚĆ
Obszar     Miara                         Wynik     Próba (n)   Stan              Przyczyna / interpretacja
MT         Wykrycie tablicy              —         —           Brak danych       Brak ocenionych wywołań
Pose       Zgodność obrysu (IoU)         —         0 par       Brak danych       Brak niezależnych obrysów GT
Pose       Błąd narożników (NMCE)       —         0 par       Brak danych       Brak niezależnych obrysów GT
MZ         Pełny poprawny numer         —         —           Brak danych       Brak porównań z GT
MZ         Błąd znaków (CER)            —         —           Brak danych       Brak znaków GT
ALPR       Poprawny numer końcowy       —         —           Brak danych       Brak ocenionych obserwacji
[Opcjonalnie] MT wielotablicowe — formalne TP/FP/FN: Niedostępne (brak protokołu/GT)

POSTĘP WERYFIKACJI                    [Przejdź do weryfikacji]
Liczba tablic MT   [●○○○○○○○] 0 z 8 wywołań
Obserwacje         [●○○○○○○○○] 0 z 9 obserwacji
Dostępne pary GT   niezależne Pose: 0 | MZ: brak ocenionych odczytów

CZASY NA TELEFONIE — POMIARY NIEZALEŻNE OD GT
MT: inferencja ... ms   MZ: inferencja ... ms   ALPR: cały proces ... ms
(p50, P95 i n; wartości wyłącznie z istniejącego, zweryfikowanego raportu)

[▸ Dlaczego nie ma wyników?]   [▸ Ograniczenia badania]
[▸ Pochodzenie danych]        [▸ Szczegóły techniczne]
```

Ilustracja przedstawia **układ i przykładowe teksty**, nie obliczone wyniki tej sesji. Liczby postępu `0/8`, `0/9` pochodzą z przedstawionej sesji z 19.10, ale w implementacji nigdy nie są wpisane na stałe: wszystkie pochodzą z aktualnego stanu weryfikacji.

### 2.1. Nagłówek

- Tytuł: **„Podsumowanie wyników sesji”**.
- Drobny podtytuł: **„Wyniki, stan weryfikacji i ograniczenia pomiaru”**.
- Jeden z prawdziwych statusów: `Weryfikacja nierozpoczęta`, `Weryfikacja w toku`, `Formularz kompletny — do zatwierdzenia`, `Formularz zatwierdzony`, `Ocena naukowa nieukończona`.
- Odrębny napis `Raport wstępny` dla niezakończonych analiz. Status nie może sugerować „finalny”, gdy `multi_plate.formal_status = NOT_EVALUABLE`.
- Tryb GT: `asystowany` lub `zaślepiony` z jednozdaniowym wyjaśnieniem po rozwinięciu.
- `Sesja / wariant / telefon` z `conditions`, bez kopiowania pełnych JSON-ów do nagłówka.

### 2.2. Cztery kafle

Każdy kafel ma **maksymalnie trzy linie**: zrozumiała nazwa, **główny wynik**, **jedna przyczyna/status**. Bez metodologicznych akapitów w kaflach. Kafel jest skrótem do odpowiedniego fragmentu tabeli, nie alternatywnym sposobem liczenia.

| Kafel | Nagłówek | Główny wynik, jeśli policzalny | Przy braku danych |
|---|---|---|---|
| MT | `Wykrywanie tablic` | `x z n potwierdzonych wskazań` ze wskazaniem **jednostki: wywołania z jedną tablicą**, *nie pełne recall/precision* | `Brak wyniku` + `Brak ocenionych wywołań` |
| Pose | `Położenie obrysu` | `Średnie IoU: x%`, niżej `n par GT` | `Brak porównania` + `Brak niezależnego GT obrysu` |
| MZ | `Odczyt znaków` | `x z n poprawnych pełnych numerów` | `Brak wyniku` + `Brak zweryfikowanych numerów GT` |
| ALPR | `Cały system ALPR` | `x z n poprawnych numerów na obserwację` | `Brak wyniku` + `Brak kompletnych par wynik–GT` |

Wartości policzalne w trakcie weryfikacji pozostają oznaczone jako **wstępne**, nawet gdy licznik i mianownik istnieją. Kafel MT nie prezentuje `TP`, `precision`, `recall` lub `mAP` tam, gdzie nie zostały formalnie wyznaczone. Jeśli wynik jakości jest asystowany, wyraźnie nazwać go `diagnostyczny`.

### 2.3. Tabela jako główna część widoku

**Sześć kolumn:** `Obszar`, `Miara`, `Wynik`, `Próba / mianownik`, `Stan`, `Wyjaśnienie`.

Przykład treści bez wymyślania wartości:

| Obszar | Miara | Wynik | Próba / mianownik | Stan | Wyjaśnienie |
|---|---|---|---|---|---|
| MT | Potwierdzona lokalizacja | `—` lub `x z n (y%)` | `n wywołań z 1 tablicą` | `Brak danych` / `Wstępny` | `Tylko ocenione wywołania z jedną tablicą; nie jest to pełne recall` |
| MT | Brak detekcji | `—` lub `k` | `ocenione wywołania` | `Brak danych` / `Opisowy` | `Nie obejmuje klatek, na których MT nie uruchomiono` |
| Pose | Zgodność obrysu (IoU) | `—` lub `x%` | `n niezależnych par GT` | `Brak danych` / `Wstępny` | `Im więcej, tym większe pokrycie obrysów` |
| Pose | Błąd narożników (NMCE) | `—` lub `x%` | `n niezależnych par GT` | `Brak danych` / `Wstępny` | `Im mniej, tym lepiej` |
| MZ | Poprawny cały numer | `—` lub `x z n (y%)` | `n zweryfikowanych odczytów MZ` | `Brak danych` / `Wstępny` | `Porównanie odczytu z rzeczywistym numerem tablicy` |
| MZ | Błąd znaków (CER) | `—` lub `x%` | `e błędów / z znaków GT` | `Brak danych` / `Wstępny` | `Błędy znaków; nie obejmuje MZ NOT_RUN` |
| ALPR | Poprawny numer końcowy | `—` lub `x z n (y%)` | `n kwalifikujących się obserwacji` | `Brak danych` / `Wstępny` | `Wynik całego potoku; inny mianownik niż MZ` |

- **Nie pokazywać `x/n`, jeśli `n` brak albo `n=0`.** Wówczas wynik `—`, stan `Brak danych` i jasno podana przyczyna.
- **`0/n` jest dozwolone wyłącznie, gdy `n>0` i zero wynika z przeprowadzonych pomiarów.**
- **Procent nie zastępuje licznika i mianownika**; obie wartości pozostają dostępne.
- Jeśli określona miara nie dotyczy danej sesji (np. MZ nie został uruchomiony), stan `Nie wykonano`, a nie `Błąd` czy `0%`.
- Gdy miara jest formalnie zablokowana przez brak niezależnego GT/ROI/protokołu, stan `Nie można ocenić naukowo`, a nie `Brak wyniku modelu`.
- Osobny wiersz `MT wielu tablic — formalne TP/FP/FN` pojawia się **tylko gdy sesja obejmuje taki zakres**; nie wypełnia się go liczbami z `operator_diagnostic`.
- Stosować polskie etykiety `Wykrywanie tablic`, `Położenie obrysu`, `Odczyt znaków`, `Cały system` — skróty MT/Pose/MZ są pomocnicze, zawsze objaśnione.
- Pierwsza kolumna wizualnie grupuje wiersze, bez wielkich pustych nagłówków sekcji.
- Kliknięcie w wiersz otwiera krótkie objaśnienie i dokładną jednostkę; nie uruchamia zmiany GT ani ocen operatora.

### 2.4. Kolory — dyskretnie i jednoznacznie

Nie kolorować całych dużych kafli ostrą zielenią/czerwienią. Proponowane kolory wyłącznie do małych znaczników i delikatnych teł wierszy, zgodne z jasnym motywem istniejącej aplikacji:

| Stan | Proponowana barwa | Kryterium | Czy oznacza jakość modelu? |
|---|---|---|---|
| `Policzalny` | zgaszona zieleń | dostępny prawidłowy mianownik i wynik **w danym zakresie** | **Nie**; to status kompletności, nie ocena skuteczności |
| `Wstępny` | bursztyn | policzone na części weryfikacji / przed zatwierdzeniem | **Nie** |
| `Brak danych` | neutralna szarość | brak licznika/mianownika/GT | **Nie** |
| `Nie wykonano` | neutralna szarość + symbol pauzy | etap faktycznie nieuruchomiony | **Nie** |
| `Nie można ocenić naukowo` | ochra lub obrys ostrzegawczy | nieudowodniona proweniencja, ROI, matching albo brak protokołu | **Nie** |
| `Niespójne dane` | czerwony akcent | faktyczna sprzeczność źródeł lub walidacji, powód jest znany | **Nie** |

- Tekst statusu musi być czytelny bez rozpoznawania barw (daltonizm / druk czarno-biały).
- **Niski wynik skuteczności** nie jest tym samym, co `Niespójne dane`; nie kolorować miar jakości na czerwono bez jawnych, zatwierdzonych progów.
- Proweniencję asystowaną pokazać tekstem `Asystowane` z wyraźną notą; samo oznaczenie kolorem nie wystarczy.

### 2.5. Kompletność weryfikacji — małe paski postępu

Jeden kompaktowy blok pod tabelą (nie powiela dużych kafli), obejmujący **sprawdzone decyzje**, a nie skuteczność modeli:

- `Wywołania MT — oceniono liczbę tablic: x z n` na bazie `progress.mt_invocations_cardinality_reviewed / progress.mt_executed_active`.
- `Obserwacje z zakończonymi decyzjami: x z n` z kanonicznego `form_verification.verified / total`; jeśli licznik nieobecny, nie próbować go wyprowadzać z `subjects_mt_done`.
- `Pary niezależnego GT obrysu: n` — tylko `pose.measured_n` i jednoznaczny opis, bez sztucznego procentu, jeżeli nie zdefiniowano całkowitej liczby par oczekiwanych.
- `Odczyty MZ z GT: n` — `mz.evaluable_reads` (liczba sprawdzonych odczytów); **nie** interpretować `n` jako kompletności, o ile nie znamy całej populacji kwalifikujących się MZ.

Paski nie reprezentują TP/FP/FN, IoU, Exact ani CER. Dla `n=0` pasek pusty i tekst `Brak zadań do oceny` lub `Brak mianownika` zależnie od faktycznej przyczyny.

### 2.6. Wydajność — oddzielona od GT

Jedna zwarta sekcja: `Czasy na telefonie — nie wymagają ręcznej weryfikacji numerów`.

| Nazwa | Miara | Jednostka | Dane źródłowe |
|---|---|---|---|
| `MT — inferencja modelu tablic` | mediana (p50), P95, n | ms | `performance.latency.mt` |
| `MZ — inferencja modelu znaków` | mediana (p50), P95, n | ms | `performance.latency.mz` |
| `ALPR — przetwarzanie potoku` | mediana (p50), P95, n | ms | `performance.latency.pipeline` |

Opcjonalnie krótka linia: `Klatki odebrane: …; przetworzone: …; pominięte przez filtr: …`, ale tylko gdy wszystkie składowe mają wiarygodne liczniki. To nie jest graf efektywności modelu. Nie obliczać od zera P95 w UI.

### 2.7. Wykres pomocniczy — zalecany dopiero w drugiej iteracji

Preferowany jest **poziomy pasek kompletności decyzji**, nie wykres jakości modelu, jeśli mianowniki nie są dostępne. Przy kompletnej weryfikacji można dodać proste porównanie MT/MZ/ALPR, ale tylko dla miar o **jawnie różnych jednostkach** — bez wspólnego procentowego wykresu sugerującego porównywalność. IoU i CER nie powinny być rysowane na jednej osi „im wyżej, tym lepiej”, ponieważ mają przeciwne kierunki interpretacji.

### 2.8. Szczegóły — domyślnie zwinięte

- **Dlaczego brak wyniku?** Krótka, konkretna lista pochodząca z `caveats`, `form_verification.issues` i `multi_plate.formal_issues`; maks. trzy najważniejsze powody na pierwszym poziomie, pozostałe po rozwinięciu.
- **Ograniczenia badania** — mała próbka, predykcje widoczne operatorowi, możliwa korelacja kolejnych klatek, brak formalnego matchingu ROI/GT, itd.
- **Pochodzenie danych** — ID sesji, SHA ZIP, rewizja sidecara, urządzenie, wariant, tryb GT, status weryfikacji.
- **Tabela techniczna** — utrzymać istniejącą tabelę z pełnymi statystykami, w tym zliczeniami pomyłek znaków. Nie usuwać ani nie zastępować fałszywie uproszczonym zestawieniem.

Nie doklejać technicznej listy przyczyn bezpośrednio pod każdym wierszem tabeli: to właśnie tworzy obecną „ścianę tekstu”.

## 3. Kanoniczne mapowanie danych

**Źródłem prawdy nie jest nowy widok ani dodatkowy licznik w GUI.** Adaptacja prezentacji musi pozostać funkcją tylko do odczytu.

| Obszar interfejsu | Kanoniczne pola / interfejs | Zasada |
|---|---|---|
| Status sesji | `scientific_state`, `review_status`, `review_mode`, `form_verification.status` (jeśli występuje) | oddzielić stan formularza od formalnej ewaluacji |
| Postęp MT | `progress.mt_invocations_cardinality_reviewed`, `progress.mt_executed_active` | wywołania, a nie klatki |
| Obserwacje | `form_verification.verified / total` | wykorzystać istniejącą politykę, nie przeliczać podmiotów z heurystyki |
| MT 1-tablicowe | `mt.localized_n`, `mt.single_plate_n`, `mt.no_detection_n`, `mt.false_detections_confirmed` | nazwać jednostkę i ograniczenie „nie pełny recall” |
| Pose niezależny | `pose.measured_n`, `pose.polygon_iou_mean_pct`, `pose.nmce_mean_pct`, opcjonalnie mediany | tylko niezależne porównywalne pary |
| Pose asystowany | `pose.manual_assisted_gt_n`, `pose.assisted_corrections` | diagnostyka osobna, bez domieszania do niezależnego IoU |
| MZ | `mz.evaluable_reads`, `mz.exact_n`, `mz.gt_characters`, `mz.error_characters`, `mz.cer` | `CER` jako już policzona proporcja, w UI ×100% |
| Cały ALPR | `alpr.evaluable_subjects`, `alpr.exact_n` | mianownik obserwacji inny niż MZ |
| Wiele tablic | `multi_plate.total_multi_invocations`, `verified_multi_invocations`, `operator_diagnostic`, `formal_status`, `formal_issues` | brak automatycznego awansu na formalne TP/FP/FN |
| Wydajność | `performance.latency.mt/mz/pipeline` i `performance.frame_flow` | n, p50, P95 wyłącznie z raportu telefonu |
| Metodyka i proweniencja | `conditions`, `caveats`, `methods`, `source_archive_sha256`, `review_revision` | dane źródłowe dostępne po rozwinięciu / eksporcie |

Wersje z brakującymi polami obsłużyć bez `KeyError`, nie domyślać się danych.

### Statusy i reguły wyświetlania

Wprowadzić prywatny dla UI `MetricRow` z polami:

```
metric_id, group, label, formatted_value, numerator, denominator,
unit, scientific_scope, status, reason, source_path,
review_provenance, is_formal, is_partial
```

To **model widoku**, a nie nowy format danych eksperymentalnych. `formatted_value` musi wynikać wyłącznie z kanonicznych wartości, nie niezależnych obliczeń. Dla danych ilościowych bez mianownika status jest jawny, liczba `0` nie jest wymyślana. Kody statusów UI nie mogą nadpisywać żadnych `review_status` w sidecarze.

Przykładowe reguły:

```text
if source_not_verified:
    quality_metric -> BRAK_ZWERYFIKOWANEGO_ZRODLA
elif metric.is_formal and canonical_formal_status == NOT_EVALUABLE:
    -> NIE_MOZNA_OCENIC_NAUKOWO
elif stage_was_NOT_RUN:
    -> NIE_WYKONANO
elif denominator is None or denominator == 0:
    -> BRAK_DANYCH
elif contradictory_source:
    -> NIESPOJNE_DANE
elif review_is_in_progress:
    -> WSTEPNY
else:
    -> POLICZALNY_W_SWYM_ZAKRESIE
```

Warunki są poglądowe; implementacja bierze rzeczywiste flagi/kontrakty z istniejących funkcji i nie może określać stanu `NOT_RUN` po samym braku rekordu. Jeśli nie da się ustalić przyczyny, wyświetlić `Brak danych (przyczyna nieustalona)`.

**Szczególna uwaga o CER:** może matematycznie przekroczyć 100% przy wielu znakach wstawionych; nie obcinać do 100% i nie rysować automatycznie w pasku 0–100. **NMCE** również nie może być sztucznie obcinane. Wyniki jakości nie zmieniają się od stylizacji.

## 4. Gotowe teksty polskie (copy do UI)

| Obecny tekst | Nowy, prostszy |
|---|---|
| `Wyniki naukowe • raport wstępny, z jawnymi mianownikami` | `Podsumowanie wyników sesji` + osobny stan `Weryfikacja w toku` |
| `Trafienia MT potwierdzone przez operatora: nieobliczalne (brak mianownika)` | `Wykrywanie tablic` → `Brak wyniku` → `Brak ocenionych wywołań z jedną tablicą` |
| `Polygon IoU: — (brak porównywalnych par)` | `Zgodność obrysu (IoU)` → `Brak porównania` → `Brak niezależnych obrysów GT` |
| `NMCE` bez wyjaśnienia | `Błąd narożników (NMCE)` + `Im niższy, tym lepiej` |
| `Dokładne numery: nieobliczalne (brak mianownika)` | `Poprawny pełny numer` → `Brak porównań z rzeczywistym numerem` |
| `CER: — (brak GT i zweryfikowanego odczytu)` | `Błąd znaków (CER)` → `Brak danych` → `Brak par odczyt MZ–GT` |
| `Próby bez uruchomionego MZ nie są błędnymi odczytami` | Szczegóły: `MZ nie był uruchomiony — tej próby nie liczono jako błędu OCR` |
| `Pipeline` | `ALPR — przetwarzanie potoku` |
| `Weryfikacja asystowana` | `Operator widział predykcje modelu; GT nie był zaślepiony` |
| `Brak mianownika dla skuteczności MT` | `Nie ma jeszcze wystarczająco zweryfikowanych wywołań MT` |
| `Formalne TP/FP/FN: NOT_EVALUABLE` | `Formalna skuteczność wykrywania: nie można jeszcze wyliczyć` + `Brak niezależnego GT lub potwierdzonego zakresu ROI` |

Długie objaśnienia i formuły pozostają w szczegółach, nie w kaflach lub zawsze widocznych tabelach.

## 5. Architektura wdrożenia bez zmiany nauki

### P2B-UI / Z4MOBREV031 — iteracja pierwsza

1. **Wyłącznie odczyt:** `auto_annotation_tool/gui/mobile_science_viewmodel.py` (nowy) — adapter `make_scientific_summary -> metric rows`, bez zapisu, heurystyk GT, samodzielnej ewaluacji lub zmian statystyk.
2. **Komponent Tk:** `auto_annotation_tool/gui/mobile_science_summary_ui.py` (nowy) — kafle 2×2, tabela `ttk.Treeview`, zwijane sekcje i pasek postępu, dostępne przy małym oknie przez jeden pionowy scrollbar (bez piętrowych scrolli).
3. **Integracja:** `auto_annotation_tool/gui/z4_mobile_sample_review.py` — zastąpić główny `tk.Text` w zakładce „Analiza wyników” nowym komponentem; zachować techniczną tabelę (`self.stats_tree`) i przycisk jej otwierania. W `refresh` przekazać istniejące `self._science_data`, `self.stats` i status formularza zamiast liczyć je ponownie w widżecie.
4. **Odrębne źródło prawdy:** `mobile_scientific_review.py` i `mobile_roi_evaluation.py` pozostają niezmienione. Zachować `display_scientific_summary` na potrzeby kompatybilności i/lub istniejących eksportów; nie kasować tekstowych wyników z innych kanałów.
5. **Testy:** nowy `tests/test_z4mobrev031_science_dashboard.py` (liczniki, gate, statusy, dostępność, Tk, mała wysokość, legacy) + zestawy regresyjne Z4MOBSAFE030 / Z4MOBREV024 / Z4MOBREV030.
6. **Instalator:** skrypt `patch_Z4MOBREV031_PANEL_ANALIZY_TABELA_KAFLE_20261019.py`, wymagający aktualnych SHA z Windows `start4`, z `--check`, `--apply`, backup i odmową nadpisania nieznanej wersji; **nie przygotowywać go bez sprawdzenia bieżącego stanu**.

### Druga iteracja (opcjonalna po odbiorze pierwszej)

- Dodać minimalne paski kompletności w przypadkach z prawdziwymi mianownikami.
- Jeśli potrzebny wykres, preferować **przegląd ukończenia decyzji**, nie pozornie porównywalny „procent skuteczności wszystkich modułów”.
- Rozwinąć interaktywne wskazywanie konkretnej przyczyny braku wyniku — bez zmiany geometrii MT/Pose, GT lub innych etapów eksperymentu.

### Niezależna ścieżka projektu (poza Z4MOBREV031)

- Wciąż pozostaje plan **Desktop P2B: weryfikacja wielu GT na pełnej klatce, z adapterem narzędzi Z2 oraz warstwami ROI**. Ta specyfikacja dotyczy tylko czytelności naukowego podsumowania i **nie zastępuje P2B**.
- Formalne wielotablicowe TP/FP/FN pozostaje zablokowane zgodnie z `Z4MOBSAFE030`, aż powstanie niezależny pełnoklatkowy GT, zatwierdzony protokół IoU i prawidłowe dowody pokrycia ROI.

## 6. Testy akceptacyjne

| ID | Sytuacja | Wymagane zachowanie |
|---|---|---|
| T01 | Nowa sesja, brak GT | Kafle pokazują `Brak wyniku`, nie `0%`; postęp 0/n tylko dla rzeczywistych mianowników. |
| T02 | Weryfikacja częściowa | Wyniki dostępne jako `Wstępne`; brak fałszywej etykiety `Zatwierdzone`. |
| T03 | Zweryfikowane 0 sukcesów / n>0 | Widoczne `0 z n (0%)`, ponieważ to prawdziwa zmierzona wartość. |
| T04 | `n=0` lub `None` | Wartość `—`, przyczyna; żadnego dzielenia przez zero. |
| T05 | MZ `NOT_RUN` | Nie obciąża odczytów, nie zmienia CER na 0%. |
| T06 | Blinded independent Pose | Pokazuje IoU i NMCE z niezależnych par, jawny `n`. |
| T07 | Tylko asystowane Pose | Główne IoU/NMCE `—`; osobna diagnostyka; zero fałszywie niezależnych par. |
| T08 | Wiele tablic / stary `multi_plate_v1` | `formal_status=NOT_EVALUABLE`, `TP/FP/FN=—`; diagnostyka operatora nie podnosi statusu formalnego. |
| T09 | ROI niepełne / brak dowodu pełnej klatki | Brak metryk formalnych, krótka czytelna przyczyna. |
| T10 | Sidecar zatwierdzony, ale brak niezależnego GT | Rozróżnienie `Formularz zatwierdzony` i `Ocena naukowa nieukończona`. |
| T11 | Stare archiwum bez niektórych pól | GUI działa, pokazuje `Brak danych`, nie rzuca wyjątku. |
| T12 | Wybrany raport zmieniony / nowa rewizja sidecara | Odtwarza aktualną tabelę i statusy; nie miesza sesji ani SHA. |
| T13 | Każda liczba względem poprzedniego eksportu | `numerator/denominator`, IoU, CER, p50/P95 pozostają identyczne, włącznie z `None`. |
| T14 | Mały rozmiar okna i skalowanie Windows 125–150% | Kafle/tabela nie nachodzą, dostępny scroll i focus klawiatury; brak uciętych etykiet. |
| T15 | Tryb ciemny/jasny, kontrast, brak rozpoznawania kolorów | Status czytelny z tekstu i symbolu; poprawny kontrast. |
| T16 | `CER > 100%`, nietypowo wysokie NMCE | Brak przycinania i przekłamania liczb. |
| T17 | Kliknięcie „Tabela techniczna” | Istniejące dane szczegółowe i przewijanie dostępne bez utraty bieżącego stanu. |
| T18 | Powtórne otwarcie panelu/zmiana zakładek | Brak zapisu do ZIP, sidecarów lub zmian w licznikach naukowych. |
| T19 | Brak zweryfikowanego archiwum lub niezgodne SHA | Brak procentów jakości modelu z niepotwierdzonego źródła; jasny komunikat. |
| T20 | Wydajność z telefonu, ale bez GT | p50/P95 i n mogą być pokazane niezależnie od jakości odczytu, ze wskazaniem źródła. |

**Warunek odbioru:** pełne testy regresyjne + wizualna akceptacja na sesji `P1-R0-FP32-B` z 19.10 (9 obserwacji, 8 wywołań MT), starej sesji z częściowym GT i zarchiwizowanej sesji bez niezależnego Pose. Należy porównać liczby z dotychczasowym eksportem JSON/Markdown oraz potwierdzić brak zmian w ZIP i sidecarach. Próba odbiorcza GUI nie stanowi nowego formalnego pomiaru modeli.

## 7. Status prac na 19.10.2026

- **Wykonano:** poprawki czytelności wykresu Z4MOBREP031–036, łącznie z opisem osi czasu i legendą; uproszczenie formularza GT numeru Z4MOBREV030; zabezpieczenie formalnych metryk ROI Z4MOBSAFE030.
- **Zaakceptowano na podstawie rozmowy:** koncepcję nowej zakładki „Analiza wyników” (cztery kafle, tabela, szczegóły, osobna wydajność).
- **Nie wykonano w tym dokumencie:** implementacji Z4MOBREV031, instalacji patcha na Windows, testów Tk nowego panelu ani pełnoklatkowego edytora GT P2B.

**Zasada końcowa:** poprawa widoku nie może „naprawiać” niekompletnych danych przez ich zgadywanie. Panel ma tłumaczyć, *dlaczego* miara istnieje lub nie istnieje, oraz pozwalać szybko przejść do brakujących decyzji operatora.

---

## 8. Implementacja — Z4MOBREV031 (19.10.2026)

Ta sekcja jest dodatkiem do specyfikacji przed wdrożeniem na lokalnym Windows. Dotychczasowe rozdziały 1–7 pozostają zachowane.

- `auto_annotation_tool/gui/mobile_science_viewmodel.py`: tylko formatowanie pól kanonicznego `make_scientific_summary`; jawne statusy MISSING, DIAGNOSTIC, PRELIMINARY, AVAILABLE, NOT_EVALUABLE, SOURCE_UNVERIFIED. Nie oblicza IoU, CER, TP/FP/FN ani innych naukowych statystyk; może jedynie wyświetlić dostarczone przez kanon liczniki, mianowniki i procenty.
- `auto_annotation_tool/gui/mobile_science_summary_ui.py`: jeden przewijany panel z kaflami, `ttk.Treeview`, paskami postępu decyzji, czasami Androida i rozwijanymi sekcjami. Przy braku miejsca pionowo kurczy się obszar widoku, nie gubi tekstu.
- `auto_annotation_tool/gui/z4_mobile_sample_review.py`: integracja przez `MobileScienceSummaryPanel`, zachowanie istniejącej tabeli technicznej i jej przełącznika, istniejących obliczeń, raportów i archiwalnych decyzji operatora.
- `tests/test_z4mobrev031_science_dashboard.py`: kontrola ``0`` vs brak danych, dzielenia przez zero, niezależnego i asystowanego GT, CER > 100%, metryk wielotablicowych, statusów, starszych raportów, wydajności i widoku Tk.

### Ograniczenia / kolejne etapy

- Paski reprezentują wyłącznie kompletność zweryfikowanych decyzji MT/formularza. Nigdy nie kodują wartości skuteczności modeli.
- Żaden wizualny wskaźnik `AVAILABLE` / `DIAGNOSTIC` nie jest formalnym progiem jakości modelu. Główna tabela i proweniencja pozostają jednoznaczne w eksporcie.
- Ekran pełnoklatkowych anotacji GT / ROI i formalna ewaluacja wielotablicowa (Desktop P2B) są oddzielnym zadaniem; ich brak nie jest ukrywany przez nowy dashboard.
- Warunek odbioru: użytkownik uruchamia patch z `--check`, następnie `--apply`, testuje regresję i akceptuje GUI na rzeczywistej sesji `P1-R0-FP32-B`.
