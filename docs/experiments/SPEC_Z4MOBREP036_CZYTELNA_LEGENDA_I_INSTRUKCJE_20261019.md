# Z4MOBREP036 — czytelna legenda osi czasu i instrukcje wykresu

**Data:** 2026-10-19
**Obszar:** Desktop → Raporty ALPR → Dane źródłowe → Czasy szczegółowe
**Stan wejściowy:** po Z4MOBREP035 (SHA-256 `z4_mobile_report_browser.py` = `85ee60bb892676e73ea13ba04d59baf8e526165d2fd691d1c7a573565191ca05`).

## Zgłoszenie

Na rzeczywistym zrzucie sesji `P1-R0-FP32-B` z 19.10.2026 długie opisy serii, szczególnie `MZ: inferencja modelu znaków`, nachodzą na instrukcję `Rolka: oś X · przeciągnij: przesuń · dwuklik: reset` w prawym górnym rogu płótna. Tekst jest nieczytelny; nie jest to błąd samych pomiarów.

## Zmiana

1. Legenda otrzymuje odrębny rząd/rzędy na płótnie, a instrukcja obsługi wykresu osobny rząd **poniżej** legendy.
2. Liczba kolumn legendy zależy od szerokości płótna: 3 dla szerokich, 2 dla średnich i 1 dla wąskich okien. W wąskich oknach nazwy serii są krótsze, ale pozostają semantycznie zgodne z pomiarami inferencji.
3. Pole wykresu zaczyna się poniżej legendy i instrukcji; zawartość nie nakłada się na siatkę.
4. Obliczenia czasu, n, wartości MT/MZ/ALPR, zapisów źródłowych, skali i zakresu osi X/Y, reguły łączenia sąsiadujących ID klatek, obsługi zoomu i hover pozostają bez zmian. Zmienione są wyłącznie pikselowe pozycje elementów po dostosowaniu wysokości nagłówka.

## Zabezpieczenia i testy

- Testy renderujące rzeczywisty `tk.Canvas` przy szerokościach 320, 420, 580, 760, 1050, 1200 i 1600 px sprawdzają geometryczny brak przecięć prostokątów tekstowych oraz brak przycięcia opisów.
- Test sprawdza, że pozioma linia siatki rozpoczyna się **poniżej** legendy i instrukcji.
- Test regresyjny wykresu przy zoom `(10, 40)` sprawdza identyczny widok osi oraz współrzędne 15 widocznych punktów (3 serie × 5 klatek) po wyłączeniu łączników.
- Zestaw regresyjny z Z4MOBREP031 i Z4MOBREP035 sprawdza niezmienność danych, punktów, osi i znaczenia serii.

## Odbiór przez operatora

1. Wybrać sesję `P1-R0-FP32-B` z 19.10.2026 w **Dane źródłowe → Czasy szczegółowe**.
2. Potwierdzić, że trzy czytelne pozycje legendy nie nachodzą na instrukcję gestów.
3. Zmniejszyć okno i sprawdzić, czy legenda przechodzi na kolejne wiersze.
4. Przybliżyć i przesunąć wykres, przełączać checkbox `Łącz punkty sąsiednich klatek`; zakres i zoom muszą pozostać stabilne.
5. Sprawdzić, czy stopka osi X pozostaje widoczna przy przeciąganiu separatora.

**Ograniczenie:** Testy na kopii kodu oraz w Tk nie zastępują odbioru GUI na komputerze użytkownika.

**Brak modyfikacji:** archiwa ZIP, telemetria, sidecary, GT, modele, Android, APK, praca TeX, statystyki naukowe.
