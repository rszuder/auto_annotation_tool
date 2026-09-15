# PZ3 — wdrożenie audytu UX v2

Data zakończenia: 2026-09-15.
Specyfikacja: PZ3_AUDIT_UX_REFACTOR_HANDOFF_2026-09-14_v2.md.
Branch: feature/evaluation-registry.

## Zachowanie

Audyt jest jednym miejscem diagnozy i decyzji. Tabela pozostaje widoczna podczas
rozstrzygania każdego obrazu wymagającego weryfikacji. Po jej zamknięciu caller
wykonuje AuditResolution i pokazuje jedynie krótkie podsumowanie operacji.

Okno zawiera cztery liczniki, filtry, status i decyzję dla każdego pliku,
szczegóły modelu/runu/datasetu/splitu, odległość pHash i ścieżkę referencji.
Podglądy pokazują obraz z puli i referencję wybranego modelu. W szczegółach
pierwszy jest model powodujący problem.

Decyzje:
- CLEAN jest dopuszczony.
- DEPENDENT i UNKNOWN są wykluczone bez możliwości ręcznej akceptacji.
- SUSPECT wymaga indywidualnej akceptacji albo odrzucenia.
- „Odrzuć wszystkie wymagające weryfikacji” działa w tym samym oknie.
- „Cofnij decyzję” przywraca stan nierozstrzygnięty.
- Przycisk zastosowania jest nieaktywny, dopóki pozostaje nierozstrzygnięty SUSPECT.
- Anulowanie, także po dokonaniu wyborów, nie zmienia członków ani nie zapisuje CURRENT.

## Dwa przepływy

**Dodaj obrazy:** diagnoza obejmuje nowych kandydatów po kontroli duplikatów.
Przycisk pokazuje liczbę obrazów do dodania. Aktualny wcześniejszy audyt może
zostać rozszerzony o nowe zaakceptowane SHA. Jeśli wcześniejsza pula wymaga
audytu, nowe czyste obrazy nadal są dodawane, a stan całej puli pozostaje STALE.

**Audytuj pulę:** diagnoza obejmuje wszystkich obecnych członków, również
brakujące pliki oznaczane jako UNKNOWN. Zapis wyniku usuwa odrzucone kopie
z DRAFT-u przez dotychczasową usługę. Liczba usuwanych obrazów i wpływ na GT
są widoczne przed zatwierdzeniem w oknie. Oryginalne pliki źródłowe pozostają.

Dla VERIFIED dozwolony jest ponowny audyt zachowanej puli. Zmiana składu
zweryfikowanego toru jest blokowana; okno wyjaśnia potrzebę przygotowania nowego DRAFT-u.

Nagłówek i szczegóły PZ3 pokazują trwały stan audytu, liczbę modeli i obrazów,
liczbę ręcznych akceptacji oraz czas audytu. Układ kart i kontrolek użytkownika
zachowano; informacje dodano do istniejącego obszaru podsumowania.
Przycisk SEAL oraz dotychczasowy guard respektują aktualność audytu.

## SQLite i spójność

[Mapa źródeł danych, writerów i readerów](pz3_audit_sources_2026-09-14.md)
została przygotowana przed zmianą dialogu i ingestu.

Standardowa inicjalizacja RegistryDatabase wykonuje addytywną migrację 3 → 4:
- evaluation_track_audits — zastosowane diagnozy, tryb, fingerprinty i czas;
- evaluation_track_audit_decisions — akcja operatora, ścieżka, SHA i status per obraz;
- evaluation_track_audit_state — kanoniczny CURRENT/STALE i stan pokrycia puli.

Raport, decyzje i stan są zapisywane wspólnie w transakcji. FK wiążą audyt
z torem, a decyzje z audytem. Istniejące relacje modeli i eksperymentów pozostają.

Dotychczasowy JSON stanu jest importowany jednokierunkowo tylko wtedy, gdy
SQLite nie ma jeszcze stanu danego toru. Dalsze odczyty i zapisy korzystają
z bazy; stary plik nie jest drugim, aktualizowanym rejestrem.

participants.json pozostaje artefaktem uczestników toru. To osobny zakres niż
experiment_participants, opisujący uczestników zapisanego eksperymentu.
Źródłem relacji model → run → dataset → train/val i ancestry nadal jest SQLite.

Przed zastosowaniem sprawdzany jest snapshot uczestników i członków.
Zmiana członków, także pojedyncze add_member, unieważnia audyt w SQLite.
Błąd zapisu decyzji po modyfikacji członków pozostawia STALE i jest zgłaszany
jako błąd wykonania, bez komunikatu sukcesu.

Przed nadaniem CURRENT sprawdzana jest zgodność manifestu z członkami SQLite.
Ponowny audyt odtwarza manifest, jeśli wcześniejszy ingest zakończył się błędem
jego zapisu już po zatwierdzeniu rekordów. Prawidłowy manifest nie jest zapisywany drugi raz.

## Walidacja

**Pełny suite: 592 testy OK** (stan przed tym etapem: 562).
Dodatkowo osobno:
- test_pz3_*.py: 77 OK;
- test_evaluation_*.py: 46 OK;
- test_participant_*.py: 26 OK;
- test_source_filename*.py: 20 OK;
- kontrola okna po dopracowaniu zawijania tekstu: 6 OK;
- git diff --check: OK.

Sprawdzono resolution A–I z handoffu, dokładnie 11 ścieżek przekazanych do
batch ingest dla mieszanego zestawu 17 obrazów, anulowanie, brak pliku,
archiwizację GT, rollback transakcji decyzji, trwałość po ponownym otwarciu bazy,
jednokierunkowy import JSON, migrację istniejącej bazy v3, FK i odzyskanie manifestu.

Smoke na rzeczywistych widgetach Tk:
5 CLEAN + 2 DEPENDENT + 2 SUSPECT + 1 UNKNOWN.
Zaakceptowano jeden SUSPECT, drugi odrzucono w oknie.
Wynik: 10 wierszy diagnozy, 6 przyjętych obrazów, 6 wierszy w PZ3,
10 zapisanych decyzji w SQLite, CURRENT i 1 ręczna akceptacja w nagłówku.
Nie pojawiło się żadne dodatkowe pytanie decyzyjne po zamknięciu audytu.

Scenariusz smoke jest wykonywany automatycznie przez kontrolowany fixture,
a zrzuty sprawdzono wizualnie. Dotyczy działania GUI i przepływu danych;
nie jest oceną jakości anotacji ani modeli.

Zrzuty:
- ../output/pz3_ux_audit_initial.png
- ../output/pz3_ux_audit_resolved.png
- ../output/pz3_ux_panel_current.png

Pełne logi są w output/pz3_verify_1.log … output/pz3_verify_5.log.
Pełny suite nadal emituje wcześniejsze komunikaty Tk z testów istniejących
przed tym etapem; nowe testy okna sprawdzają również błędy callbacków.

## Benchmark końcowy

Kontrolowany, tymczasowy rejestr: 2 uczestników testowych i 1000 rzeczywistych
obrazów referencyjnych. Wejście: 1000 zdjęć z sample_1000, 233 416 557 bajtów.
Jest to test wydajności na rzeczywistych plikach z metadanymi modeli testowych;
nie stanowi oceny rzeczywistych modeli użytkownika.

| Pomiar | Pierwszy import | Ponowne dodanie |
| --- | ---: | ---: |
| Czas całej operacji | 15,86 s | 2,46 s |
| Dodane rekordy | 769 | 0 |
| Wiersze po operacji | 769 | 769 |
| Czas audytu | 5,74 s | 1,13 s |
| Największy odstęp zdarzeń kontrolnych Tk | 0,206 s | 0,237 s |
| Nowe obliczenia SHA w audycie | 0, po preflight | 0 |
| Nowe obliczenia pHash | 1882 | 0 |
| Zapisy manifestu podczas ingestu | 1 | 0 |

W pierwszym wyborze pominięto 20 duplikatów, 98 obrazów zależnych i 113
wymagających weryfikacji. Dodano wszystkie 769 CLEAN.
Przy ponownym dodaniu audyt objął tylko 211 ponownie wybranych, wcześniej
odrzuconych kandydatów; 769 członków rozpoznano podczas preflightu.

Szczegóły: ../output/pz3_ux_benchmark_report.json.

## Odtworzenie

~~~powershell
python -m unittest discover -s tests -p "test_*.py"
python tests/pz3_audit_ux_smoke.py
python tests/pz3_benchmark.py --output output/pz3_ux_benchmark_report.json
git diff --check
~~~

Po ponownym uruchomieniu aplikacji dostępny jest nowy dialog, a standardowa
inicjalizacja rejestru stosuje migrację SQLite.

