# PZ3 — kontrola nazw i powtarzalność audytu po usunięciu draftu

Okno kontroli nazw pokazuje tylko pliki niespełniające formatu nazwy.
Liczba takich plików jest niezależna od liczby podejrzeń audytu train/val.
W aktualnym flow po imporcie audyt uruchamia się przyciskiem
„Sprawdź niezależność puli” (po wyborze próby: „Sprawdź finalną próbę”).

Zapis kontroli nazw zmienia pliki źródłowe: poprawia nazwy lub przenosi odrzucone
pliki do sąsiedniego katalogu __odrzucone_nazwy. Usunięcie draftu nie cofa tych
zmian. Audyt usuwa odrzucone obrazy z kopii w torze; oryginały pozostają.

## Zmiana UI

- Nagłówek PZ3: „Kontrola nazw plików”, kolumna „Problem z nazwą” i licznik
  „nazwy do poprawy”.
- Jasne wskazanie następnego, oddzielnego kroku sprawdzania niezależności.
- Wybór źródła opisuje kolejność: nazwy → dodanie → jawny audyt.
- Okna są budowane ukryte, następnie przywracane, podnoszone i aktywowane.
  Zachowują zwykłe systemowe kontrolki okna.
- Zamknięcie/zapis przywraca wcześniejszy modal grab rodzica, także przy przejściu
  z wyboru katalogu do kontroli nazw.
- Komunikaty audytu używają aktualnych nazw przycisków.

## Regresja

Test odtwarza: te same modele → pełna pula → audyt → odrzucenie podejrzanych →
usunięcie draftu → nowy draft → pełna oryginalna pula → ponowny audyt.
Porównuje wszystkie werdykty, SHA, pHash i dowody względem każdego modelu.
Odrzucone podejrzane obrazy ponownie wymagają decyzji. Cache i odczyt bez cache
dają takie same wyniki. Oryginały zachowują zawartość.

Osobny przypadek ma jedną błędną nazwę i czternaście podejrzanych obrazów.
Korekta tej nazwy usuwa ją z listy nazw, zachowując czternaście podejrzeń audytu.

Nowe testy: test_pz3_recreated_draft_audit.py i testy okien w test_pz3_dialog_interactions.py.
Scenariusz 10 000 obrazów: output/pz3_repeat_10000.py, wyłącznie dane syntetyczne.
Backend audytu, usuwania draftu i cache fingerprintów pozostaje bez zmian.

## Wyniki — 2026-09-16

- Scenariusz 10 000 syntetycznych obrazów: **PASS**. Przed usunięciem i po
  odtworzeniu: 9984 bez zależności, 14 do decyzji, 1 zależny, 1 nieczytelny.
  Wszystkie werdykty i dowody identyczne także po wymuszeniu odczytu bez cache.
- Pełny unittest discover: **756 testów OK**, bez pominiętych testów.
- Dodatkowe testy Z2: **64 PASS**.
- Smoke audytu i okna kontroli nazw: **PASS**.
- Kontrola GUI: normalne otwarcie, przywrócenie po minimalizacji, fokus,
  przywrócenie grab rodzica po anulowaniu/zapisie, czytelne objaśnienia.
- Backend registry/ranking: pliki identyczne z początkiem zadania.
- git diff --check: bez błędów.

Artefakty lokalne: output/pz3_repeat_10000_result.json,
output/pz3_repeat_results.json, output/pz3_repeat_final_*.log.
Wstępny zestaw miał jedną przejściową odmowę inicjalizacji Tcl; pełny zestaw
i osobny smoke GUI wykonały te scenariusze bez pomijania.

## Lżejszy układ i bezpieczny powrót do aplikacji

Modal ma dwa regulowane panele: listę plików i duży podgląd (domyślnie około
40% / 60%). Lista pokazuje nazwę i decyzję; pełny problem jest pod listą.
Pasek nad panelami łączy zmianę nazwy i odrzucenie z narzędziami zoomu.
Odrzucanie zbiorcze znajduje się pod „Więcej”, a reguły, ścieżka źródła i skróty
pod „Zasady i skróty”. Stała stopka zawiera Anuluj oraz główne Zapisz i kontynuuj.

Rozmiar domyślny 1160×760 jest ograniczany do ekranu, minimum wynosi 900×600.
W kontroli wizualnej obu motywów płótno podglądu miało odpowiednio 659×504
i 503×344 px; wszystkie przyciski były widoczne.

Po zamknięciu kontroli nazw, wyboru źródła i okna postępu wspólny helper
restore_parent_after_modal przywraca widocznego rodzica i fokus.
Poprzedni grab wraca wyłącznie do istniejącego, widocznego elementu.
Ukryty grab nie blokuje głównego okna; nowy aktywny modal zachowuje obsługę.
Niezależnie zminimalizowane okno narzędzi pozostaje zminimalizowane, a dostępna
staje się aplikacja główna.

Regresja obejmuje rzeczywistą korektę nazwy → zatwierdzenie → import PZ3,
zminimalizowane i ukryte okno główne, ukryty poprzedni modal, zagnieżdżone modale,
okno postępu i kliknięcie w aplikacji po zakończeniu. Scenariusz obejmuje również
zdarzenia odzyskiwania okna używane przez AutoAnnotationApp.

### Weryfikacja układu i powrotu z modali — 2026-09-17

- Testy obsługi nazw, powrotu okien i niezależnego minimalizowania: **45 PASS**.
- Rzeczywisty import PZ3 po zmianie nazwy i ukryciu okna aplikacji: **PASS**.
- Pełny unittest discover: **764 testy OK**.
- Dodatkowe testy Z2: **64 PASS** łącznie. Jeden test wymagał osobnego procesu
  po błędzie inicjalizacji Tcl w fixture; izolowane ponowienie przeszło.
- Smoke audytu i final hardening (GT, VERIFY, SEAL, controlled comparison): **PASS**.
- Jasny/ciemny motyw, 1160×760 oraz 900×600: kontrola wizualna **PASS**.
- Backend registry/ranking bez zmian; git diff --check bez błędów.

Nowe testy: test_source_review_window_return.py oraz przypadek importu po korekcie
w test_pz3_ingest_integration.py.
Raporty: output/source_layout_results.json, output/source_review_layout_results.json.
