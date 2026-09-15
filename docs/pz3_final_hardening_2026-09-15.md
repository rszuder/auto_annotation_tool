# PZ3 / ranking — final hardening, 2026-09-15

Źródło zakresu: handoff_final_hardening_evaluation_registry.md z Pobranych.
Punkt bazowy: 9772db9, feature/evaluation-registry.
Zachowano osobne, wcześniejsze zmiany zwartego nagłówka torów.

## Zabezpieczenia

- Aktywny kontekst porównania PZ3 pozostaje aktywny po zmianie pola ścieżki.
  Selektory toru i uczestników pokazują zamrożone dane zamiast otwierać edycję.
- Start sprawdza ścieżkę względem kontekstu przed uruchomieniem silnika.
  Po zebraniu modeli sprawdzane są ponownie ścieżka i dokładny zbiór uczestników
  (bez braków, dodatkowych modeli i duplikatów). Błąd zatrzymuje proces.
- Wynik przygotowania eksperymentu musi wskazywać właściwy track_id.
  Aktywne PZ3 nie może skorzystać z wyniku legacy (None).
  Dotychczasowy bridge nadal sprawdza pieczęć i SHA zamrożonych uczestników.
- W GT PZ3 model aktywnego projektu jest dostępny jako domyślna propozycja.
  Pole i przycisk wyboru pozostają dostępne. Uruchomienie używa scope=run,
  bez adopcji MT i bez modyfikowania uczestników. Działa również niezależnie
  od pomocniczej flagi free mode; zwykłe Z2 zachowuje dotychczasowe opcje.
- Trzy collectory współdzielą helper SHA z cache lokalnym dla pojedynczego
  zbierania kandydatów. Kopie tego samego checkpointu są deduplikowane.
- Globalne (Cały Workspace) zbiera kandydatów także bez dodatkowego katalogu
  modeli i pokazuje również modele projektu. Dawne „Wszystkie” pozostaje
  jedynie obsługiwanym aliasem wejściowym normalizowanym do Globalne.

Nie zmieniono schematu registry, metryk, zasad audytu niezależności ani oświadczeń.

## Regresje i wyniki

- tests/test_pz3_final_hardening.py: 14 testów.
- tests/test_z2_gt_model_selection.py: 5 testów z rzeczywistym modalem Tk;
  walidator checkpointów w tych testach ma kontrolowane odpowiedzi.
- Wymagane pliki z handoffu oraz nowe regresje: **99 testów OK**.
- Pełny suite projektu: **623 testy OK**.
- Wyniki: output/pz3_final_hardening_test_results.json.
- Logi: output/pz3_final_hardening_targeted.log i
  output/pz3_final_hardening_full.log.
- Runner lokalny: python output/run_pz3_final_hardening_tests.py.
  Pełny suite można także uruchomić standardowo:
  python -m unittest discover -s tests -p "test_*.py".

## Smoke GUI

Polecenie: python tests/pz3_final_hardening_smoke.py.

Smoke używa tymczasowego Workspace i kopii lokalnych wag YOLO26 n/s.
Wykonał rzeczywistą preanotację na CPU: pokazał MT projektu jako propozycję,
wybrał drugi checkpoint, uruchomił proces i sprawdził SHA modelu w pierwszym
niezmiennym AUTO. Na trzech syntetycznych obrazach model nie wykrył tablic.
Roboczy GT zachował pełną pulę; dodano kontrolowane anotacje, zapisano je przez
edytor, wykonano verify oraz SEAL. Snapshot AUTO zachował swój hash.

W części rankingowej podstawiono deterministyczne predykcje. Rzeczywisty
runtime, bridge, metryki i zapis SQLite przeszły dla dokładnie dwóch
zamrożonych checkpointów. Sprawdzono blokadę obu selektorów, odmowę startu
po zmianie rank_data_dir i odrzucenie zmienionego SHA kopii checkpointu.
Dane produkcyjne ani oryginalne wagi nie były modyfikowane.

Artefakty:
- output/pz3_final_gt_project_default.png
- output/pz3_final_gt_selected_model.png
- output/pz3_final_hardening_results.png
- output/pz3_final_hardening_smoke.json

To sprawdzenie działania kontraktu aplikacji. Syntetyczny GT i deterministyczne
wyniki rankingu nie są pomiarami naukowymi. Rzeczywiste E1A nadal wymaga pełnego,
ręcznie sprawdzonego GT oraz właściwego porównania na docelowej puli.
