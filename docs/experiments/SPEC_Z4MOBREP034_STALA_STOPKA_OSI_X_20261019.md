# Z4MOBREP034 — niewidoczna stopka osi X przy przeciąganiu separatora

Data: 2026-10-19. Zakres: Desktop, GUI wykresu **Dane źródłowe → Czasy szczegółowe**.

## Zgłoszenie

Zrzuty porównawcze z tej samej sesji P1-R0-FP32-B: po zmniejszeniu panelu wykresu
operator nadal widzi oś X i tabelę, ale stopka objaśniająca reprezentację osi
całkowicie znika; po powiększeniu wykresu znów się pojawia. To nie błąd
pomiaru ani nie efekt przełącznika „Łącz punkty sąsiednich klatek”.

## Przyczyna

W `z4_mobile_report_browser.py` wewnątrz górnego panelu `ttk.PanedWindow`
`latency_canvas` (żądana wysokość 320 px) był pakowany przed etykietą stopki.
Tk rozdziela dostępną przestrzeń według kolejności pakowania. Kiedy operator
rozszerza tabelę i kurczy górny panel, elastyczne płótno może otrzymać
przestrzeń przed stopką; stopka nie jest mapowana.

## Zmiana

Etykieta stopki otrzymuje `side=tk.BOTTOM` oraz
`before=self.latency_canvas`. Dzięki temu Tk rezerwuje miejsce dla dolnej
stopki przed rozmiarem elastycznego płótna. Checkbox pozostaje nad wykresem;
stopka pozostaje pod wykresem, a wysokość płótna skaluje się do dostępnego
obszaru. Zachowane zostają ustawienia podziału okna i jego przewijana tabela.

## Niezmienniki

- Brak zmian w serii, osi X/Y, zoomie, panoramowaniu, identyfikatorach klatek.
- Brak zmian łączenia punktów ani ich kolorów.
- Nie dotykamy ZIP, sesji, GT, sidecarów, modeli, Androida, metryk ani TeX.
- Ta poprawka nie zwiększa minimalnego rozmiaru panelu wykresu: przy ręcznym
  zmniejszeniu go do ekstremalnie małej wysokości rzędu kilkudziesięciu pikseli
  interfejs fizycznie nie pomieści już jednocześnie paska, stopki i wykresu.

## Testy odbiorcze

1. Włącz sesję P1-R0-FP32-B 19.10 i **Czasy szczegółowe**.
2. Przesuwaj separator wykres/tabela tak, by tabela pokazywała wiele wierszy;
   stopka osi X ma nadal pozostawać widoczna pod wykresem.
3. Zmień powiększenie i checkbox łączników; skale i pomiary bez zmian.
4. Zmniejsz i powiększ okno; stopka nie może przenikać do tabeli.
5. Uruchom `test_z4mobrep034_footer_packing.py` oraz regresję 031/032/029.
