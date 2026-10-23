# Z4MOBREP033 — łączniki punktów bez zmiany skali wykresu (19.10.2026)

## Zmiana względem Z4MOBREP031 / proponowanego Z4MOBREP032

Checkbox ma krótką nazwę: **„Łącz punkty sąsiednich klatek”**.
Nie steruje on skalowaniem ani sposobem rozmieszczenia pomiarów. Zmienia wyłącznie obecność odcinków pomiędzy rzeczywiście kolejnymi identyfikatorami klatek, dla których istnieją wartości etapu. W szczególności nie łączy 384 z 386 ani 391 z 585.

Rozmieszczenie punktów jest wyliczane automatycznie: dla krótkich sesji z bardzo nierównymi odstępami numerów klatek przyjmowane są równe odległości *graficzne*, a oś nadal pokazuje rzeczywiste ID (np. 384, 386, ..., 585). Przy innych sesjach położenia odpowiadają numerom klatek / osi źródłowej. Nie jest to oś czasu — nachylenia łączników nie stanowią pochodnych czasowych.

Przełączenie checkboxa **nie zmienia** `_latency_x_view`, `_latency_full_x`, położenia punktów, skali Y, `pan` ani statusów raportu. Tylko jawne użycie rolki, przeciągnięcia lub dwukliku (resetu) zmienia nawigację. Przeliczenie pełnej geometrii przy rysowaniu korzysta z tej samej niezmiennej mapy X, niezależnie od checkboxa.

Checkbox jest domyślnie zaznaczony, aby zachować wcześniejszy wygląd dla następujących po sobie numerów klatek. Jeśli znane ID klatek nie są dostępne, przełącznik nie tworzy pozornej ciągłości na osi czasu/numerów pomiaru. Dla śladów bardzo gęstych (>350 widocznych rekordów) pozostaje bezpieczna wizualizacja min–max per kolumna, bez tworzenia interpolowanych wartości.

Opis osi X i notatka o ukrytych pomiarach są umieszczone w osobnym wierszu *pod wykresem* (poprawa układu Z4MOBREP032), aby nie przykrywał ich separator z tabelą.

## Odbiór

1. Sesja P1-R0-FP32-B 19.10: 8 punktów każdej serii oraz etykiety rzeczywistych klatek 384, 386–391, 585.
2. Przy włączonym checkboxie: 5 odcinków na serię łączących 386–391, bez odcinków do 384 i 585.
3. Po wyłączeniu: dokładnie te same punkty w dokładnie tych samych pikselach i zakresach osi; znikają **wyłącznie łączniki**.
4. Ustawić zoom np. na 3 środkowe obserwacje; włączyć/wyłączyć checkbox i sprawdzić, że nie zmienia się zakres ani położenie widoku. Przesunięcie wykresu pozostaje niezmienione.
5. Podpis osi zawsze jest czytelny pod wykresem, również po zmianie podziału przestrzeni wykres/tabela.
6. Wartości pomiarów, czasy, histogramy, eksporty, GT, pliki archiwów i modele pozostają bez zmian.

## Uwagi o źródle i bezpieczeństwie

Nie nadpisujemy danych surowych ani obliczeń metryk. Podczas nakładania patcha wymagamy zgodnych sum SHA-256 dla kompletnego stanu Z4MOBREP031 **albo** Z4MOBREP032; instalator działa transakcyjnie, zapisuje kopię bezpieczeństwa i blokuje obce wersje plików. Dokument Z4MOBREP032 (jeśli został zastosowany) należy interpretować łącznie z tą specyfikacją; jej opis checkboxa zastępuje niniejszy kontrakt.
