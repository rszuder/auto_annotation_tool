# Ranking/PZ3 — scope i lifecycle, 2026-09-15

Źródło zakresu: handoff_final_scope_lifecycle_freeze.md z Pobranych.
Punkt bazowy: bf6e534, feature/evaluation-registry.
Zachowano wcześniejszą poprawkę widoczności i komunikatów ponownego audytu.

## Zakres modeli

- Projekt korzysta z katalogu registry ograniczonego do aktywnego projektu
  oraz dotychczasowych zasobów tego projektu.
- Skan pozostałych katalogów w 9_projects działa wyłącznie dla Globalne.
- Globalne nadal obejmuje aktywny projekt, inne projekty i katalog globalny.
- Zachowano istniejący helper SHA oraz deduplikację checkpointów.

Regresje używają rzeczywistego tymczasowego registry z Project_A, Project_B
i modelem globalnym. Sprawdzają również kopię tego samego checkpointu
w projekcie i katalogu globalnym oraz działanie projektowego fallbacku
przy niedostępnym katalogu registry.

## Jawne zakończenie sesji PZ3

Okno kontrolowanego porównania ma nagłówek „Porównanie eksperymentalne PZ3”
i przycisk „Wróć do zwykłego rankingu”.

Akcja clear_pz3_comparison_context:
- odmawia podczas rankingu i kończącego się anulowania;
- czyści wyłącznie kontekst sesji i bieżący wybór toru w GUI;
- odświeża referencję, dostępność startu i wyniki;
- pozwala ponownie otworzyć zwykłe selektory toru i uczestników;
- nie zapisuje ani nie usuwa pieczęci, uczestników lub wyników eksperymentu.

Po wyjściu operator wybiera materiał do zwykłego rankingu od nowa.
Zamknięcie okna wyników, odświeżenie, błąd, anulowanie i ukończenie obliczeń
nie czyszczą kontekstu automatycznie. Można powtórzyć ten sam kontrolowany
eksperyment albo jawnie wyjść i otworzyć inny tor PZ3.

Nie zmieniono validate_comparison_context, bridge, schematu registry,
protokołu, metryk ani wyboru modelu preanotacji.

## Walidacja

- Nowe regresje: tests/test_ranking_scope_lifecycle.py — 10 testów OK.
- Wymagany zestaw z handoffu wraz z nowymi regresjami: 78 testów OK.
- Pełny suite: 634 testy OK.
- Logi i wyniki: output/pz3_scope_lifecycle_test_results.json,
  output/pz3_scope_lifecycle_targeted.log, output/pz3_scope_lifecycle_full.log.
- Runner lokalny: python output/run_pz3_scope_lifecycle_tests.py.
- Standardowy pełny suite: python -m unittest discover -s tests -p "test_*.py".

Istniejący python tests/pz3_final_hardening_smoke.py przeszedł z rozszerzeniem
tests/pz3_scope_lifecycle_probe.py. Sprawdzono GT, SEAL, kontrolowany ranking,
jego powtórzenie, zamknięcie i ponowne otwarcie okna, odmowę wyjścia w trakcie
obliczeń, jawne wyjście, oba zwykłe selektory oraz wejście do zapieczętowanego
toru B. Tor A zachował pieczęć, uczestników i wszystkie cztery wyniki dwóch
uruchomień; tor B pokazał własny kontekst i uczestników oczekujących na test.

Smoke działa w tymczasowym Workspace: rzeczywista preanotacja na CPU,
syntetyczna pula/GT oraz deterministyczne predykcje w części rankingowej.
Te wyniki nie są pomiarami do pracy dyplomowej.

Artefakty: output/pz3_scope_lifecycle_smoke.json oraz zrzuty
pz3_scope_lifecycle_controlled.png, pz3_scope_lifecycle_regular.png
i pz3_scope_lifecycle_track_b.png w katalogu output.
