# Rola analizy modeli w PZ2 i eksperymentu w PZ3

Punkt odniesienia: `4b8685c`.

PZ2 zachowuje trening, historię, analizę roboczą, wykresy i raporty.
Dawna zakładka Ranking nosi stabilną nazwę **Analiza modeli**.

PZ3 pozostaje miejscem definiowania kontrolowanego eksperymentu:
participants → audit → RAW sample selection → GT → VERIFY → SEAL → Porównaj modele.

## Dwa tryby

Bez `comparison_context()` PZ2 pokazuje „Analiza robocza modeli”,
„Tryb roboczy — bez pieczęci PZ3”, „Źródło analizy roboczej” i „Modele do analizy”.
CTA „Otwórz Tory testowe PZ3” buduje leniwie istniejącą kartę PZ3 i wybiera ją
w notebooku Z4. Nie otwiera kolejnego okna i nie zmienia typu modeli.

W kontekście PZ3 nagłówek pokazuje eksperyment kontrolowany, CONTROLLED / SEALED,
nazwę i ID toru, liczbę obrazów oraz uczestników. Dotychczasowe blokady toru,
modeli, SHA, reference i opcji zaawansowanych pozostają aktywne.

Zamknięcie okna wyników nie kasuje kontekstu. Jawny przycisk
„Wróć do analizy roboczej” korzysta z istniejącego mechanizmu wyjścia,
w tym blokady podczas pracy lub kończenia anulowania.

## Uruchomienie i raporty

Analiza robocza nadal używa dotychczasowego silnika. Nie wywołuje
`RankingExperimentBridge.prepare()`, także gdy wskazano źródło SEALED.
Nie powstaje wówczas nowy rekord controlled experiment.

Przy aktywnym kontekście PZ3 przygotowanie eksperymentu, guardy i zapis wyników
działają dotychczasowym torem. Bridge i backend rankingu pozostają bez zmian.

Raport roboczy (Markdown i tytuły wykresów SVG) nosi oznaczenie „Analiza robocza”.
Raport kontrolowany zawiera tryb, tor, zamrożonych uczestników, reference,
SHA modeli, manifestu i protokołu oraz metryki. Pobiera wyłącznie wpisy
kontrolowane pasujące do toru i modeli kontekstu. Wpisy robocze na tym samym
źródle nie są przejmowane do raportu PZ3.

Historyczne statusy dowodów pozostają zapisane przy poszczególnych wynikach.
Przegląd historycznych wyników w PZ2 nie tworzy nowego eksperymentu.

## Granice zmiany

Nie zmieniono formatu ranking entries, ranking score, F1, precision, recall, mAP,
corner metrics, wyznaczania evidence status, comparison bridge, SEAL,
participant audit, GT ani selekcji RAW. Nazwy wewnętrzne rank_* pozostały.

Istniejące wyniki PZ3 można nadal przeglądać i raportować przez kontekst PZ3.
Osobna sekcja listująca ostatnie eksperymenty w PZ2 pozostaje opcjonalnym
rozszerzeniem interfejsu; nie jest wymagana do rozdzielenia trybów.

## Weryfikacja — 2026-09-16

- Regresja tego zakresu: 49 testów PASS, 12 subtests.
- Pełne unittest discover: 723 testy OK.
- Dodatkowe testy Z2: 64 OK. Po sporadycznym błędzie inicjalizacji Tcl
  63 testy przeszły w zestawie, a pozostały test potwierdzono w osobnym procesie.
- pz3_final_hardening_smoke.py: PASS.
- pz3_sample_review_smoke.py: PASS.
- Rzeczywiste GUI: etykieta karty, banner roboczy, routing PZ2 → PZ3,
  nagłówek CONTROLLED / SEALED, jawne wyjście z kontekstu i widoczność
  przycisków Zaawansowane / Anuluj bez obcinania.
- Kontrola hashy całego backendu ranking oraz chronionych modułów
  PZ3 lifecycle / GT / audit / RAW: identyczne względem początku zadania.
- git diff --check: bez błędów.

Smokes działają na izolowanych danych i używają deterministycznych predykcji
do sprawdzenia zapisu wyników. Ich metryki nie są wynikiem rzeczywistego
eksperymentu MT-n vs MT-s.
