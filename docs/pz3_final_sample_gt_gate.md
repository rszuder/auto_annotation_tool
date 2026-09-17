# PZ3: GT dopiero po finalnej próbie i ponownym audycie

Zmiana względem `1279475f23017f5808ef563dbb755d991413c45c`, zgodnie z
`handoff_block_gt_until_final_sample_reaudit.md`.

Dla DRAFT typu `ranking` / `final_test` i targetu `plate` przygotowanie
oraz import nowego GT wymagają:

- zapisanego `sample_selection.json` należącego do tego toru,
- niepustego składu, którego SHA są podzbiorem zapisanej próby,
- aktualnego audytu `CURRENT` tej puli.

Zatwierdzenie próby unieważnia audyt istniejącym mechanizmem, również jeśli
operator wybierze całą pulę. Ponowny audyt jest zatem obowiązkowy.

Wspólna polityka znajduje się w
`auto_annotation_tool/registry/final_sample_policy.py`.
Dotychczasowy `has_selected_sample` został przeniesiony do warstwy rejestru
i pozostaje dostępny przez import w `pz3_workflow_view.py`.

Kontrola działa w stanie obu przycisków PZ3, w metodach otwierania Z2 i importu
XML, w samym `prepare_gt_workspace`, w `EvaluationTrackService.set_ground_truth`
oraz przy wejściu do kontekstu GT w Z2. Odrzucenie następuje przed tworzeniem
roboczego XML, kopiowaniem GT lub otwarciem okna wyboru pliku.

Istniejący zarejestrowany GT zachowuje ścieżkę edycji bez ponownego wyboru próby;
plik musi istnieć i odpowiadać zapisanemu SHA. XML musi też zawierać dokładnie aktualne obrazy, bez duplikatów nazw. Sama ścieżka w rejestrze nie
wystarcza. Walidacja, znaki i pojazdy zachowują dotychczasowe warunki wejścia.

Schemat wyboru próby, silnik audytu, rejestrowanie próby, kontrakt obrazów GT,
VERIFY, SEAL oraz ranking pozostają bez zmian. Nie dodano nowego stanu trwałego.

Testy `tests/test_final_sample_gt_gating.py` obejmują GUI, bezpośrednie
wywołania usług, wybór całej puli, ponowny audyt, import XML, istniejący GT,
zgubiony / zmieniony GT, niepoprawny plik wyboru, usunięcie obrazu z próby
oraz dodanie obrazu spoza próby. Fixture formalnych eksperymentów używają
rzeczywistego zatwierdzania i audytu próby.

Weryfikacja końcowa jest zapisywana w:
- `output/final_sample_gt_full_suite.log`,
- `output/final_sample_gt_sample_smoke.log`,
- `output/final_sample_gt_hardening_smoke.log`.

Wynik weryfikacji (2026-09-17):
- pełne `python -m unittest discover -s tests -p "test_*.py"`: **791 testów, OK**;
- w tym **19 nowych testów** blokady GT;
- `pz3_sample_review_smoke.py`: **PASS** — oba przyciski GT wyłączone przed wyborem i po commit, aktywne po re-audycie; 20 kandydatów → 6 obrazów → GT → VERIFY → SEAL → porównanie;
- `pz3_final_hardening_smoke.py`: **PASS**, także cykl przełączania zapieczętowanych torów;
- `git diff --check`: **PASS**.

Scenariusze GUI używały tymczasowych Workspace. Preanotacja korzystała z lokalnych
modeli na CPU, a ranking z deterministycznych predykcji testowych. Nie są to wyniki
pomiarów eksperymentu badawczego. Poprawiono też raportowanie wyjątków i zamykanie
interpretera Tk w tych skryptach, aby błąd scenariusza nie pozostawiał zawieszonego procesu.
