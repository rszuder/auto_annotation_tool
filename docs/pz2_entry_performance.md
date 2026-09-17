# Szybsze wejście do Z4/PZ2

Profilowanie lokalnego Workspace wykazało, że podczas budowania PZ2 zbierano listę
modeli dziewięć razy. Ponownie liczono SHA checkpointów, choć „Analiza modeli”
nie była jeszcze otwarta. Haszowanie zajęło 12,16 s z 14,12 s budowania panelu.

## Zmiana

- Dane analizy odświeżają się po otwarciu jej zakładki lub okna wyników.
  Otwarcie PZ2 z historią treningu nie odczytuje zawartości modeli analizy.
- Zmiana targetu nie uruchamia zagnieżdżonych odświeżeń przez trace StringVar.
- Cache SHA służy deduplikacji listy GUI. Jest wspólny dla kolektorów tego samego
  okna i ograniczony do 512 wpisów. Sprawdza urządzenie, tożsamość pliku, rozmiar,
  mtime_ns i ctime_ns. Zmiana/podmiana usuwa poprzedni wynik.
- Nie zapamiętuje błędów odczytu ani plików zmienionych w trakcie odczytu.
  Katalog i lista ścieżek nadal są odczytywane na nowo — dodane/usunięte modele
  nie znikają za cache listy.
- Bezpośrednie pierwsze wejście z PZ3 zachowuje zamrożone źródło; synchronizacja
  targetu nie resetuje ścieżki controlled reference.
- Kontrolowane porównanie pobiera modele z kontekstu PZ3, omijając cache listy GUI.
  Backendowe sprawdzanie SHA, pieczęci i uczestników pozostaje bez zmian.

## Pomiar lokalny

Ten sam lokalny Workspace, osobne procesy, cProfile; zapis sesji/historii wyłączony.
Globalny asynchroniczny skan urządzeń pominięty w obu pomiarach. Dataset treningu
nie był wybrany. Pomiar obejmuje rzeczywiste pliki modeli i historię.

| Etap | Przed | Po |
|---|---:|---:|
| Budowa PZ2 | 14,12 s | 0,73 s |
| Pierwsze wyświetlenie po budowie | 0,80 s | 0,94 s |
| Łącznie pierwsze wejście | 14,92 s | 1,67 s |
| Pierwsze otwarcie Analizy modeli | — | 2,15 s |
| Powrót do Analizy modeli | — | 0,42 s |

Pomiar wyświetlenia zawiera okno obsługi zdarzeń o minimum 0,3 s.
To lokalny pomiar, zależny od liczby checkpointów i dysku.
Artefakty: output/pz2_entry_before*.pstats, output/pz2_entry_after*.pstats,
output/pz2_entry_before.json i output/pz2_entry_after.json.

## Testy

Regresja celowana: 64 testy i 12 podtestów PASS.
Obejmuje odroczone odświeżanie, rzeczywisty notebook Tk, bezpośrednie wejście
controlled, zmianę pliku tej samej długości, podmianę z zachowanym mtime,
usunięcie/ponowne utworzenie, błędy odczytu, zmianę w trakcie haszowania,
deduplikację kopii i izolację zakresu Projekt/Globalne.

Pełna weryfikacja po zmianie:
- unittest discover: **751 testów OK**;
- dodatkowe testy Z2: **64 PASS**;
- smoke GUI analizy roboczej i kontrolowanej: **PASS**;
- pz3_final_hardening_smoke.py: **PASS**;
- pz3_sample_review_smoke.py: **PASS**;
- 36 plików backendu/RAW/GT/comparison: SHA-256 bez zmian;
- git diff --check: bez błędów.

Wyniki: output/pz2_entry_results.json i output/pz2_entry_final_*.log.
Scenariusze smoke używają izolowanych danych; nie są pomiarem jakości modeli.
