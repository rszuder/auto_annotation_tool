# Zgodność istniejącego GT z bieżącą pulą

Handoff: `handoff_existing_gt_membership_hardening.md`.
Punkt odniesienia: `e174f748d310bc5fe0d8c3ef909a5e5e588a8598`.

Wyjątek dla istniejącego Ground Truth przy formalnych eksperymentach plate
wymaga teraz jednocześnie poprawnego SHA oraz zgodności CVAT XML z aktualnymi
członkami toru. Nazwy `image/@name` są porównywane po `Path(name).name`.
Lista musi być niepusta, bez powtórzeń i odpowiadać dokładnie `original_name`
każdego członka. Uszkodzony XML, brak nazwy, brakujący lub dodatkowy obraz
wyłączają wyjątek. SHA i XML sprawdzane są na tych samych odczytanych bajtach.

Przy dodaniu obrazu, zarówno pojedynczo, jak i paczką, rejestr zeruje
`gt_format`, `gt_relative_path`, `gt_sha256`, `object_count` i `verified_at`.
Dzieje się to w tej samej transakcji SQLite co dodanie członków i aktualizacja
ich liczby. Błąd zatwierdzenia cofa oba skutki. Pusta paczka lub odrzucony
duplikat zachowują dotychczasowy GT.

Poprzedni XML pozostaje na dysku, ale przestaje być aktywnym GT w rejestrze
i nowym manifeście. Nie jest przenoszony ani usuwany przez operację dodawania.
Nawet błąd późniejszego zapisu manifestu nie przywraca go jako aktywnego GT.

Sprawdzenie XML działa również dla niespójnych danych ze starszego Workspace,
niezależnie od unieważniania GT przy nowych operacjach. Poprawny GT przy
niezmienionej puli pozostaje dostępny do korekty bez ponownego wyboru próby.

Regresja formalnego flow obejmuje: istniejący GT → dodanie obrazu →
unieważnienie GT → audyt szerokiej puli → zatwierdzenie próby → STALE →
ponowny audyt → CURRENT → nowe GT. Nie zmieniono silnika audytu, lineage,
fingerprintów, schematu próby, VERIFY, SEAL ani mechanizmów rankingu.

Testy:
- `tests/test_existing_gt_membership.py`: 15 przypadków (w tym warianty
  nazw, błędny XML, rollback obu ścieżek dodawania i błąd manifestu);
- poprzednie testy `test_final_sample_gt_gating.py` i regresje dodawania:
  łącznie 43 testy zakończone poprawnie;
- pełny wynik i scenariusze GUI:
  `output/existing_gt_membership_full_suite.log`,
  `output/existing_gt_membership_sample_smoke.log`,
  `output/existing_gt_membership_hardening_smoke.log`.

Weryfikacja końcowa (2026-09-17):
- pełny unittest: **806 testów, OK**;
- `pz3_sample_review_smoke.py`: **PASS**;
- `pz3_final_hardening_smoke.py`: **PASS**, łącznie z cyklem zmiany toru;
- `git diff --check`: **PASS**.

Scenariusze GUI działały w tymczasowych Workspace. Korzystały z rzeczywistej
preanotacji na CPU oraz deterministycznych predykcji testowych rankingu;
nie są pomiarem wyników rzeczywistego eksperymentu.

Odczyt rzeczywistego Workspace, bez zmian w jego rejestrze: tor
`TRK-3CB60B7B61384A08A1F6`, DRAFT, 9908 obrazów, zapisany audyt CURRENT,
brak aktywnego GT i brak zatwierdzonej próby. Kolejny krok: wybór finalnej
próby. Wynik odczytu: `output/existing_gt_membership_live_readonly_audit.json`.
