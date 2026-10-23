# Z4MOBREP031 — czytelność wykresu czasów przy nieregularnych ID klatek

**Data:** 2026-10-19. **Zakres:** GUI przeglądarki raportów ALPR (Desktop) oraz funkcje pomocnicze widoku. Bez zmian archiwów, śladów czasowych, agregacji, metryk GT, modeli, Androida i tekstu pracy.

## Problem odtworzony w archiwum P1 z 19.10.2026

`traces.csv` ma osiem wyników dla `frame_id` = `384, 386, 387, 388, 389, 390, 391, 585` (trzy serie czasu). Widok osi X `385–394` pokazuje **6/8** rzeczywistych pomiarów; klatka `384` jest poza lewą granicą, a klatka `585` poza prawą. Poprzednia legenda nadal pokazywała `n=8`, bez rozróżnienia liczby widocznych punktów. Duża luka `391→585` po oddaleniu ścieśniała pozostałe punkty przy lewej granicy.

## Kontrakt GUI

1. Domyślny przełącznik „Przy dużych lukach: równe odstępy pomiarów (etykiety = prawdziwe ID klatek)” w panelu **Dane źródłowe → Czasy szczegółowe**. Włącza *tylko w krótkich, ściśle rosnących seriach ID klatek z dużą luką* widok o równych odległościach między kolejnymi pomiarami. Podpisy osi zachowują **prawdziwe ID**: 384, 386, …, 585. Opis osi wyraźnie stwierdza, że to **nie skala czasu**. Nie interpolujemy ani nie fabrykujemy brakujących pomiarów 392–584.
2. Odznaczenie przełącznika przywraca dotychczasowy **numeryczny odstęp ID klatek**. Nie zmienia żadnej wartości Y, opóźnienia, rekordu źródłowego ani statystyk tabeli.
3. Zmiana trybu wyświetlania resetuje wyłącznie zakres zoomu. Rolka, przesuwanie myszą i dwuklik-reset pozostają dostępne.
4. W powiększonym zakresie pokazujemy `n=ogółem, wid.=liczba_widocznych` w legendzie serii i w stopce `widoczne/ogółem · poza: ◀lewo ▶prawo`. W pełnym zakresie legendę pozostawiamy jako `n=ogółem`.
5. Linie łączą wyłącznie próbki, które istnieją i stanowiły ciągłość według pierwotnego `ID klatki`; luka 391→585 nadal **nie zostaje połączona** fikcyjną linią.
6. Dla danych bez dużej luki, niesortowanych, z duplikatami, z osią czasową zamiast ID lub nadmiernie długich serii zostaje oryginalna oś numeryczna.

## Kryteria odbioru

- Testy nowych funkcji i metody rysowania dla oryginalnych ID 384…585, w tym zoom `385–394` i 6/8 widocznych.
- Test regresyjny przewijania prawej karty przy fokusie na liście (`Z4MOBREP029`).
- Odbiór ręczny w Windows GUI na sesji `P1-R0-FP32-B` z 19.10: osiem widocznych punktów w trybie równomiernym, surowe ID na podpisach, brak łączenia przez lukę, przełączenie na rzeczywisty odstęp, świadoma liczba punktów poza oknem podczas zoomu.
- Nienaruszalność `traces.csv`, `_latency_full_x` zapisuje tylko bieżącą **przestrzeń widoku**; sumy i p95 pochodzą wyłącznie z danych źródłowych.

Status w chwili przygotowania: **implementacja zaproponowana, odbiór Windows użytkownika oczekuje**.
