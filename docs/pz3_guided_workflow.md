# PZ3 — prowadzenie przez przygotowanie eksperymentu

Warstwa `gui/pz3_workflow_view.py` tłumaczy istniejący stan gotowości na następny
krok. Nie zapisuje nowej maszyny stanów. Readiness i guardy backendu pozostają
źródłem dostępności operacji.

Kolejność: modele → obrazy → sprawdzenie niezależności → wybór próby →
sprawdzenie finalnej próby → Ground Truth → weryfikacja → pieczęć → porównanie.
Istniejący GT kieruje od razu do weryfikacji; tory validation/char zachowują
dotychczasowe ścieżki. SEALED i RETIRED nie wracają do przygotowania.

## Import i audyt

Dodawanie obrazów wykonuje kontrolę nazw, fingerprinty i deduplikację, następnie
zapisuje kandydatów. Sprawdzenie niezależności użytkownik uruchamia osobnym
przyciskiem. Nie powstaje automatycznie audyt CURRENT ani wynik eksperymentu.
Do tego czasu istniejące guardy blokują GT, VERIFY i SEAL.

Pierwszy audyt: „do wykonania”; unieważniony wynik wcześniejszego sprawdzenia:
„wymaga ponowienia”. Przy pustym torze komunikat wskazuje brak modeli albo obrazów.

Widok odczytuje istniejący sample_selection.json także po ponownym otwarciu toru.
Po commit próbki podpowiada „Sprawdź finalną próbę”. Podzbiór zachowany po audycie
nadal jest wybraną próbą. Dodanie nowych obrazów kieruje ponownie do jej wyboru.
Odczyt służy wyłącznie prezentacji; nie zmienia kontraktu ani jego walidacji.

## Hierarchia i picker

Tylko następny dostępny krok ma Accent.TButton. Otwarty formularz nowego toru
ma własną główną akcję. Nagłówek pokazuje kontekstowy audyt i Ground Truth,
a sekcja przygotowania — liczbę modeli i obrazów.

Picker „Wybierz modele do eksperymentu” rozdziela:
- profil wskazanego wiersza,
- udział przez pole „W eksperymencie”, spację i Dodaj/Usuń z eksperymentu,
- zarządzanie katalogiem w osobnej sekcji; usuwanie z katalogu jest pod „⋯”.

Licznik wyboru pozostaje widoczny niezależnie od wskazanego wiersza.
Zatwierdzenie wyboru jest głównym CTA pickera. Profil i sortowanie zachowane.

## Regresja

Testy sprawdzają kontekstowe statusy, dziewięć etapów, jeden wyróżniony przycisk,
ponowne otwarcie próbki, jawny audyt, zachowanie blokad i operacje pickera.
Backend registry/ranking, RAW selection, GT i controlled comparison pozostają
bez zmian. Lokalny zapis hashy: output/pz3_guided_protected.json.

## Wyniki weryfikacji — 2026-09-16

- Pełne unittest discover: **740 testów OK**.
- Dodatkowe testy funkcji Z2: **64 PASS**.
- pz3_audit_ux_smoke.py: **PASS** (10 kandydatów → jawny audyt → 6 obrazów).
- pz3_final_hardening_smoke.py: **PASS**.
- pz3_sample_review_smoke.py: **PASS**.
- Kontrola GUI: jasny/ciemny motyw, 1140×780 i 1000×700, profil i akcje dostępne.
- 36 chronionych plików registry/ranking/RAW/GT/comparison: identyczne SHA-256.
- git diff --check: bez błędów.

Raporty lokalne: output/pz3_guided_results.json i output/pz3_guided_final_*.log.
Smoke korzystają z izolowanych danych i deterministycznych predykcji porównania;
wyniki nie stanowią rzeczywistego pomiaru MT-n vs MT-s.
