# Audyt bramek i wejścia T02 → Z2 — 2026-09-07

Zgłoszenie doprecyzowane podczas pracy: **T02 z bieżącego grafu**. Projekt `demo_6D564A` ma aktywną iterację 3, etap E1 i ścieżkę `char_from_ready_plates`. Pula projektu zawiera 13 obrazów i 14 zatwierdzonych tablic. Nie ma ręcznie wskazanego importu AT na wejściu tej iteracji.

## Przyczyny i poprawki

1. Nawigacja T02 wymagała pola importu AT, choć kontrakt bramki dopuszcza tablice z poprzednich iteracji. Teraz używa wskazanego źródła, zapisanej kontroli bieżącej iteracji albo tworzy roboczy zestaw z zatwierdzonej puli projektu. Zestaw jest zachowywany przy ponownym wejściu. Uszkodzony wskazany import zgłasza błąd; nie jest zastępowany innym źródłem.
2. Wykonawca grafu uznawał samo wywołanie funkcji nawigacji za sukces. Nadpisywał ostrzeżenie o braku źródła i zapisywał nieprawdziwy sukces w historii. Nawigacja zwraca teraz wynik blokady albo stan oczekiwania, a końcowy wynik zapisuje po rzeczywistym przełączeniu do Z2. Błąd wejścia, brak przełączenia, zmiana projektu lub iteracji są raportowane jako niepowodzenie. Ponawianie ładowania ma limit.
3. Filtr listy Z2 ponownie ukrywał pozycje zatwierdzone w projekcie, mimo że odtwarzanie T02 prawidłowo wczytywało wszystkie anotacje. Kontrola T02 pokazuje także tę pulę. Sprawdzone na liście 13 obrazów / 14 tablic.
4. Kontrola T02 nie potrzebuje odtwarzania roboczego źródła E2 i jego poprzedniej sesji. Pominięto te operacje i zachowano obrazy należące do kontrolowanego AT. Wejście z gotowym modułem Z2 do pełnej listy w testach zajęło około 2,8–3,7 s; nie jest to pomiar całego startu aplikacji.
5. Modal Praca T02 zamyka poprzednie okna grafu i zwalnia ich przechwycenie wejścia przed nawigacją.
6. Zatwierdzanie bramek mogło raportować sukces po anulowaniu, wyjątku przechwyconym przez backend lub braku zmiany stanu. Wykonawca sprawdza aktywny etap i ścieżkę przed akcją, a po niej docelowy etap oraz status zatwierdzenia. Historia zachowuje iterację źródłową, także gdy T06 uruchamia następną iterację.
7. Ocena ukończenia bramki nie uwzględniała wszystkich ograniczeń ścieżek. T01 nie jest ukończona na skrócie T02, T03 i T04 nie zatwierdzają się wzajemnie, a T05 nie należy do toru tablic. Same zachowane zasoby nie odblokowują przyszłego etapu nowej iteracji.
8. Ujednolicono identyfikację T03/T04 w zatwierdzaniu E2 według krawędzi grafu i poprawiono komunikaty T02. Zatwierdzanie E2 z zimnego grafu ładuje rzeczywisty moduł Z2 zamiast wywoływać puste funkcje zastępcze.

## Sprawdzone scenariusze

| Bramka / sytuacja | Oczekiwany wynik |
| --- | --- |
| T01, tor tablic albo znaków ze zdjęć | Potwierdzenie prowadzi E1 → E2; anulowanie nie zatwierdza bramki |
| T02, gotowa pula projektu | Kontrola w Z2, zapis i powrót pozostawiają E1; jawne zatwierdzenie prowadzi E1 → E3 |
| T02, import, brak źródła, brak XML lub obrazów | Właściwe źródło ma pierwszeństwo; brak jest zgłaszany bez sukcesu w historii |
| T02, ponowne wejście | Ten sam roboczy zestaw, pełna lista, bez utraty przechwycenia myszy przez modal |
| T03 / T04 | Odpowiednio E2 → E3 lub E2 → E4T; niewłaściwa ścieżka nie wywołuje zatwierdzenia |
| T05 | E3 → E4Z tylko na torach znaków |
| T06, trening albo pominięcie | Decyzja musi odpowiadać bieżącej iteracji i celowi; anulowanie nie zamyka iteracji |
| Wyjątek lub funkcja bez zmiany stanu | Brak fałszywego zatwierdzenia i sukcesu w historii |
| Zachowane zasoby w iteracjach 1–3 | Nie odblokowują przyszłych etapów przed dojściem do nich |

Testy kontraktów wykonawcy obejmują wszystkie bramki i wyniki: zatwierdzenie, anulowanie, brak działania oraz wyjątek. Dodatkowo sprawdzono rzeczywistą funkcję zatwierdzania T02, kontrolę aktualności decyzji T06, regresje Z2/Z3 i historii. Nie jest to pełny test GUI wszystkich treningów i eksportów.

## Walidacja

- `test_campaign_gate_state_machine.py`, `test_campaign_entry_resource_selection.py`, `test_campaign_graph_presentation.py`, `test_project_history_resources.py`: **121 testów, 13 podtestów**.
- `test_z2_auto_result_list.py`, `test_z2_free_entry_runtime.py`, `test_z3_entry_runtime.py`, `test_z3_rows_and_t05_return.py`: **95 testów, 4 podtesty**.
- `python -m auto_annotation_tool.campaign_graph_sanity`: **OK — 7 krawędzi, 6 specyfikacji, 3 ścieżki**.
- Natywna próba `output/demo_t02_gate_probe.py`: produkcyjny modal Praca T02 → Z2 → zapis i powrót → ponowne wejście. Pełna lista 13/14, brak pozostawionego grab, pula nadal 13/14, etap nadal E1 przed osobnym zatwierdzeniem. Wynik: `output/demo_t02_gate_probe/results.json`, `errors: []`.

Test okna odczytywał dane demo, ale zapisy kampanii przechwytywał w pamięci, a zapis plików ograniczał do katalogu testowego `output`. Nie cofano iteracji projektu ani nie zmieniano historycznych zdarzeń. Wcześniejsze błędne wpisy sukcesu w historii pozostają śladem starego zachowania.
