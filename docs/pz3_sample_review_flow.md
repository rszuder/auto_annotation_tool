# Wybór próby eksperymentalnej przed Ground Truth

Uzgodnienie z 2026-09-16 zastępuje wcześniejszy wspólny krok wyboru i GT.
Finalna próba jest wybierana z audytowanej puli na podstawie surowych obrazów,
bez wykonywania preanotacji. Preanotacja Ground Truth jest wykonywana dopiero
po zatwierdzeniu próby i ponownym audycie jej finalnego składu.

## Praca użytkownika

1. W PZ3 wybierz uczestników i dodaj szeroką pulę. Rozstrzygnij audyt.
2. Użyj **Wybierz próbę w Z2…**.
3. Oglądaj surowe zdjęcia. **Spacja** lub kliknięcie statusu przełącza
   **W PRÓBIE / POZA PRÓBĄ**, również dla zdjęć z zerową liczbą anotacji.
4. Zaznacz grupę przez Ctrl/Shift i użyj **Dodaj zaznaczone do próby** albo
   **Usuń zaznaczone z próby** w menu PPM. Dostępne są również przyciski nad listą.
5. Licznik **Wybrano: X / Y** jest globalny. Filtry **Wszystkie**, **W próbie**
   i **Poza próbą** nie zmieniają zapamiętanego wyboru. Działają nawigacja,
   zoom i pełny ekran. Zaznaczenie grupowe pozostaje przy nawigacji między obrazami.
6. **Zatwierdź próbę i wróć do PZ3** zapisuje dokładny skład finalnej próby.
   GT nadal nie istnieje, a audyt otrzymuje status STALE.
7. Ponów audyt finalnej próby. Dopiero CURRENT odblokowuje **Przygotuj GT w Z2**.
8. Teraz uruchom **Preanotacja…** na finalnej próbie albo wykonaj anotacje ręcznie.
   Sprawdź wszystkie tablice i narożniki, zapisz GT, wykonaj VERIFY i SEAL.
9. Controlled ranking używa dokładnie finalnych członków toru i odpowiadającego im GT.

**Anuluj i wróć** nie zmienia draftu i nie zapisuje GT.
Wybór pozostaje w pamięci bieżącej sesji aplikacji, aby umożliwić kontynuację.
Poprzedni podgląd Z2 i jego zatwierdzenia anotacji są przywracane po wyjściu.

## Kontrakt

- Wejście wymaga DRAFT tablic, uczestników, niepustej puli i CURRENT.
  Opublikowane GT blokuje ponowny dobór próby.
- Kontekst `_pz3_sample_selection_context` i zbiór
  `_experiment_sample_selected_sha256` są niezależne od kontekstu GT
  oraz approval anotacji i treningu.
- Podgląd korzysta z istniejącego canvasu Z2, listy i cache.
  Lekkie rekordy obrazów mają początkowo wymiary 1×1; właściwy obraz
  i jego rozmiar są odczytywane dopiero przy wyświetlaniu.
- RAW nie uruchamia modeli, nie tworzy XML, nie zapisuje GT, nie rysuje
  polygonów i nie eksportuje datasetu.
- `commit_sample_selection()` przyjmuje wybrane SHA i migawkę audytu/puli;
  nie przyjmuje XML ani metadanych GT.
- Transakcja sprawdza ponownie membership i audit_id. Błędy zapisu plików
  lub zatwierdzania bazy przywracają poprzednie członkostwo i kopie.
- Oryginalne pliki użytkownika pozostają nietknięte. Usuwane są tylko
  niewybrane kopie toru i jego stagingu.
- `sample_selection.json` zawiera metodę, liczby, wybrane SHA, datę,
  identyfikator audytu oraz opcjonalną notatkę kryteriów. Manifest i SEAL
  obejmują go integralnością jak przed rozdzieleniem etapów.
- Standardowe `prepare_gt_workspace()`, `publish_working_gt()`, VERIFY,
  SEAL oraz zamrożeni uczestnicy i zabezpieczenia rankingu zachowują kontrakt:
  **TRACK MEMBERS == GT IMAGES == RANKING IMAGES**.

## Weryfikacja

Testy: `test_pz3_reviewed_sample.py`, `test_pz3_sample_review_gui.py`.

Smoke: `python tests/pz3_sample_review_smoke.py`.
Sprawdza 20 surowych obrazów, zero anotacji i brak wywołań GT/inference podczas
wyboru 6 zdjęć, anulowanie/powrót, filtry, licznik, spację i kliknięcie statusu.
Po commit sprawdza brak GT i STALE, potem reaudyt, rzeczywistą preanotację CPU
wyłącznie 6 obrazów, korektę GT, VERIFY, SEAL i porównanie dwóch uczestników.

Obrazy i ręczne GT smoke są syntetyczne, a predykcje rankingu deterministyczne.
To test integracji, nie wyniki eksperymentu pracy dyplomowej.
Stary lifecycle jest dodatkowo sprawdzany przez `tests/pz3_final_hardening_smoke.py`.
