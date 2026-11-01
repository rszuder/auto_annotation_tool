# ALPR — kontrakt pytań badawczych i analizy F4–F6

**Wersja:** `ALPR-ANALYSIS-1.0`\
**Data ustalenia zasad analitycznych:** 31.10.2026\
**Status:** zamrożona specyfikacja do wykonania i audytu, **nie** rejestracja sprzed uzyskania wyników F4.\
**Zakres:** praca inżynierska o mobilnym ALPR i własnym środowisku do jego rozwijania i oceny; etap F4 (zebrany), F5A/F5B (stan lokalny do sprawdzenia), F6 (nie przedstawiono dowodu wykonania).\
**Przedmiot zmiany:** kwalifikowanie raportów do **analizy**, a nie modyfikacja wyników, GT, modeli, ingerencja w wyniki eksperymentów ani przeredagowanie szablonu TeX.

## 0. Pochodzenie i chronologia zasad

Odróżniać trzy kategorie informacji:

- **[WCZEŚNIEJSZY PLAN]** — założenia wynikające z dokumentu `ALPR_AKT86_METODYKA_POROWNAN_F4_F5_F6_20261024.md` (projekt, 24.10), z oryginalnego planu badań i z treści pracy z 20.10.
- **[DOWÓD]** — konkretne stwierdzenie podparte audytem `RAPORT_F4_12_SESJI_AKT56_20261022.md`, aktualnym manifestem albo zweryfikowanym eksportem. Audyt techniczny nie dowodzi automatycznie gotowości jakości.
- **[DECYZJA RETROSPEKTYWNA 31.10]** — reguła analizy, sformułowana po zebraniu 12 sesji F4. Tę datę należy ujawnić w pracy; nie przedstawiać jako prerejestracji F4. Zasady stosować jednakowo do wszystkich wyników i weryfikować na wejściu do analizy, nigdy wybiórczo zależnie od wyniku wariantu.

Niniejszy dokument utrwala zasady analizy przed dalszą interpretacją i publikowaniem porównań. Zmiany w przyszłości wymagają nowej numerowanej wersji oraz rejestru wpływu na wszystkie warianty. Nie nadpisywać ani nie wycofywać starszych wersji.

## 1. Cel pracy — zgodność z istniejącym TeX

Cel konstrukcyjny, zgodny z sekcją „Cel i zakres pracy” w `tresc_pracy(20261020-000036).tex`: zbudowanie mobilnego systemu ALPR oraz środowiska Desktop do przygotowania danych, treningu, oceny i wyboru modeli, z wersjonowaną wymianą danych z aplikacją Android.

**Nadrzędne pytanie badawcze:**

> Jak dobór konfiguracji modeli i sposobu organizacji obliczeń wpływa na **wydajność, skuteczność wykrycia i poprawność końcowego odczytu** lokalnego ALPR na telefonie o ograniczonych zasobach — i jakimi dowodami można uzasadnić wybór jednej konfiguracji?

To pytanie nie zakłada przewagi jakiegokolwiek wariantu. W pracy należy wykazać powtarzalność procesu badawczego, wiarygodne pomiary i uzasadnione granice wniosków, a nie dowodzić z góry, że INT8/ROI/AutoZoom „działa lepiej”.

**Testowalne twierdzenia / oczekiwane rezultaty:**

- **C1 — identyfikowalność:** dla każdej użytej obserwacji można wskazać źródłowe archiwum, APK, model/checkpoint, scenariusz, konfigurację, jednostkę i wersję obliczenia. Jeśli nie — taka obserwacja nie stanowi pełnoprawnego pomiaru w danym twierdzeniu.
- **C2 — wydajność:** można zmierzyć koszt MT, MZ i całego potoku, a zmianę FP32/INT8 opisać na telefonie przy kontrolowanych warunkach. Kierunek i wielkość zmiany są **wynikiem**, nie założeniem.
- **C3 — skuteczność:** można osobno ocenić wykrycie tablicy (BBOX), jej geometrię (Pose), wykonany odczyt znakowy (MZ) i cały potok E2E, nie mieszając mianowników i źródeł GT.
- **C4 — dobór konfiguracji:** F4/F5 dostarczają danych umożliwiających wybór świadomego kompromisu jakość–czas–pokrycie–pamięć; jeśli dowód jest niepełny, podać warunki i ograniczenia decyzji, nie fałszywą optymalność.
- **C5 — wynik końcowy:** jedna zamrożona konfiguracja przechodzi niezależną ocenę F6 na nowym materiale; bez tego nie deklarować końcowej, niezależnie zmierzonej skuteczności systemu mobilnego.

Słowo „udowodnić” w opisie pracy rozumieć jako **przedstawić dowody i sprawdzić hipotezy**; wynik negatywny też jest pełnowartościowy.

## 2. Cztery doświadczenia — bez zmieniania sensu

| Etap | Zmienna badana | Pytanie | Co pozostaje stałe | Wynik/wniosek |
|---|---|---|---|---|
| **F4** | FP32 vs INT8 tej samej pary źródłowych checkpointów DAY MT/MZ | Czy zmiana precyzji zmienia czasy MT/MZ, całego ALPR i jakość? | APK, telefon, MT512/MZ320, CPU2, R0, MP/Lock/AutoZoom OFF, scenariusz i protokół | Zmierzony kompromis wydajność–jakość, osobno DAY i NIGHT |
| **F5A** | R0 (pełna klatka), R1 (MP+do 1 ROI), R2 (MP+do 2 ROI) | Czy koszt MP i ograniczenia ROI są uzasadnione pokryciem tablic? | modele, precyzja, progi, urządzenie, AZ OFF, wspólne źródło | Koszt oraz pokrycie pełnej sceny, w tym tablice poza ROI |
| **F5B** | AutoZoom OFF/ON | Czy zoom pomaga trudnym/mniejszym tablicom, jaki jest jego koszt? | modele, precyzja, polityka MP/ROI, progi, początkowy kadr i reset | Zmiana odczytu + dodatkowe wywołania i opóźnienie |
| **F6** | Brak — jedna konfiguracja po wyborze | Jaka jest końcowa jakość i wydajność na niezależnych danych? | wszystkie zamrożone parametry i reguły oceny | Końcowy pomiar, nie wybór lepszego wariantu |

**[DOWÓD F4]** 12 oryginalnych sesji (2 warianty × 2 scenariusze × 3 powtórzenia) były technicznie kompletne w audycie AKT56. Każde z 216 nominalnych 10-sekundowych okien miało co najmniej jedno zmierzone MT, ale liczby wywołań/śladów były różne. DAY/NIGHT oznaczają **materiał fotograficzny wyświetlany na TV**, nie różne checkpointy DAY/NIGHT. Wyników tej kampanii nie przedstawiać jako ślepego lub terenowego testu nocnej jazdy.

**[OTWARTE]** Nie ustalać na podstawie samego starego planu, że F5 lub F6 są już wykonane. Agent ma sprawdzić bieżące źródła i przed publikacją odnotować aktualny stan.

## 3. Jedno główne rozróżnienie: WYBÓR ≠ OCENA ≠ WNIOSEK

**[DECYZJA RETROSPEKTYWNA 31.10]** Jeden koszyk zaimportowanych raportów. Zaznaczenie raportu oznacza „chcę go zbadać”, a nie „cały raport jest pełnowartościowy dla każdej metryki”.

**Poziom A — wybór:** pozwolić zaznaczyć każdy czytelny wpis importu z identyfikatorem sesji i SHA źródła. Nie stawiać `READY`, `APPROVED_LIMITED` lub kompletnego GT jako warunku samego checkboxa. Wpis bez odzyskanego oryginału może pozostać w koszyku diagnostycznym, ale musi mieć status niedostępnego źródła i nie może dostarczać liczb.

**Poziom B — kwalifikacja do miary:** moduł po otwarciu sam rozpoznaje pytanie badawcze, weryfikuje oryginały, manifesty, świeżość eksportów, kontroluje jednostki i przypisuje status każdej mierze: `FULL`, `SUBSET`, `N/A` albo `NOT_COMPARABLE`. Odmowa dotyczy **konkretnej miary lub twierdzenia**, nie całego koszyka.

**Poziom C — interpretacja:** oddzielić wyniki **opisowe** od **kontrolowanego porównania**. Brak dowodu identyczności zdjęć czy różne warunki termiczne nie unieważniają punktu pomiarowego, ale ograniczają siłę wnioskowania przyczynowego. Naruszenie SHA/manifestu blokuje udział danych numerycznych z tego źródła, nie tylko wyświetla ostrzeżenie.

Nie wprowadzać dwóch koszyków „wydajność” i „jakość”. Można mieć **wewnątrz modułu** wybór pytania F4/F5A/F5B i wykresu, który sam określa dopuszczalne jednostki.

## 4. Jednostki badawcze i identyfikatory

Nie utożsamiać:

1. **Sceny/planszy** — jedna zaplanowana fotografia, 18 DAY albo 18 NIGHT w F4.
2. **Okna prezentacji** — nominalne 10 s danej planszy; niedokładność ręcznej zmiany TV jest ograniczeniem.
3. **Klatki źródłowej** — rzeczywista bitmapa z Androida; nie musi być unikalną planszą.
4. **Wywołania MT** — rzeczywistego uruchomienia MT z `mt_invocation_id`.
5. **Detekcji FINAL** — po źródłowym postprocessingu/NMS; kilka FINAL z jednego MT jest możliwych.
6. **RAW odrzuconego przez NMS** — tylko dowód diagnostyczny, nie kolejny FINAL/FP.
7. **Wywołania MZ** — rzeczywistej próby modelu znaków; jeden ślad może zawierać wiele MZ.
8. **Fizycznej tablicy GT (GTR+GTZ)** — referencja operatora; może mieć wiele obserwacji z tego samego obrazu/sceny. Nie liczyć wielokrotnie tej samej tablicy jako niezależnego obiektu, jeśli twierdzenie dotyczy scen.
9. **Sesji** — jedna rejestracja r01/r02/r03. Trzech powtórzeń nie traktować jako 54 niezależnych fotografii.

Identyfikacja sesji: `session_id + source_archive_sha256 + manifest + zweryfikowane mapowanie F4 variant/scenario/rNN`. Źródło z telefonu zachować bajtowo. Historyczne `NIGHT_F32` z numeracją 4/5/6 mapować w analizie na FP32/NIGHT r01–r03 bez zmiany zapisanych danych.

## 5. Metryki i poprawne mianowniki — obowiązujące zasady

Szczegółowa tabela i kontrakt eksportowy znajdują się w `02_DEFINICJE_MIAR_I_BRAKOW.md`.

### 5.1. Wydajność

- **MT p50/p95 [ms]:** per rzeczywiste, ważne wywołanie MT; `n_MT` to ich liczba. Nie jest to p50 18 plansz.
- **MZ p50/p95 [ms]:** w obecnym F4 `character_inference_ms` bywa sumą MZ **na ślad**. Jeśli brak dowodu osobnych czasów per MZ, nazwać „czas etapu MZ/ślad”, nie „czas jednego odczytu MZ”. Liczbę wywołań MZ pokazywać niezależnie.
- **Potok p50/p95 [ms]:** zakończony rzeczywisty ślad ALPR, z `n_pipeline`; obok liczba MZ/ślad i MT/ślad. Nie wolno przypisywać różnicy potoku wyłącznie kwantyzacji, gdy liczba wywołań MZ jest różna.
- Brak wykonania to `n=0; p50/p95=N/A`, a nie `0 ms`; przerwane lub niepełne ślady odrzucamy z percentyli z jawną liczbą.
- Nie liczyć percentyla całej puli przez medianę z p95 trzech powtórzeń. Raportować 3 punkty sesyjne oraz medianę wyników sesyjnych jako **medianę z median** (z osobną nazwą).

### 5.2. MT — wykrycie vs Pose

- Kryterium dopasowania F4 zatwierdzone retrospektywnie wcześniej: **BBOX IoU ≥ 0,50**, source `FINAL`, greedy 1:1 według malejącego confidence, przy remisach stabilny indeks; żadnego dodatkowego NMS w Desktop. Nie zastępować kryterium przez Polygon IoU.
- `TP`, `FP`, `FN`: z sum kwalifikowanych, **kompletnych jednostek detekcyjnych** (wywołanie/ROI) z poprawną fizyczną referencją. Dla brakującej lub niepotwierdzonej GTR/pochodzenia BBOX nie domyślać liczb; oddzielić `UNASSESSABLE` i podać pokrycie. Wariant z 19 ocenialnymi z 21 nie jest bezwarunkowym wynikiem całych 21.
- `Precision=TP/(TP+FP)`, `Recall=TP/(TP+FN)`, `F1=2TP/(2TP+FP+FN)` — po zsumowaniu liczników w kwalifikowanym zakresie, nie przez średnią procentów sesyjnych. Niewykonane lub brakujące jednostki to N/A, a nie 0.
- **Pose availability:** odsetek źródłowych, dopasowanych MT z rzeczywistym `VALID_QUAD` i dowodem oryginalnych narożników; topologiczna poprawność nie jest miarą dokładności. Dla ważnych par Pose–GTR podać liczbę `n_pose` i Polygon IoU/NMCE; brak Pose: `N/A` geometrii i osobna liczba niepowodzeń.
- **GTR ≠ Pose modelu:** cztery narożniki operatora nie mogą być kopiowane do predykcji; BBOX modelu i obrys GTR mają odrębne źródła.
- `RAW` stłumione przez NMS nie jest FINAL FP. Jedna detekcja FINAL nie otrzymuje dwóch TP nawet gdy BBOX obejmuje dwie fizyczne tablice.

### 5.3. MZ — tekst i cały potok

- **Warunkowe Exact MZ** = liczba poprawnych pełnych odczytów / liczba kwalifikowanych rzeczywiście wykonanych MZ z czytelnym GTZ. **Micro-CER** = suma odległości Levenshteina / suma długości odpowiadających tekstów GTZ.
- MZ `NOT_RUN` to **nie** wykonany błędnie model MZ: nie tworzyć mu CER ani Exact dla *wykonanych odczytów*. W kompletnym E2E ten sam przypadek może oznaczać brak odczytu całego potoku i odpowiednio znaleźć się w mianowniku E2E.
- Rzeczywiście wykonane MZ z pustą predykcją i potwierdzonym GTZ należy rozliczyć zgodnie z zapisanym kontraktem (pełna odległość edycyjna), o ile brak nie jest klasyfikowany jako osobny nieocenialny błąd runtime; każdy przypadek jawny.
- **Exact E2E** — poprawny numer / wszystkie kwalifikowane, unikalne rzeczywiste tablice w zdefiniowanych oknach obserwacji; uwzględnia brak detekcji i `no-read`. Warunek: niezależna/udokumentowana mapa plansza→GT oraz deterministyczna reguła wyboru wyniku ze wszystkich odczytów w oknie, ustalona **przed** obliczeniem E2E. Jeśli brak dowodu mapowania albo GT, metryka E2E F4 ma `N/A` lub wyraźny status analizy eksploracyjnej, a nie pozornie pełne 100%.
- `ASSISTED` (GT skorygowane przy widocznym wyniku modelu) nie jest niezależną/zaślepioną walidacją. Późniejsze schowanie nakładki nie zmienia jej proweniencji.

## 6. F4 — formalny plan zestawienia po 12 sesjach

### 6.1. Kohorta i grupowanie

`E-MOB-QINT8-01`, 2 scenariusze `PAIR_DAY_01` i `PAIR_NIGHT_01`, w każdym: `DAY_FP32 r01–r03`, `DAY_INT8 r01–r03`. Nazwa wariantu z telefonu nie wystarcza bez rejestru SHA. Oba ramiona używają checkpointów DAY, zmienna to precyzja, nie checkpoint nocny.

**Zestawienie podstawowe:** FP32/INT8 **wewnątrz tego samego scenariusza**, każdy rNN osobny. Wszystkie sześć sesji scenariusza może trafić do jednego koszyka i modułu; mod nie powinien odrzucać ich jako grupy tylko dlatego, że jedna ma brak miary GT.

### 6.2. Zmienne i hipotezy (bez gwarancji wyniku)

- **F4-H1:** INT8 zmienia (hipoteza robocza: redukuje) czas pojedynczego MT; analogiczne porównanie MZ dopuszczalne tylko przy tej samej jednostce czasu.
- **F4-H2:** redukcja kosztu modelu nie musi w tej samej proporcji redukować czasu całego potoku; liczba MZ, preprocessing i stan termiczny mogą zmienić wynik.
- **F4-H3:** FP32 i INT8 mogą różnić się pod względem kompletności wykryć, dostępności Pose, poprawności wykonywanego MZ i pełnego odczytu E2E. Kierunku tej różnicy nie zakładać.

**Główna tabela do pracy:** scenariusz, wariant, rNN, `n_MT`, MT p50/p95, `n_MZ_trace`, MZ/trace p50/p95, `n_pipeline`, potok p50/p95, liczba wywołań MZ, stany źródeł i termiki. Tabela jakości osobno: `n_qual`, coverage, TP/FP/FN i F1 tam, gdzie kompletne, Pose availability i n_pose, Exact/CER tam, gdzie GTZ i wykonane MZ; `N/A` z powodem. Nigdy nie mieszać mianowników.

**Porównanie główne:** jakościowy kompromis tylko gdy zakres kwalifikowany jest adekwatny i porównywalny. Brak tego warunku oznacza **uczciwą diagnostykę**, nie wykluczenie sesji i nie dowód przewagi.

### 6.3. Warunki wniosku przyczynowego

Dla tezy „INT8 spowodowało różnicę” sprawdzić: identyczny fizyczny telefon/APK, scenariusz, checkpointy bazowe, pipeline i progi, obraz/plan ekspozycji, runtime/delegate, typ tensorów INT8, oraz różnice termiki/obciążenia. Przy ich braku formułować **opisowe** „w zarejestrowanych sesjach wariant A osiągnął …”, nie kategoryczne „sama kwantyzacja przyspieszyła cały ALPR o …”.

Różnica `n_MZ` to zmiana kosztu i/lub liczby kandydatów, nie automatycznie czysty efekt pojedynczego MZ. NIGHT obejmuje inne fotografie niż DAY; porównanie DAY↔NIGHT nie jest kontrolowanym wpływem samego oświetlenia.

### 6.4. Statystyka

- Pokazać każdy rNN (n=3 powtórzenia na wariant/scenariusz). Nie łączyć 54 śladów w 54 niezależne sceny.
- Dla czasów można raportować medianę statystyk sesyjnych i zakres między trzema sesjami. Odnotować dokładną definicję. P95 jest policzone per sesja.
- Różnice `FP32−INT8` w ms, redukcję `(FP32−INT8)/FP32·100%`, przyspieszenie `FP32/INT8` liczyć z jawnie wybranych, porównywalnych statystyk, nie z zestawu dowolnie korzystnych klatek.
- Przy wykazanej mapie scena↔scena możliwa analiza sparowana po scenach; bez tej mapy — nie używać słowa „sparowane”.
- `Exact` / `CER` różnicować w punktach procentowych; z licznikami oraz mianownikami. Nie wymyślać testów istotności przy małej liczności i skorelowanych obserwacjach. Bootstrap po scenach dopiero gdy powstanie sprawdzona mapa oraz wystarczający zakres.

## 7. F5A — koszt MP/ROI i pokrycie

- R0: MT na pełnej klatce bez MP; R1: MP i maksymalnie jeden ROI; R2: MP i do dwóch ROI. Nie nazywać różnicy R0↔R1 „samym kadrowaniem”, bo włącza również MP.
- Podać p50/p95, `n_MP`, `n_MT`, `n_MZ`, rozmiary ROI, pominięcia wynikające z wyboru ROI i koszty dodatkowych wywołań.
- **GT całej klatki** wymagane do wniosku o pokryciu; tablica poza wybranym ROI nie jest błędem pojedynczego wywołania MT, ale może być niepowodzeniem polityki ROI/systemu.
- Jeśli brak pełnoklatkowego GT, pokazać tylko koszty i pokrycie rzeczywiście przeanalizowanego ROI, z jawnym ograniczeniem. Nie dopisywać sztucznych FN.

## 8. F5B — koszt i skuteczność AutoZoom

- OFF/ON na wspólnych początkowych scenach, modelach, profilach i regule resetu. Uwzględnić również sytuacje, gdzie AutoZoom nie zadziałał.
- Pokazać rozmiar początkowy tablicy, zmianę wyników, dodatkowe wywołania, opóźnienie, no-read i przypadki poprawa / bez zmiany / pogorszenie.
- Nie wybierać tylko pozytywnych zbliżeń. Nie przedstawiać różnicy z nieweryfikowanego dopasowania scen jako czystego skutku AutoZoom.

## 9. Wybór konfiguracji i F6

- Po F4/F5A/F5B wybrać **jedną** konfigurację, opisując kompromis między skutecznością, czasem, pokryciem i pamięcią. Unikać arbitralnej sumy ważonej skonstruowanej po wynikach; pokazać rozwiązania niedominowane (Pareto), ograniczenia i uzasadnienie.
- Zapisać wersje i SHA modeli/APK, parametry wejścia, progi, delegate i metodę pomiaru. ZAMROZIĆ przed F6.
- F6 używa niezależnego, niewykorzystanego wcześniej materiału i najlepiej niezależnego GT. Nie może dobierać progów po spojrzeniu na rezultat. Raportować Exact E2E, micro-CER, odsetek no-read, p50/p95, pokrycie, błędy i PSS, **jeśli istnieje zweryfikowane źródło**.
- Jeśli nie można dowieść niezależności lub w ogóle nie wykonano F6: jawnie nazwać go brakującym ograniczeniem pracy, nie zastępować wcześniejszym EVAL396 lub F4.

## 10. Ranga wyniku w module

| Etykieta | Znaczenie |
|---|---|
| `DESCRIPTIVE` | Wyniki na wiarygodnych źródłach, ale brak pełnego potwierdzenia porównywalności/GT. Wolno opisywać różnice bez jednoznacznej atrybucji przyczynowej. |
| `ASSISTED_SUBSET` | Miara jakości na kwalifikowanym podzbiorze, z n/mianownikiem, zakresem i pochodzeniem GT. Nie stanowi pełnego wyniku sesji. |
| `CONTROLLED_COMPARISON` | Spełnione kontrole źródeł, zmiennej, scenariusza, jednostek i warunków w stopniu potrzebnym do danego twierdzenia. Ostrzeżenia nadal publikowane. |
| `INDEPENDENT_FINAL` | Tylko F6 ze sprawdzonym niezależnym materiałem i zamrożoną konfiguracją. |
| `UNAVAILABLE` | Nie istnieje dozwolony mianownik / źródło / miara. Pokazać N/A i powód. |

`APPROVED_LIMITED` pozostaje statusem ukończonej weryfikacji operatora z ograniczeniem ocenialności. **Nie awansować** tej sesji do `READY` w dotychczasowym gate jakości. Analizator może mimo to pokazać dostępne metryki lub jawne N/A.

## 11. Artefakty do pracy inżynierskiej (minimalne)

- **F4:** tabela sesji i źródeł; (1) MT i MZ/trace p50/p95 z n, (2) całe ALPR p50/p95 + n MZ, (3) pokrycie scen i no-read (jeżeli przypisanie do plansz potwierdzone), (4) dokładność wykryć i geometrii z n, (5) Exact/CER i zakres kwalifikowanych GTZ, (6) syntetyczny kompromis jakość–czas bez fikcyjnych punktów.
- **F5A:** czas/pokrycie dla R0/R1/R2, straty polityki ROI.
- **F5B:** koszt i efekt AZ OFF/ON, uwzględniający brak interwencji.
- **F6:** osobna tabela i wykres końcowego, niezależnego wyniku jednej konfiguracji.
- **Każdy wykres/CSV:** tytuł będący pytaniem badawczym, jednostka (`ms`, `%`, pp), `n`, n_missing, źródła SHA, `session_id`, wariant, scenariusz, rewizja, identyfikator algorytmu, GT-mode, warunki i uwagi. PNG/SVG i maszynowy CSV/JSON. Nie przeładowywać pracy wykresami z pól niemających związku z pytaniem.

Nie przepisujemy teraz liczb z pojedynczego screenshotu jako końcowego wniosku. Rzeczywiste agregacje i mianowniki muszą zostać odtworzone i sprawdzone z archiwów.

## 12. Niewiadome i kontrole blokujące mocne twierdzenia

- Dokładna mapa źródłowych obserwacji F4 do 18 plansz oraz zgodności scen między powtórzeniami: perceptual-hash daje dowód porządku orientacyjnego, nie ścisłe parowanie pikselowe czy timestampów granic.
- Protokół scenowego E2E F4: czas okna, wybór wyniku, jedna referencja fizyczna, no-read i związanie ze sceną — nie gotowy bez dowodów.
- Bieżący stan ocen 12 sesji (ostatnie zatwierdzenia mogły zmienić rewizje); odczytać lokalne sidecary i manifesty, **nie** traktować statusu z październikowych zrzutów jako aktualnego dowodu.
- Czy MZ jest per-call czy agregatem per-trace, czy istnieje wiarygodny PSS; brak = N/A.
- Stan F5/F6, niezależność final_test oraz bieżące bramki promotora — wymagają osobnego potwierdzenia.

## 13. Zamrożenie, audyt i zgodność z pracą

Ten dokument stanowi **kontrakt analizy v1.0 przyjęty 31.10.2026 po akwizycji F4**. Nie jest dowodem, że tak samo zaplanowano wszystkie reguły przed badaniem. Agent ma dopisać jawne `analysis_protocol_id`, wersję implementacji i różnice od starszego AKT86 do nowych eksportów, nie zmieniając starego źródła.

Zmiana protokołu po pierwszych wynikach v1.0: wyłącznie nowa wersja `1.1+`, z zakresem, powodem, testem regresji i **analizą wrażliwości na wszystkich 12 sesjach F4**. Nie usuwać historycznych eksportów ani nie przeliczać ich bez identyfikacji wersji.

Nie zmieniać `EE-dyplom.cls`, układu pracy, istniejących niezmienionych fragmentów TeX, bibliografii, oryginałów GT/MT ani kodu Android bez osobnego zadania. W przyszłej redakcji rozdziału wyników odróżnić część offline EVAL396, retrospektywną F4, testy F5 i niezależny F6.

**Źródła w pakiecie:** `07_ZRODLA_I_GRANICE.md`; same pliki źródłowe pozostają w Bibliotece użytkownika i repozytorium, nie są modyfikowane przez ten dokument.
