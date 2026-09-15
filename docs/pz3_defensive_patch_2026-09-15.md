# PZ3/ranking — defensywne domknięcie, 2026-09-15

Źródło: handoff_final_defensive_patch_before_freeze.md z Pobranych.
Stan bazowy: 0e1bc31, feature/evaluation-registry.

## Wdrożone zabezpieczenia

- Projektowy collector dołącza self.history wyłącznie wtedy, gdy jej katalog
  po resolve należy do 5_training_runs aktywnego projektu. Obsługiwane są
  również podkatalogi targetów, np. plates. Historia globalna, innego
  projektu lub o nieustalonej przynależności jest pomijana.
- W kontrolowanym PZ3 przycisk „Zaawansowane” jest ukryty.
  Bezpośrednie wywołanie edytora jest blokowane komunikatem o pieczęci.
  Ten sam warunek sprawdzany jest przed zastosowaniem źródeł, więc również
  okno otwarte wcześniej w zwykłym rankingu nie podmieni aktywnego toru PZ3.
- open_comparison odmawia wejścia podczas obliczeń oraz przy
  rank_cancel_requested=True. Odmowa następuje przed resolve_comparison;
  bieżący kontekst i ścieżka toru pozostają zachowane. Po zakończeniu
  anulowania można otworzyć drugi tor.

Zachowano walidację toru i dokładnego zbioru modeli, ponowne sprawdzanie SHA,
bridge, protokół, metryki, jawne wyjście PZ3 oraz preanotację GT.

## Weryfikacja

- tests/test_ranking_scope_lifecycle.py: 17 testów OK, w tym 7 nowych regresji.
- Wymagane pliki z handoffu: 70 testów OK.
- Pełny suite: 641 testów OK.
- Wyniki: output/pz3_defensive_patch_test_results.json.
- Logi: output/pz3_defensive_patch_targeted.log i
  output/pz3_defensive_patch_full.log.
- Runner lokalny: python output/run_pz3_defensive_patch_tests.py.
- Pełny suite: python -m unittest discover -s tests -p "test_*.py".

Smoke python tests/pz3_final_hardening_smoke.py wraz z istniejącym
pz3_scope_lifecycle_probe przeszedł. Oprócz GT → SEAL → ranking potwierdził:
ukrycie i bezpośrednią blokadę Zaawansowane, blokadę zapisu ze starego okna,
odmowę re-entry w stanie kończącego się cancel, powtórzenie porównania,
jawne wyjście do zwykłego rankingu oraz późniejsze wejście do toru B.
Pieczęć i wyniki toru A pozostały zachowane.

Smoke korzysta z tymczasowego Workspace, kopii lokalnych wag do preanotacji
na CPU, syntetycznej puli/GT i deterministycznych predykcji rankingu.
Nie są to wyniki eksperymentu do pracy dyplomowej.

Artefakty: output/pz3_scope_lifecycle_smoke.json oraz zrzuty
pz3_scope_lifecycle_controlled.png, pz3_scope_lifecycle_regular.png
i pz3_scope_lifecycle_track_b.png w katalogu output.
