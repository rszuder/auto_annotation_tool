# Dobór próby rankingowej i GT w Z2

Uzgodnienie użytkownika z 2026-09-15 zmienia wcześniejszy handoff
`handoff_pz3_sample_selection_in_z2.md`: preanotacja dotyczy szerokiej,
już zaakceptowanej przez audyt puli. Ręczne zatwierdzenie zdjęcia w Z2
oznacza wybór do finalnej próby i akceptację jego GT po sprawdzeniu
wszystkich tablic i narożników.

## Praca użytkownika

1. W PZ3 wybierz uczestników i dodaj szeroką pulę. Rozstrzygnij audyt.
2. Użyj **Dobierz próbę i GT w Z2…**.
3. Uruchom **Preanotacja…** z wybranym modelem dla całej puli.
4. Przeglądaj i poprawiaj anotacje. Zatwierdzaj interesujące zdjęcia:
   spacją na liście, przez PPM → **Oznacz zaznaczone jako OK**,
   a w pełnym ekranie spacją lub kliknięciem statusu **W PRÓBIE / POZA PRÓBĄ**.
   Ponowne przełączenie cofa zatwierdzenie.
5. Licznik zatwierdzonych dotyczy całej puli i pozostaje niezależny od
   bieżącego zdjęcia, przewijania i filtra. Jest widoczny w górnym pasku,
   a w pełnym ekranie także na klikalnym statusie.
6. **Przekaż zatwierdzone do PZ3** redukuje DRAFT do tych zdjęć i zapisuje
   odpowiadający im XML GT. Oryginalne pliki użytkownika pozostają nietknięte.
7. Ponów audyt finalnej próby, potwierdź kompletność GT, wykonaj VERIFY i SEAL.
8. Ranking korzysta dokładnie z zatwierdzonej próby.

**Wróć bez przekazania** zachowuje robocze anotacje i zatwierdzenia do
kontynuacji. Nie zmienia członków DRAFT ani nie publikuje GT.

## Kontrakt

- Nowy tryb wymaga DRAFT tablic, uczestników, niepustej puli i aktualnego audytu.
  Nie otwiera selekcji po publikacji GT; późniejsze korekty GT mają istniejącą trasę.
- Tryb korzysta z istniejącego kontekstu edycji GT Z2 z flagą
  `sample_selection`. Pozwala na preanotację i ręczną korektę.
- Zatwierdzenia są zapisywane przez istniejący mechanizm Z2. Commit
  przelicza wybrane nazwy na SHA z migawki puli i sprawdza ją ponownie w transakcji.
- Finalni członkowie toru = obrazy w finalnym GT = obrazy rankingu.
- Commit zapisuje członków, GT i stan audytu razem. Błąd zapisu plików lub
  zatwierdzania transakcji przywraca poprzednie dane i pliki.
- Po commit audyt jest STALE. GT jest już w DRAFT, ale VERIFY i SEAL
  pozostają niedostępne do ponownego audytu.
- `sample_selection.json` zapisuje metodę, liczby kandydatów i wybranych,
  SHA wybranych obrazów, identyfikator audytu i datę. Manifest oraz SEAL
  obejmują ten plik integralnością; stare tory nie wymagają nowego artefaktu.
- Pełny snapshot AUTO pozostaje niezmieniony. Metryki AUTO względem finalnego
  GT obejmują wyłącznie finalną próbę.
- Indeksy członków pozostają stabilne; wybór nie jest oparty na pozycji w GUI.

## Weryfikacja

Testy: `test_pz3_reviewed_sample.py`, `test_pz3_sample_review_gui.py`.
Smoke: `python tests/pz3_sample_review_smoke.py`.

Smoke używa tymczasowego Workspace, 20 syntetycznych obrazów, rzeczywistej
preanotacji CPU na kopii lokalnego modelu i wyboru 6 zdjęć przez GUI.
Sprawdza reaudyt, GT, VERIFY, SEAL i ranking dwóch zamrożonych uczestników.
Predykcje rankingu i poprawione GT są deterministyczną fiksturą testową,
nie wynikami eksperymentu pracy dyplomowej.
