# Dataset uczestnika PZ3

Stan względem `98aaeef`: każdy nowo zapisany uczestnik zawiera `dataset_id`.
Rejestr rozwiązuje go jednym zapytaniem `models.run_id → training_runs.dataset_id`.
Nazwy plików, katalogi i nazwy runów nie służą do ustalania datasetu.

Okno „Modele uczestniczące w eksperymencie” pokazuje Run i Dataset w zwartej
kolumnie Pochodzenie, a pełne wartości w profilu zaznaczonego modelu.
Menu sortowania udostępnia osobno Run i Dataset (sortowanie naturalne).
Rozwinięcie widoku opisuje [profil modelu](pz3_participant_model_profile.md).

## Kontrakt i aktualność audytu

- `complete` / `known` bez runu lub datasetu nie są dostępne jako poprawni uczestnicy.
- Dotychczasowa obsługa słabszego provenance pozostaje zachowana.
- `participants.json` ma wersję `alpr.evaluation_track_participants.v2` i zapisuje dataset każdego modelu.
- Fingerprint obejmuje `model_id | sha256 | run_id | dataset_id | provenance_status`.
- Zmiana powiązania run–dataset w rejestrze blokuje użycie wcześniejszego audytu.
  Wymagane są ponowny wybór uczestników i ponowny audyt.
- Ręczna rejestracja pozostaje bez zmian: `known`, dataset z wybranego runu.

## Starsze tory

Odczyt nigdy nie uzupełnia zapisanego datasetu bieżącymi danymi rejestru.

Starszy DRAFT bez `dataset_id` wymaga ponownego wyboru modeli i audytu.
Samo otwarcie nie przepisuje `participants.json`.

SEALED i RETIRED odczytują uczestników i stan audytu z zamrożonego kontraktu.
Dla starszych pieczęci obsługiwany jest pierwotny fingerprint bez datasetu.
Historyczne artefakty i stan SQLite nie są przepisywane podczas odczytu.
Późniejsza zmiana rejestru nie zmienia zapisanej historii zapieczętowanego toru.

## Granice zmiany

Mechanika porównywania obrazów z train/val, selekcja RAW, GT, SEAL,
controlled ranking, bridge i kontrola SHA pozostają bez zmian.
Dodano jedynie metadane uczestnika, ich prezentację i kontrolę zamrożenia pochodzenia.

Testy regresyjne: `tests/test_participant_dataset_lineage.py`,
`tests/test_pz3_participant_sorting.py` oraz `tests/test_pz3_dialog_interactions.py`.

## Weryfikacja (2026-09-16)

- Pełne `unittest discover`: **686 testów OK**.
- Dodatkowe testy funkcji Z2 przez pytest: **64 testy OK**.
- `pz3_final_hardening_smoke.py`: **PASS**.
- `pz3_sample_review_smoke.py`: **PASS**.
- Kontrola tabeli uczestników w szerokości 1160 i 720 px, w tym przewijania Dataset.
- Brak zmian względem `98aaeef` w ranking/bridge, `pz3_comparison.py`,
  `experiment_service.py`, `track_service.py`, selekcji RAW i GT.

Smoke używa tymczasowego Workspace i deterministycznych predykcji rankingowych;
nie stanowi pomiaru jakości modeli w rzeczywistym eksperymencie.
